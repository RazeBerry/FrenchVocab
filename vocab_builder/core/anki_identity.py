"""Private, per-language Anki GUID seed aliases beside the export tracker."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from .file_safety import atomic_write_text, file_lock


def identity_path(tracker_path: Path, language: str) -> Path:
    return Path(tracker_path).parent / f"anki_identity_{language}.json"


def load_identity(path: Path) -> dict[str, str]:
    """Read the sole persisted alias mapping; absence means identity seeds."""
    with file_lock(path):
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or set(payload) != {"version", "guid_headword_aliases"}
            or type(payload["version"]) is not int
            or payload["version"] != 1
        ):
            raise ValueError(f"Invalid Anki identity file: {path}")
        aliases = payload.get("guid_headword_aliases")
        _validate_aliases(aliases, path)
        return dict(aliases)


def _validate_aliases(aliases: object, path: Path | None = None) -> None:
    if not isinstance(aliases, dict) or any(
            not isinstance(key, str) or not isinstance(seed, str)
            or not key or not seed or key != key.strip().lower()
            or seed != seed.strip().lower()
            for key, seed in aliases.items()
    ):
        raise ValueError(f"Invalid Anki identity aliases: {path or 'new mapping'}")


def identity_text(aliases: dict[str, str]) -> str:
    _validate_aliases(aliases)
    return json.dumps(
        {"version": 1, "guid_headword_aliases": aliases},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def save_identity(path: Path, aliases: dict[str, str]) -> None:
    with file_lock(path):
        atomic_write_text(path, identity_text(aliases), create_backup=False)


def reserve_seeds(aliases: Mapping[str, str], live_keys: Iterable[str]) -> dict[str, str]:
    """Return aliases in which no unaliased live key uses a seed an alias holds.

    An alias reserves its seed: the note a corrected headword kept still owns
    that GUID in Anki. A live key whose own spelling is such a seed (the old
    spelling, added again as a new word) gets the fresh seed ``<key>#<n>``.
    The smallest free n makes the choice a function of the catalog, so a
    correction's dry run and its apply, or two exports, choose alike.
    """
    seeded = dict(aliases)
    live = sorted(set(live_keys))
    for key in live:
        if key in seeded or key not in seeded.values():
            continue
        in_use = set(seeded.values()) | {seeded.get(other, other) for other in live}
        n = 2
        while f"{key}#{n}" in in_use:
            n += 1
        seeded[key] = f"{key}#{n}"
    return seeded


def load_reserved_identity(path: Path, live_keys: Iterable[str]) -> dict[str, str]:
    """Load the aliases, persisting any seed :func:`reserve_seeds` adds."""
    with file_lock(path):
        aliases = load_identity(path)
        seeded = reserve_seeds(aliases, live_keys)
        if seeded != aliases:
            save_identity(path, seeded)
        return seeded
