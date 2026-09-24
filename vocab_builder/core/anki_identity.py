"""Private, per-language Anki GUID seed aliases beside the export tracker."""

from __future__ import annotations

import json
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
