#!/usr/bin/env python3
"""Merge two LaTeX vocabulary files of one language without duplicates.

The first file is kept as it stands, preamble included. Each entry of the
second file whose headword the merged text does not already hold is inserted
at its alphabetical position. Entries are read with the repository's balanced
parser, and identity and order come from the collection language's headword
key, so Polish keeps `Sad` and `Sąd` apart while French merges `Côte` and
`cote`. The result is written to a new file next to the first; neither input
is modified.

    python scripts/merge_tex_vocab.py --language pl first.tex second.tex
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path
from typing import Sequence

from vocab_builder.core.vocab_repository import choose_insert_position
from vocab_builder.languages import LanguageConfig, get_language_config
from vocab_builder.latex_repository import iter_entry_groups, unescape_latex


def merge_text(first: str, second: str, config: LanguageConfig) -> tuple[str, int, int]:
    """Return (merged text, entries added, entries skipped as already held)."""
    entry_cmd = config.vocab.entry_command
    key = config.headword_key
    held = {
        key(unescape_latex(groups[0].strip()))
        for groups, _, _ in iter_entry_groups(first, entry_cmd, num_groups=1)
    }
    merged = first
    added = skipped = 0
    for groups, start, end in iter_entry_groups(second, entry_cmd, num_groups=4):
        word = unescape_latex(groups[0].strip())
        if key(word) in held:
            skipped += 1
            continue
        position = choose_insert_position(merged, entry_cmd, word, key=key)
        merged = merged[:position] + second[start:end] + "\n\n" + merged[position:]
        held.add(key(word))
        added += 1
    return merged, added, skipped


def _unique_output_path(path: Path) -> Path:
    stem = f"{path.stem}_merged_{_dt.datetime.now():%Y%m%d_%H%M%S_%f}"
    candidate = path.with_stem(stem)
    counter = 1
    while candidate.exists():
        candidate = path.with_stem(f"{stem}_{counter}")
        counter += 1
    return candidate


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Merge two LaTeX vocabulary files of one language.")
    parser.add_argument("--language", required=True, help="Language code or alias, e.g. fr, de, en or pl.")
    parser.add_argument("file1", type=Path, help="The file kept as it stands, preamble included.")
    parser.add_argument("file2", type=Path, help="The file whose missing entries are added.")
    args = parser.parse_args(argv)
    try:
        config = get_language_config(args.language)
        merged, added, skipped = merge_text(
            args.file1.read_text(encoding="utf-8"),
            args.file2.read_text(encoding="utf-8"),
            config,
        )
        out = _unique_output_path(args.file1)
        with out.open("x", encoding="utf-8") as handle:
            handle.write(merged)
    except (OSError, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        sys.exit(1)
    print(f"[SUCCESS] Added {added}, skipped {skipped} already held; merged file written to: {out}")


if __name__ == "__main__":
    main()
