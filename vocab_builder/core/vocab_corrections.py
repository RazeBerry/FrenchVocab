"""Reviewed, single-catalog corrections to stored vocabulary and Anki state."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vocab_builder.core.anki_identity import identity_path, identity_text, load_identity, save_identity
from vocab_builder.core.file_safety import atomic_copy_file, atomic_write_text, file_lock
from vocab_builder.core.history_logger import TranslationLogger
from vocab_builder.core.vocab_repository import VocabRepository, choose_insert_position
from vocab_builder.languages import get_language_config
from vocab_builder.latex_repository import LatexRepository, find_entry_bounds, parse_all_entries
from vocab_builder.models import WordEntry, normalize_word_key


class CorrectionError(ValueError):
    """A correction cannot safely be applied to the current catalog."""


def _key(word: str) -> str:
    return word.strip().lower()


def _digest(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def _text(data: bytes, label: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorrectionError(f"{label} is not valid UTF-8") from exc


def _entry_payload(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"word", "type", "definitions", "examples"}:
        raise CorrectionError(f"{label} must have word, type, definitions, examples")
    if not isinstance(value["word"], str) or not value["word"].strip():
        raise CorrectionError(f"{label}.word must be nonempty text")
    if not isinstance(value["type"], str):
        raise CorrectionError(f"{label}.type must be text")
    if not isinstance(value["definitions"], list) or any(
        not isinstance(item, str) for item in value["definitions"]
    ):
        raise CorrectionError(f"{label}.definitions must be a text list")
    if not isinstance(value["examples"], list) or any(
        not isinstance(item, list) or len(item) != 2
        or any(not isinstance(part, str) for part in item)
        for item in value["examples"]
    ):
        raise CorrectionError(f"{label}.examples must be a list of text pairs")
    return value


def _parsed_payload(entry: WordEntry) -> dict[str, Any]:
    return {
        "word": entry.word,
        "type": entry.type,
        "definitions": entry.definitions,
        "examples": [list(pair) for pair in entry.examples],
    }


def _index(content: str, entry_cmd: str) -> dict[str, tuple[dict[str, Any], str, int, int]]:
    parser = LatexRepository(Path("/dev/null"), entry_cmd)
    indexed: dict[str, tuple[dict[str, Any], str, int, int]] = {}
    for _groups, start, end in parse_all_entries(content, entry_cmd):
        parsed = parser._parse_entry_at(content, start)
        if parsed is None or parsed[1] != end:
            raise CorrectionError(f"Cannot parse entry block at character {start}")
        payload = _parsed_payload(parsed[0])
        key = _key(payload["word"])
        if key in indexed:
            raise CorrectionError(f"Duplicate stored headword key: {key}")
        indexed[key] = (payload, content[start:end], start, end)
    return indexed


def _validate_patch(patch: Any, language: str) -> list[dict[str, Any]]:
    if not isinstance(patch, dict) or patch.get("version") != 1 or patch.get("language") != language:
        raise CorrectionError("Patch version or language does not match")
    patch_id = patch.get("patch_id")
    if not isinstance(patch_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", patch_id):
        raise CorrectionError("patch_id must be a safe, nonempty file component")
    base = patch.get("base")
    if not isinstance(base, dict) or set(base) != {
        "vocab_sha256", "tracker_sha256", "identity_sha256"
    }:
        raise CorrectionError("Patch base must name vocab, tracker, and identity hashes")
    for name, value in base.items():
        if value is None and name == "identity_sha256":
            continue
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise CorrectionError(f"Invalid base.{name}")
    corrections = patch.get("corrections")
    if not isinstance(corrections, list) or not corrections:
        raise CorrectionError("Patch needs at least one correction")
    seen_ids: set[str] = set()
    for row in corrections:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
            raise CorrectionError("Every correction needs a nonempty id")
        if row["id"] in seen_ids:
            raise CorrectionError(f"Repeated correction id: {row['id']}")
        seen_ids.add(row["id"])
        _entry_payload(row.get("before"), f"{row['id']}.before")
        _entry_payload(row.get("after"), f"{row['id']}.after")
        if not isinstance(row.get("retire"), list):
            raise CorrectionError(f"{row['id']}.retire must be a list")
        for item in row["retire"]:
            _entry_payload(item, f"{row['id']}.retire")
        keep = row.get("keep_identity_of", row["before"]["word"])
        if not isinstance(keep, str) or keep not in [
            item["word"] for item in [row["before"], *row["retire"]]
        ]:
            raise CorrectionError(f"{row['id']}.keep_identity_of must name before or retire")
        row["keep_identity_of"] = keep
        for field in ("reasons", "sources"):
            if not isinstance(row.get(field), list) or any(
                not isinstance(item, str) for item in row[field]
            ):
                raise CorrectionError(f"{row['id']}.{field} must be a text list")
    return corrections


def _tracker_payload(data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(_text(data, "Tracker"))
    except json.JSONDecodeError as exc:
        raise CorrectionError("Tracker is not valid JSON") from exc
    if not isinstance(value, dict) or not isinstance(value.get("words"), list) or not isinstance(
        value.get("entry_order"), list
    ):
        raise CorrectionError("Tracker needs words and entry_order lists")
    for field in ("words", "entry_order"):
        values = value[field]
        if any(not isinstance(key, str) or key != _key(key) for key in values):
            raise CorrectionError(f"Tracker {field} contains invalid keys")
        if len(values) != len(set(values)):
            raise CorrectionError(f"Tracker {field} contains duplicate keys")
    return value


def _seed(key: str, aliases: dict[str, str]) -> str:
    seen: set[str] = set()
    while key in aliases:
        if key in seen:
            raise CorrectionError("Anki identity aliases contain a cycle")
        seen.add(key)
        key = aliases[key]
    return key


def _guid(seed: str, namespace: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{namespace.lower()}::{seed}").hex


def _unified(before: str, after: str, label: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"{label}:before", tofile=f"{label}:after",
    ))


def _render(
    content: str, tracker: dict[str, Any], aliases: dict[str, str],
    corrections: list[dict[str, Any]], entry_cmd: str, namespace: str,
) -> tuple[str, dict[str, Any], dict[str, str], list[dict[str, Any]], list[dict[str, str]]]:
    original = _index(content, entry_cmd)
    # The app finds duplicates by the accent-free key, so a corrected headword
    # that matches another live entry only up to accents is still a collision.
    duplicate_keys: dict[str, set[str]] = {}
    for key, (payload, _block, _start, _end) in original.items():
        duplicate_keys.setdefault(normalize_word_key(payload["word"]), set()).add(key)
    touched: set[str] = set()
    targets: set[str] = set()
    for row in corrections:
        old = [row["before"], *row["retire"]]
        keys = [_key(item["word"]) for item in old]
        if len(keys) != len(set(keys)) or any(key in touched for key in keys):
            raise CorrectionError(f"{row['id']} touches an entry twice")
        touched.update(keys)
        for item, key in zip(old, keys):
            if key not in original or original[key][0] != item:
                raise CorrectionError(f"{row['id']} before/retire mismatch: {item['word']}")
        target = normalize_word_key(row["after"]["word"])
        if target in targets or duplicate_keys.get(target, set()) - set(keys):
            raise CorrectionError(f"{row['id']} collides with live headword: {row['after']['word']}")
        targets.add(target)

    next_tracker = dict(tracker)
    order = list(tracker["entry_order"])
    words = set(tracker["words"])
    next_aliases = {key: _seed(key, aliases) for key in aliases}
    diffs: list[dict[str, Any]] = []
    retired: list[dict[str, str]] = []
    for row in corrections:
        old = [row["before"], *row["retire"]]
        keys = [_key(item["word"]) for item in old]
        target = _key(row["after"]["word"])
        keep_key = _key(row["keep_identity_of"])
        kept_seed = _seed(keep_key, aliases)
        old_seeds = {key: _seed(key, aliases) for key in keys}
        for item, key in zip(old, keys):
            if old_seeds[key] != kept_seed:
                retired.append({"headword": item["word"], "guid": _guid(old_seeds[key], namespace)})
        old_blocks = [original[key][1] for key in keys]
        new_block = VocabRepository.format_latex_entry(
            row["after"]["word"], row["after"]["type"],
            row["after"]["definitions"], [tuple(pair) for pair in row["after"]["examples"]],
            entry_cmd,
        )
        if target == keys[0] and len(keys) == 1:
            bounds = find_entry_bounds(content, entry_cmd, row["before"]["word"])
            if bounds is None or content[slice(*bounds)] != old_blocks[0]:
                raise CorrectionError(f"{row['id']} entry bounds changed")
            content = content[:bounds[0]] + new_block + content[bounds[1]:]
        else:
            spans = []
            for key in keys:
                bounds = find_entry_bounds(content, entry_cmd, original[key][0]["word"])
                if bounds is None:
                    raise CorrectionError(f"{row['id']} entry disappeared while rendering")
                spans.append(bounds)
            for start, end in sorted(spans, reverse=True):
                content = content[:start] + content[end:]
            position = choose_insert_position(content, entry_cmd, row["after"]["word"])
            content = content[:position] + new_block + "\n\n" + content[position:]
        diffs.append({
            "id": row["id"], "status": "validated",
            "entry_diff": _unified("\n\n".join(old_blocks) + "\n", new_block + "\n", row["id"]),
        })
        positions = [index for index, key in enumerate(order) if key in keys]
        earliest = min(positions) if positions else len(order)
        order = [key for key in order if key not in keys]
        order.insert(min(earliest, len(order)), target)
        was_exported = keep_key in words
        words.difference_update(keys)
        if was_exported:
            words.add(target)
        for key in keys:
            next_aliases.pop(key, None)
        if target != kept_seed:
            next_aliases[target] = kept_seed

    next_tracker["words"] = sorted(words)
    next_tracker["entry_order"] = order
    rendered = _index(content, entry_cmd)
    if len(rendered) != len(original) - sum(len(row["retire"]) for row in corrections):
        raise CorrectionError("Post-render entry count changed unexpectedly")
    for row in corrections:
        target = _key(row["after"]["word"])
        if target not in rendered or rendered[target][0] != row["after"]:
            raise CorrectionError(f"{row['id']} rendered entry differs from after payload")
    for key, (_payload, block, _start, _end) in original.items():
        if key not in touched and (key not in rendered or rendered[key][1] != block):
            raise CorrectionError(f"Untouched entry block changed: {key}")
    live_keys = set(rendered)
    if (set(order) | words) - live_keys:
        raise CorrectionError("Tracker contains keys without a live entry")
    seeds = [_seed(key, next_aliases) for key in live_keys]
    if len(seeds) != len(set(seeds)):
        raise CorrectionError("Two live entries would share an Anki GUID seed")
    return content, next_tracker, next_aliases, diffs, retired


def _history_ids(path: Path, patch_id: str) -> set[str]:
    if not path.exists():
        return set()
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        metadata = record.get("metadata")
        if record.get("flow") == "vocab" and record.get("action") == "correct" and isinstance(metadata, dict) and metadata.get("patch_id") == patch_id:
            seen.add(str(metadata.get("correction_id")))
    return seen


def _append_history(
    path: Path, language: str, vocab_path: Path, patch_id: str,
    corrections: list[dict[str, Any]],
) -> None:
    logger = TranslationLogger(language_code=language, base_dir=path.parent)
    seen = _history_ids(path, patch_id)
    for row in corrections:
        if row["id"] in seen:
            continue
        after = row["after"]
        ok = logger.log_vocab_entry(
            action="correct", provider=None, word=after["word"],
            word_type=after["type"], definitions=after["definitions"],
            examples=[tuple(pair) for pair in after["examples"]],
            source_text=None, normalized_key=_key(after["word"]), latex_file=vocab_path,
            metadata={
                "patch_id": patch_id, "correction_id": row["id"],
                "before": row["before"], "retired": row["retire"],
                "keep_identity_of": row["keep_identity_of"],
                "reasons": row["reasons"], "sources": row["sources"],
            },
        )
        if not ok:
            raise CorrectionError(f"Could not append correction history for {row['id']}")


def _pending_transactions(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorrectionError(f"Cannot inspect mobile state: {path}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("transactions", {}), dict):
        raise CorrectionError(f"Invalid mobile transactions state: {path}")
    return bool(payload.get("transactions"))


def _bundle(
    data_dir: Path, patch_id: str, files: dict[str, Path],
    before: dict[str, str | None], after: dict[str, str | None], patch_hash: str,
    counts: dict[str, int], retired: list[dict[str, str]],
) -> Path:
    root = data_dir / "backups" / "corrections"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    bundle = root / f"{patch_id}-{stamp}"
    bundle.mkdir(parents=True, exist_ok=False)
    for name, path in files.items():
        if path.exists():
            atomic_copy_file(path, bundle / path.name)
    manifest = {
        "version": 1, "patch_id": patch_id, "patch_sha256": patch_hash,
        "before": before, "after": after,
        "files": {name: path.name for name, path in files.items()},
        "counts": counts, "retired_anki_identities": retired,
    }
    atomic_write_text(
        bundle / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        create_backup=False,
    )
    return bundle


def _replay_bundle(
    data_dir: Path, patch_id: str, patch_hash: str, hashes: dict[str, str | None],
) -> tuple[Path, dict[str, Any]] | None:
    root = data_dir / "backups" / "corrections"
    if not root.exists():
        return None
    for candidate in sorted(root.glob(f"{patch_id}-*/manifest.json"), reverse=True):
        try:
            manifest = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        planned = manifest.get("after")
        if (
            manifest.get("patch_sha256") == patch_hash
            and isinstance(planned, dict)
            and all(planned.get(name) == hashes.get(name) for name in (
                "vocab_sha256", "tracker_sha256", "identity_sha256"
            ))
        ):
            return candidate.parent, manifest
    return None


def run_corrections(
    *, language: str, data_dir: Path, patch_path: Path, apply: bool = False,
) -> dict[str, Any]:
    """Validate a reviewed patch and optionally commit it under one catalog lock."""
    if language not in {"fr", "de", "en"}:
        raise CorrectionError("language must be fr, de, or en")
    data_dir = Path(data_dir)
    patch_bytes = Path(patch_path).read_bytes()
    try:
        patch = json.loads(_text(patch_bytes, "Patch"))
    except json.JSONDecodeError as exc:
        raise CorrectionError("Patch is not valid JSON") from exc
    corrections = _validate_patch(patch, language)
    config = get_language_config(language)
    vocab_path = data_dir / config.vocab_filename
    tracker_path = data_dir / f"exported_words_{language}.json"
    identity_file = identity_path(tracker_path, language)
    history_path = data_dir / "history" / f"{language}_translations.jsonl"
    state_path = data_dir / f".mobile-{language}-state.json"
    files = {
        "vocab_sha256": vocab_path, "tracker_sha256": tracker_path,
        "identity_sha256": identity_file, "history_sha256": history_path,
    }
    with file_lock(vocab_path):
        if _pending_transactions(state_path):
            raise CorrectionError(f"Pending mobile transactions in {state_path}; stop and repair the service first")
        blobs = {name: _bytes(path) for name, path in files.items()}
        hashes = {name: _digest(blob) for name, blob in blobs.items()}
        if blobs["vocab_sha256"] is None or blobs["tracker_sha256"] is None:
            raise CorrectionError("Vocabulary and tracker files must both exist")
        base = patch["base"]
        if any(hashes[name] != base[name] for name in base):
            replay = _replay_bundle(data_dir, patch["patch_id"], _digest(patch_bytes), hashes)
            if not apply or replay is None:
                mismatched = [name for name in base if hashes[name] != base[name]]
                raise CorrectionError(f"Base SHA-256 mismatch: {', '.join(mismatched)}; no files changed")
            bundle, manifest = replay
            _append_history(history_path, language, vocab_path, patch["patch_id"], corrections)
            return {
                "patch_id": patch["patch_id"], "status": "already_applied",
                "corrections": [{"id": row["id"], "status": "already_applied"} for row in corrections],
                "bundle_path": str(bundle),
                "selected_words": [row["after"]["word"] for row in corrections],
                "counts": manifest["counts"],
                "retired_anki_identities": manifest["retired_anki_identities"],
            }
        content = _text(blobs["vocab_sha256"], "Vocabulary")
        tracker = _tracker_payload(blobs["tracker_sha256"])
        try:
            aliases = load_identity(identity_file)
        except (ValueError, json.JSONDecodeError) as exc:
            raise CorrectionError(f"Invalid Anki identity file: {identity_file}") from exc
        entry_cmd = config.vocab.entry_command or "\\entry"
        if not entry_cmd.startswith("\\"):
            entry_cmd = "\\" + entry_cmd
        rendered, next_tracker, next_aliases, rows, retired = _render(
            content, tracker, aliases, corrections, entry_cmd, config.anki.deck_namespace
        )
        tracker_text = json.dumps(next_tracker, ensure_ascii=False, indent=2)
        if blobs["tracker_sha256"].endswith(b"\n"):
            tracker_text += "\n"
        next_identity_text = identity_text(next_aliases)
        report: dict[str, Any] = {
            "patch_id": patch["patch_id"], "status": "validated", "corrections": rows,
            "counts": {
                "before": len(_index(content, entry_cmd)),
                "after": len(_index(rendered, entry_cmd)),
                "retired": sum(len(row["retire"]) for row in corrections),
            },
            "tracker_diff": _unified(_text(blobs["tracker_sha256"], "Tracker"), tracker_text, "tracker"),
            "identity_diff": _unified(
                _text(blobs["identity_sha256"], "Identity") if blobs["identity_sha256"] else "",
                next_identity_text, "identity",
            ),
            "retired_anki_identities": retired,
            "selected_words": [row["after"]["word"] for row in corrections],
            "bundle_path": None,
        }
        if not apply:
            return report
        after_hashes = {
            "vocab_sha256": _digest(rendered.encode("utf-8")),
            "tracker_sha256": _digest(tracker_text.encode("utf-8")),
            "identity_sha256": _digest(next_identity_text.encode("utf-8")),
        }
        bundle = _bundle(
            data_dir, patch["patch_id"], files, hashes, after_hashes,
            _digest(patch_bytes), report["counts"], retired,
        )
        report["bundle_path"] = str(bundle)
        save_identity(identity_file, next_aliases)
        atomic_write_text(vocab_path, rendered, create_backup=True)
        atomic_write_text(tracker_path, tracker_text, create_backup=False)
        _append_history(history_path, language, vocab_path, patch["patch_id"], corrections)
        # Re-read after all writes; the lock still excludes competing catalog writers.
        if _bytes(vocab_path) != rendered.encode("utf-8") or _bytes(tracker_path) != tracker_text.encode("utf-8"):
            raise CorrectionError(f"Post-write file mismatch; recovery bundle: {bundle}")
        if load_identity(identity_file) != next_aliases:
            raise CorrectionError(f"Post-write identity mismatch; recovery bundle: {bundle}")
        committed = _index(_text(_bytes(vocab_path), "Vocabulary"), entry_cmd)
        original = _index(_text(blobs["vocab_sha256"], "Vocabulary"), entry_cmd)
        touched = {
            _key(item["word"])
            for row in corrections for item in [row["before"], *row["retire"]]
        }
        if len(committed) != report["counts"]["after"]:
            raise CorrectionError(f"Post-write entry count mismatch; recovery bundle: {bundle}")
        for row in corrections:
            stored = committed.get(_key(row["after"]["word"]))
            if stored is None or stored[0] != row["after"]:
                raise CorrectionError(f"Post-write entry mismatch; recovery bundle: {bundle}")
        for key in set(original) - touched:
            if key not in committed or committed[key][1] != original[key][1]:
                raise CorrectionError(f"Post-write untouched block mismatch; recovery bundle: {bundle}")
        stored_tracker = _tracker_payload(_bytes(tracker_path))
        if (set(stored_tracker["words"]) | set(stored_tracker["entry_order"])) - set(committed):
            raise CorrectionError(f"Post-write stale tracker key; recovery bundle: {bundle}")
        seeds = [_seed(key, next_aliases) for key in committed]
        if len(seeds) != len(set(seeds)):
            raise CorrectionError(f"Post-write shared Anki seed; recovery bundle: {bundle}")
        report["status"] = "applied"
        for row in rows:
            row["status"] = "applied"
        return report
