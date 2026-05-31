"""Batch vocabulary entry loading contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal, Sequence

from vocab_builder.models import WordEntry

if TYPE_CHECKING:
    from vocab_builder.core.vocab_repository import VocabRepository


DuplicatePolicy = Literal["skip", "merge", "error"]
Status = Literal["added", "skipped", "merged", "failed"]


@dataclass(frozen=True)
class EntryOutcome:
    """Result for one requested bulk entry."""

    word: str
    status: Status
    detail: str = ""


@dataclass(frozen=True)
class BulkAddReport:
    """Summary of a bulk-add attempt."""

    outcomes: list[EntryOutcome]
    dry_run: bool

    def count(self, status: Status) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == status)

    @property
    def ok(self) -> bool:
        return self.count("failed") == 0

    @property
    def changed(self) -> bool:
        return any(outcome.status in {"added", "merged"} for outcome in self.outcomes)

    def to_dict(self) -> dict[str, object]:
        return {
            "dry_run": self.dry_run,
            "ok": self.ok,
            "counts": {
                "added": self.count("added"),
                "skipped": self.count("skipped"),
                "merged": self.count("merged"),
                "failed": self.count("failed"),
            },
            "outcomes": [asdict(outcome) for outcome in self.outcomes],
        }


def bulk_add_entries(
    repo: VocabRepository,
    entries: Sequence[WordEntry],
    *,
    on_duplicate: DuplicatePolicy = "skip",
    dry_run: bool = False,
) -> BulkAddReport:
    """Apply a batch through the repository's atomic bulk writer."""
    return repo.bulk_add_entries(entries, on_duplicate=on_duplicate, dry_run=dry_run)
