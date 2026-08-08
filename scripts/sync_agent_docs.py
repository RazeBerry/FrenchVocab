#!/usr/bin/env python3
"""Keep the tool-specific repository guides on one canonical knowledge base."""

from __future__ import annotations

import argparse
import difflib
import os
from pathlib import Path
import sys
import tempfile


CANONICAL_NAME = "AGENTS.md"
MIRROR_NAME = "CLAUDE.md"
DEFAULT_ROOT = Path(__file__).resolve().parents[1]


def _paths(root: Path) -> tuple[Path, Path]:
    return root / CANONICAL_NAME, root / MIRROR_NAME


def agent_docs_are_synced(root: Path) -> bool:
    """Return whether both guides exist and contain exactly the same bytes."""
    canonical, mirror = _paths(root)
    return (
        canonical.is_file()
        and mirror.is_file()
        and canonical.read_bytes() == mirror.read_bytes()
    )


def sync_agent_docs(root: Path) -> bool:
    """Atomically replace the mirror from the canonical guide when needed."""
    canonical, mirror = _paths(root)
    source = canonical.read_bytes()
    if mirror.is_file() and mirror.read_bytes() == source:
        return False

    descriptor, temporary_name = tempfile.mkstemp(
        dir=root,
        prefix=f".{MIRROR_NAME}.",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(source)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(canonical.stat().st_mode & 0o777)
        os.replace(temporary, mirror)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def _difference(root: Path) -> str:
    canonical, mirror = _paths(root)
    canonical_text = canonical.read_text(encoding="utf-8").splitlines(keepends=True)
    mirror_text = (
        mirror.read_text(encoding="utf-8").splitlines(keepends=True)
        if mirror.is_file()
        else []
    )
    return "".join(
        difflib.unified_diff(
            mirror_text,
            canonical_text,
            fromfile=MIRROR_NAME,
            tofile=CANONICAL_NAME,
        )
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Synchronize {MIRROR_NAME} from canonical {CANONICAL_NAME}."
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--check",
        action="store_true",
        help="fail when the guides differ (default)",
    )
    action.add_argument(
        "--write",
        action="store_true",
        help=f"atomically rewrite {MIRROR_NAME} from {CANONICAL_NAME}",
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = args.root.resolve()

    if args.write:
        changed = sync_agent_docs(root)
        status = "updated" if changed else "already aligned"
        print(f"{MIRROR_NAME} {status} with canonical {CANONICAL_NAME}.")
        return 0

    if agent_docs_are_synced(root):
        print(f"{CANONICAL_NAME} and {MIRROR_NAME} are byte-for-byte aligned.")
        return 0

    print(
        f"error: {MIRROR_NAME} is not the byte-for-byte mirror of {CANONICAL_NAME}.\n"
        f"Run: python scripts/sync_agent_docs.py --write",
        file=sys.stderr,
    )
    print(_difference(root), file=sys.stderr, end="")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
