#!/usr/bin/env python3
"""Validate or apply one reviewed vocabulary correction patch."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from vocab_builder.core.vocab_corrections import CorrectionError, run_corrections
from vocab_builder.languages import get_language_config


def _disk_preflight(data_dir: Path, language: str) -> None:
    """Report measured free space and a conservative logical-copy estimate."""
    config = get_language_config(language)
    sizes = {
        "vocab": (data_dir / config.vocab_filename),
        "tracker": (data_dir / f"exported_words_{language}.json"),
        "identity": (data_dir / f"anki_identity_{language}.json"),
        "history": (data_dir / "history" / f"{language}_translations.jsonl"),
    }
    lengths = {name: path.stat().st_size if path.exists() else 0 for name, path in sizes.items()}
    estimate = (
        4 * lengths["vocab"] + 2 * lengths["tracker"]
        + 2 * lengths["identity"] + lengths["history"] + 1024 * 1024
    )
    free = shutil.disk_usage(data_dir).free
    unit = 1024 ** 3
    print(
        f"Data volume free: {free / unit:.3f} GiB measured; "
        f"peak additional allocation: up to {estimate / unit:.3f} GiB estimated "
        "from logical sizes and simultaneous copies (filesystem sharing may change physical use).",
        file=sys.stderr,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", required=True, choices=("fr", "de", "en"))
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--patch", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if args.apply:
            _disk_preflight(args.data_dir, args.language)
        report = run_corrections(
            language=args.language, data_dir=args.data_dir,
            patch_path=args.patch, apply=args.apply,
        )
    except (CorrectionError, OSError) as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            print(f"Correction refused: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Patch {report['patch_id']}: {report['status']}")
        for row in report["corrections"]:
            print(f"\n{row['id']}: {row['status']}")
            if row.get("entry_diff"):
                print(row["entry_diff"], end="")
        for name in ("tracker_diff", "identity_diff"):
            if report.get(name):
                print(f"\n{name}:\n{report[name]}", end="")
        if report.get("bundle_path"):
            print(f"\nRecovery bundle: {report['bundle_path']}")
        if report.get("retired_anki_identities"):
            print("Retired Anki identities to delete by hand:")
            for item in report["retired_anki_identities"]:
                print(f"  {item['headword']}: {item['guid']}")
        print("Selected words to export: " + ", ".join(report["selected_words"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
