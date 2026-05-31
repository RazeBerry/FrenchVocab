#!/usr/bin/env python3
"""Bulk-load structured vocabulary entries into a language LaTeX file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from rich.console import Console

from vocab_builder.core.bulk_add import BulkAddReport, bulk_add_entries
from vocab_builder.core.vocab_repository import VocabRepository
from vocab_builder.languages import get_language_config
from vocab_builder.models import WordEntry
from vocab_builder.ui_helper import UIHelper


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bulk-load structured vocabulary JSON into a LaTeX vocab file."
    )
    parser.add_argument("--language", required=True, help="Language code or alias, e.g. fr or de.")
    parser.add_argument("--file", type=Path, help="JSON input file. Reads stdin when omitted.")
    parser.add_argument("--dry-run", action="store_true", help="Plan the batch without writing.")
    parser.add_argument(
        "--on-duplicate",
        choices=("skip", "merge", "error"),
        default="skip",
        help="How to handle entries whose normalized word already exists.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON.")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path("."),
        help="Directory containing the language vocabulary file.",
    )
    return parser.parse_args(argv)


def _load_payload(path: Path | None) -> tuple[Any | None, str | None]:
    try:
        raw = path.read_text(encoding="utf-8") if path else sys.stdin.read()
        return json.loads(raw), None
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON: {exc}"
    except OSError as exc:
        return None, f"Could not read JSON input: {exc}"


def _validate_payload(
    payload: Any,
    *,
    cli_language: str,
) -> tuple[list[WordEntry], list[str], list[str]]:
    entries: list[WordEntry] = []
    warnings: list[str] = []
    errors: list[str] = []

    if not isinstance(payload, dict):
        return [], [], ["payload must be a JSON object"]

    if "language" in payload:
        raw_language = payload["language"]
        if not isinstance(raw_language, str) or not raw_language.strip():
            errors.append("language must be a non-empty string when provided")
        else:
            try:
                payload_language = get_language_config(raw_language).code
            except ValueError as exc:
                errors.append(str(exc))
            else:
                if payload_language != cli_language:
                    errors.append(
                        f"language mismatch: payload has {payload_language}, CLI has {cli_language}"
                    )

    raw_entries = payload.get("entries")
    if raw_entries is None:
        return [], warnings, [*errors, "entries is required"]
    if not isinstance(raw_entries, list):
        return [], warnings, [*errors, "entries must be an array"]

    for index, raw_entry in enumerate(raw_entries):
        before = len(errors)
        if not isinstance(raw_entry, dict):
            errors.append(f"entries[{index}] must be an object")
            continue

        word = _read_required_str(raw_entry, "word", f"entries[{index}]", errors)
        word_type = _read_type(raw_entry, f"entries[{index}]", errors)
        definitions = _read_definitions(raw_entry, f"entries[{index}]", errors)
        examples = _read_examples(raw_entry, f"entries[{index}]", errors, warnings)

        if len(errors) == before:
            entries.append(
                WordEntry(
                    word=word,
                    type=word_type,
                    definitions=definitions,
                    examples=examples,
                )
            )

    return entries, warnings, errors


def _read_required_str(
    raw_entry: dict[str, Any],
    key: str,
    path: str,
    errors: list[str],
) -> str:
    value = raw_entry.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}.{key} must be a non-empty string")
        return ""
    return value.strip()


def _read_type(raw_entry: dict[str, Any], path: str, errors: list[str]) -> str:
    if "type" not in raw_entry:
        return "expression"
    value = raw_entry["type"]
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}.type must be a non-empty string when provided")
        return ""
    return value.strip()


def _read_definitions(
    raw_entry: dict[str, Any],
    path: str,
    errors: list[str],
) -> list[str]:
    raw_definitions = raw_entry.get("definitions")
    if not isinstance(raw_definitions, list):
        errors.append(f"{path}.definitions must be a non-empty string array")
        return []

    definitions: list[str] = []
    for index, definition in enumerate(raw_definitions):
        if not isinstance(definition, str) or not definition.strip():
            errors.append(f"{path}.definitions[{index}] must be a non-empty string")
        else:
            definitions.append(definition.strip())
    if not definitions:
        errors.append(f"{path}.definitions must contain at least one definition")
    return definitions


def _read_examples(
    raw_entry: dict[str, Any],
    path: str,
    errors: list[str],
    warnings: list[str],
) -> list[tuple[str, str]]:
    raw_examples = raw_entry.get("examples", [])
    if not isinstance(raw_examples, list):
        errors.append(f"{path}.examples must be an array")
        return []

    examples: list[tuple[str, str]] = []
    for index, raw_example in enumerate(raw_examples):
        example_path = f"{path}.examples[{index}]"
        if not isinstance(raw_example, list) or len(raw_example) != 2:
            errors.append(f"{example_path} must be a two-element string array")
            continue
        source, english = raw_example
        if not isinstance(source, str) or not source.strip():
            errors.append(f"{example_path}[0] must be a non-empty string")
            continue
        if not isinstance(english, str):
            errors.append(f"{example_path}[1] must be a string")
            continue
        if not english.strip():
            warnings.append(f"{example_path}[1] is empty")
        examples.append((source.strip(), english.strip()))
    return examples


def _build_repo(language_code: str, base_dir: Path) -> VocabRepository:
    config = get_language_config(language_code)
    return VocabRepository(
        latex_file=base_dir / config.vocab_filename,
        entry_command=config.vocab.entry_command,
        language_config=config,
        ui=UIHelper(Console()),
        vocab_template=config.vocab,
    )


def _print_human_report(report: BulkAddReport) -> None:
    prefix = "[SUCCESS]" if report.ok else "[ERROR]"
    mode = "dry-run " if report.dry_run else ""
    print(
        f"{prefix} {mode}bulk add: "
        f"added={report.count('added')} "
        f"merged={report.count('merged')} "
        f"skipped={report.count('skipped')} "
        f"failed={report.count('failed')}"
    )
    for outcome in report.outcomes:
        detail = f" - {outcome.detail}" if outcome.detail else ""
        print(f"{outcome.status}: {outcome.word}{detail}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        config = get_language_config(args.language)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    payload, load_error = _load_payload(args.file)
    if load_error:
        print(f"[ERROR] {load_error}", file=sys.stderr)
        return 2

    entries, warnings, errors = _validate_payload(payload, cli_language=config.code)
    for warning in warnings:
        print(f"[WARNING] {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"[ERROR] {error}", file=sys.stderr)
        return 2

    repo = _build_repo(config.code, args.base_dir)
    if not repo.latex_file.exists():
        print(f"[ERROR] Target file does not exist: {repo.latex_file}", file=sys.stderr)
        return 2

    report = bulk_add_entries(
        repo,
        entries,
        on_duplicate=args.on_duplicate,
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_human_report(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
