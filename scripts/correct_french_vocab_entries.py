#!/usr/bin/env python3
"""Apply the reviewed 2026-09-03 French vocabulary corrections atomically."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Sequence

from vocab_builder.core.file_safety import atomic_write_text, file_lock
from vocab_builder.latex_repository import parse_all_entries


EXPECTED_ENTRY_COUNT = 614


@dataclass(frozen=True)
class ExactReplacement:
    old: str
    new: str
    count: int = 1


@dataclass(frozen=True)
class EntryCorrection:
    old_headword: str
    new_headword: str
    replacements: tuple[ExactReplacement, ...] = ()


CORRECTIONS = (
    EntryCorrection("agaçante", "Agaçante"),
    EntryCorrection(
        "Alambique (m.)",
        "Alambic (m.)",
        (
            ExactReplacement("l'alambique", "l'alambic"),
            ExactReplacement("un alambique", "un alambic", 2),
            ExactReplacement("du 19ème siècle", "du XIXe siècle"),
        ),
    ),
    EntryCorrection(
        "Anerie",
        "Ânerie",
        (
            ExactReplacement("une anerie", "une ânerie"),
            ExactReplacement("une pure anerie", "une pure ânerie"),
            ExactReplacement("d'aneries", "d'âneries"),
        ),
    ),
    EntryCorrection("Assomant", "Assommant"),
    EntryCorrection("Bras ballants:", "Bras ballants"),
    EntryCorrection(
        "Couronnement",
        "Couronnement",
        (
            ExactReplacement(
                "le couronnement de années d'entraînement",
                "le couronnement de plusieurs années d'entraînement",
            ),
        ),
    ),
    EntryCorrection("Depourvu", "Dépourvu"),
    EntryCorrection("Desobligeante", "Désobligeante"),
    EntryCorrection("Double tranchant", "À double tranchant"),
    EntryCorrection(
        "Enjoler",
        "Enjôler",
        (
            ExactReplacement("m'enjoler", "m'enjôler"),
            ExactReplacement("l'a enjolé", "l'a enjôlé"),
            ExactReplacement("laisser enjoler", "laisser enjôler"),
        ),
    ),
    EntryCorrection("Etroitesse", "Étroitesse"),
    EntryCorrection(
        "Foirer",
        "Foirer",
        (ExactReplacement("Je foir toujours", "Je foire toujours"),),
    ),
    EntryCorrection(
        "Fourrer",
        "Fourrer",
        (ExactReplacement("l'oeil", "l'œil", 2),),
    ),
    EntryCorrection("Gresillement", "Grésillement"),
    EntryCorrection(
        "Paillaison",
        "Paillage",
        (
            ExactReplacement("La paillaison", "Le paillage", 2),
            ExactReplacement("la paillaison", "le paillage"),
        ),
    ),
    EntryCorrection("Paipitant", "Palpitant"),
    EntryCorrection(
        "Poignard",
        "Poignard",
        (ExactReplacement("pignard", "poignard", 3),),
    ),
    EntryCorrection(
        "Prends soins de qqch",
        "Prendre soin de quelque chose",
        (
            ExactReplacement(
                """\\item Nous devons prendre soin de l'environnement pour les générations futures. \\\\ (We must take care of the environment for future generations.

Note: The original phrase "Prends soins de qqch" has been corrected to the infinitive form "Prendre soin de quelque chose" as per the given criteria. "Qqch" is an abbreviation for "quelque chose" (something), and it has been expanded in the correct form.)""",
                """\\item Nous devons prendre soin de l'environnement pour les générations futures. \\\\ (We must take care of the environment for future generations.)""",
            ),
        ),
    ),
    EntryCorrection("Proteiforme", "Protéiforme", (
        ExactReplacement("proteiforme", "protéiforme", 3),
    )),
    EntryCorrection("Redhibitoire", "Rédhibitoire"),
    EntryCorrection("Saignee", "Saignée"),
    EntryCorrection(
        "Scolopendre (m.)",
        "Scolopendre (f.)",
        (
            ExactReplacement("\\item Un scolopendre", "\\item Une scolopendre"),
            ExactReplacement("observé un scolopendre", "observé une scolopendre"),
        ),
    ),
    EntryCorrection(
        "Voleter",
        "Voleter",
        (
            ExactReplacement("Les papillons voletent", "Les papillons volettent"),
            ExactReplacement("les oiseaux voleteront", "les oiseaux voletteront"),
        ),
    ),
)


def _entry_index(content: str) -> dict[str, tuple[int, int]]:
    indexed: dict[str, tuple[int, int]] = {}
    duplicates: list[str] = []
    for groups, start, end in parse_all_entries(content, r"\entry"):
        headword = groups[0].strip()
        if headword in indexed:
            duplicates.append(headword)
        indexed[headword] = (start, end)
    if duplicates:
        raise ValueError(f"Duplicate exact headwords: {sorted(duplicates)}")
    return indexed


