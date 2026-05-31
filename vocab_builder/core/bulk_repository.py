"""Atomic repository implementation for bulk vocabulary loading."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence

from vocab_builder.core.bulk_add import BulkAddReport, DuplicatePolicy, EntryOutcome
from vocab_builder.core.file_safety import atomic_write_text, file_lock
from vocab_builder.latex_repository import find_entry_bounds
from vocab_builder.models import WordEntry

if TYPE_CHECKING:
    from vocab_builder.core.vocab_repository import VocabRepository


def bulk_add_entries_for_repo(
    repo: VocabRepository,
    entries: Sequence[WordEntry],
    *,
    on_duplicate: DuplicatePolicy = "skip",
    dry_run: bool = False,
) -> BulkAddReport:
    """Plan the full batch in memory, then commit with one atomic write."""
    if on_duplicate not in {"skip", "merge", "error"}:
        raise ValueError(f"Unsupported duplicate policy: {on_duplicate}")
    if not entries:
        return BulkAddReport([], dry_run=dry_run)

    outcomes: list[EntryOutcome] = []
    with file_lock(repo.latex_file):
        try:
            working_content = repo.latex_file.read_text(encoding="utf-8")
        except OSError as exc:
            return BulkAddReport(
                [EntryOutcome(entry.word, "failed", str(exc)) for entry in entries],
                dry_run=dry_run,
            )

        repo.load_existing_entries()
        word_entries = {
            key: _clone_entry_record(value)
            for key, value in repo.word_entries.items()
        }
        normalized_entries = dict(repo.normalized_entries)
        entry_cmd = repo._get_entry_command()

        for entry in entries:
            working_content = _plan_entry(
                repo,
                entry,
                on_duplicate,
                working_content,
                entry_cmd,
                word_entries,
                normalized_entries,
                outcomes,
            )

        report = BulkAddReport(outcomes, dry_run=dry_run)
        if dry_run:
            return report
        if not report.ok:
            return _blocked_report(outcomes, dry_run=dry_run)
        if not report.changed:
            return report

        try:
            atomic_write_text(repo.latex_file, working_content, create_backup=True)
        except OSError as exc:
            return _write_failed_report(outcomes, dry_run=dry_run, error=exc)

        repo._entry_count_snapshot = None
        repo.load_existing_entries()
        return report


def _plan_entry(
    repo: VocabRepository,
    entry: WordEntry,
    on_duplicate: DuplicatePolicy,
    working_content: str,
    entry_cmd: str,
    word_entries: dict[str, dict[str, Any]],
    normalized_entries: dict[str, str],
    outcomes: list[EntryOutcome],
) -> str:
    word = entry.word.strip()
    existing_key = normalized_entries.get(repo.normalize_word(word))
    if existing_key is not None:
        return _plan_duplicate(
            repo,
            entry,
            on_duplicate,
            existing_key,
            working_content,
            entry_cmd,
            word_entries,
            outcomes,
        )

    latex_block = repo.format_latex_entry(
        word,
        entry.type,
        list(entry.definitions),
        list(entry.examples),
        entry_command=repo.entry_command,
    )
    insert_position = repo._choose_insert_position(working_content, entry_cmd, word)
    word_key = word.lower()
    normalized_entries[repo.normalize_word(word_key)] = word_key
    word_entries[word_key] = _new_entry_record(entry)
    outcomes.append(EntryOutcome(word, "added"))
    return (
        working_content[:insert_position]
        + latex_block
        + "\n\n"
        + working_content[insert_position:]
    )


def _plan_duplicate(
    repo: VocabRepository,
    entry: WordEntry,
    on_duplicate: DuplicatePolicy,
    existing_key: str,
    working_content: str,
    entry_cmd: str,
    word_entries: dict[str, dict[str, Any]],
    outcomes: list[EntryOutcome],
) -> str:
    existing = word_entries.get(existing_key)
    existing_word = existing.get("word", existing_key) if existing else existing_key
    if on_duplicate == "skip":
        outcomes.append(EntryOutcome(entry.word, "skipped", f"duplicate of {existing_word}"))
        return working_content
    if on_duplicate == "error":
        outcomes.append(EntryOutcome(entry.word, "failed", f"duplicate of {existing_word}"))
        return working_content
    if existing is None:
        outcomes.append(EntryOutcome(entry.word, "failed", f"missing duplicate record {existing_key}"))
        return working_content

    bounds = find_entry_bounds(working_content, entry_cmd, existing_word, prefer_last=False)
    if bounds is None:
        outcomes.append(EntryOutcome(entry.word, "failed", f"entry block not found for {existing_word}"))
        return working_content

    merged_defs = repo._dedup_merge_definitions(
        repo._coerce_existing_definitions(existing),
        list(entry.definitions),
    )
    merged_exs = repo._dedup_merge_examples(
        repo._coerce_existing_examples(existing),
        list(entry.examples),
    )
    final_type = existing.get("type") or entry.type
    latex_block = repo.format_latex_entry(
        existing_word,
        final_type,
        merged_defs,
        merged_exs,
        entry_command=repo.entry_command,
    )
    start, end = bounds
    word_entries[existing_key] = _merged_entry_record(
        existing,
        final_type,
        merged_defs,
        merged_exs,
    )
    outcomes.append(EntryOutcome(entry.word, "merged", f"merged into {existing_word}"))
    return working_content[:start] + latex_block + working_content[end:]


def _clone_entry_record(entry: dict[str, Any]) -> dict[str, Any]:
    cloned = dict(entry)
    cloned["definitions_list"] = list(entry.get("definitions_list") or [])
    cloned["examples_list"] = list(entry.get("examples_list") or [])
    return cloned


def _new_entry_record(entry: WordEntry) -> dict[str, Any]:
    display_word = entry.word if entry.type.lower() == "sentence" else entry.word.capitalize()
    return {
        "word": display_word,
        "type": entry.type,
        "definitions": "; ".join(entry.definitions),
        "examples": "; ".join([f"{source} ({english})" for source, english in entry.examples]),
        "definitions_list": list(entry.definitions),
        "examples_list": list(entry.examples),
    }


def _merged_entry_record(
    existing: dict[str, Any],
    final_type: str,
    merged_defs: list[str],
    merged_exs: list[tuple[str, str]],
) -> dict[str, Any]:
    updated = dict(existing)
    updated["type"] = final_type
    updated["definitions_list"] = merged_defs
    updated["examples_list"] = merged_exs
    updated["definitions"] = "; ".join(merged_defs)
    updated["examples"] = "; ".join([f"{source} ({english})" for source, english in merged_exs])
    return updated


def _blocked_report(
    outcomes: list[EntryOutcome],
    *,
    dry_run: bool,
) -> BulkAddReport:
    return BulkAddReport(
        [
            EntryOutcome(
                outcome.word,
                "failed",
                "batch not written because one or more entries failed",
            )
            if outcome.status in {"added", "merged"}
            else outcome
            for outcome in outcomes
        ],
        dry_run=dry_run,
    )


def _write_failed_report(
    outcomes: list[EntryOutcome],
    *,
    dry_run: bool,
    error: OSError,
) -> BulkAddReport:
    return BulkAddReport(
        [
            EntryOutcome(outcome.word, "failed", f"write failed: {error}")
            if outcome.status in {"added", "merged"}
            else outcome
            for outcome in outcomes
        ],
        dry_run=dry_run,
    )