def corrected_vocabulary(content: str) -> str:
    original_entries = parse_all_entries(content, r"\entry")
    if len(original_entries) != EXPECTED_ENTRY_COUNT:
        raise ValueError(
            f"Expected {EXPECTED_ENTRY_COUNT} entries, found {len(original_entries)}"
        )

    indexed = _entry_index(content)
    edits: list[tuple[int, int, str]] = []
    for correction in CORRECTIONS:
        bounds = indexed.get(correction.old_headword)
        if bounds is None:
            raise ValueError(f"Missing target entry: {correction.old_headword}")
        start, end = bounds
        block = content[start:end]

        if correction.old_headword != correction.new_headword:
            old_marker = f"\\entry{{{correction.old_headword}}}"
            new_marker = f"\\entry{{{correction.new_headword}}}"
            if block.count(old_marker) != 1 or new_marker in block:
                raise ValueError(
                    f"Unsafe headword state for {correction.old_headword!r}"
                )
            block = block.replace(old_marker, new_marker, 1)

        for replacement in correction.replacements:
            actual = block.count(replacement.old)
            if actual != replacement.count:
                raise ValueError(
                    f"{correction.old_headword!r}: expected {replacement.count} "
                    f"occurrence(s) of {replacement.old!r}, found {actual}"
                )
            block = block.replace(replacement.old, replacement.new)
        edits.append((start, end, block))

    corrected = content
    for start, end, block in sorted(edits, reverse=True):
        corrected = corrected[:start] + block + corrected[end:]

    corrected_entries = parse_all_entries(corrected, r"\entry")
    if len(corrected_entries) != EXPECTED_ENTRY_COUNT:
        raise ValueError("The corrected vocabulary no longer parses completely")
    normalized = [groups[0].strip().lower() for groups, _, _ in corrected_entries]
    if len(normalized) != len(set(normalized)):
        raise ValueError("The corrected vocabulary contains a normalized duplicate")
    corrected_heads = {groups[0].strip() for groups, _, _ in corrected_entries}
    for correction in CORRECTIONS:
        if correction.new_headword not in corrected_heads:
            raise ValueError(f"Corrected headword is absent: {correction.new_headword}")
        if (
            correction.old_headword != correction.new_headword
            and correction.old_headword in corrected_heads
        ):
            raise ValueError(f"Old headword survived: {correction.old_headword}")
    return corrected


def _migrate_tracker_sequence(name: str, values: Sequence[str]) -> list[str]:
    migrated = list(values)
    for correction in CORRECTIONS:
        old = correction.old_headword.strip().lower()
        new = correction.new_headword.strip().lower()
        if old == new:
            continue
        old_count = migrated.count(old)
        new_count = migrated.count(new)
        if old_count != 1 or new_count != 0:
            raise ValueError(
                f"Unsafe tracker {name} state for {old!r} -> {new!r}: "
                f"old={old_count}, new={new_count}"
            )
        migrated[migrated.index(old)] = new
    return migrated


def corrected_tracker(content: str) -> str:
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("The Anki tracker must be a JSON object")
    words = data.get("words")
    entry_order = data.get("entry_order")
    if not isinstance(words, list) or not all(isinstance(value, str) for value in words):
        raise ValueError("The Anki tracker words field is invalid")
    if not isinstance(entry_order, list) or not all(
        isinstance(value, str) for value in entry_order
    ):
        raise ValueError("The Anki tracker entry_order field is invalid")

    migrated_words = _migrate_tracker_sequence("words", words)
    migrated_order = _migrate_tracker_sequence("entry_order", entry_order)
    if len(migrated_words) != len(words) or len(migrated_order) != len(entry_order):
        raise ValueError("Tracker migration changed a sequence length")
    data["words"] = sorted(migrated_words)
    data["entry_order"] = migrated_order
    return json.dumps(data, ensure_ascii=False, indent=2)


def run(vocabulary_path: Path, tracker_path: Path, *, apply: bool) -> dict[str, object]:
    lock_context = file_lock(vocabulary_path) if apply else _null_lock()
    with lock_context:
        vocabulary_before = vocabulary_path.read_text(encoding="utf-8")
        tracker_before = tracker_path.read_text(encoding="utf-8")
        vocabulary_after = corrected_vocabulary(vocabulary_before)
        tracker_after = corrected_tracker(tracker_before)

        result: dict[str, object] = {
            "mode": "apply" if apply else "dry-run",
            "entry_corrections": len(CORRECTIONS),
            "headword_corrections": sum(
                item.old_headword != item.new_headword for item in CORRECTIONS
            ),
            "entry_count": len(parse_all_entries(vocabulary_after, r"\entry")),
            "tracker_word_count": len(json.loads(tracker_after)["words"]),
            "tracker_order_count": len(json.loads(tracker_after)["entry_order"]),
            "vocabulary_changed": vocabulary_after != vocabulary_before,
            "tracker_changed": tracker_after != tracker_before,
        }
        if not apply:
            return result

        vocabulary_written = False
        tracker_written = False
        try:
            vocabulary_backup = atomic_write_text(
                vocabulary_path,
                vocabulary_after,
                create_backup=True,
            )
            vocabulary_written = True
            tracker_backup = atomic_write_text(
                tracker_path,
                tracker_after,
                create_backup=True,
            )
            tracker_written = True
            if vocabulary_path.read_text(encoding="utf-8") != vocabulary_after:
                raise OSError("Vocabulary post-write verification failed")
            if tracker_path.read_text(encoding="utf-8") != tracker_after:
                raise OSError("Tracker post-write verification failed")
        except Exception:
            if vocabulary_written:
                atomic_write_text(
                    vocabulary_path,
                    vocabulary_before,
                    create_backup=False,
                )
            if tracker_written:
                atomic_write_text(
                    tracker_path,
                    tracker_before,
                    create_backup=False,
                )
            raise

        result["vocabulary_backup"] = str(vocabulary_backup)
        result["tracker_backup"] = str(tracker_backup)
        return result


class _null_lock:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_args: object) -> None:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("vocabulary", type=Path)
    parser.add_argument("tracker", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = run(args.vocabulary, args.tracker, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
