"""Production-debt scheduling for composition practice."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from vocab_builder.compat import get_env
from vocab_builder.models import normalize_word_key

VERDICT_CORRECT = "correct"
VERDICT_INCORRECT = "incorrect"
VERDICT_NOT_USED = "not_used"
VALID_VERDICTS = frozenset({VERDICT_CORRECT, VERDICT_INCORRECT, VERDICT_NOT_USED})


@dataclass(frozen=True)
class ScheduledWord:
    """Vocabulary entry selected for composition practice."""

    key: str
    word: str
    word_type: str
    first_definition: str
    entry_index: int
    examples: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ProductionState:
    """Derived production state for one vocabulary entry."""

    entry: ScheduledWord
    latest_verdict: Optional[str]
    latest_attempt_index: Optional[int]
    latest_success_index: Optional[int]
    latest_failure_index: Optional[int]
    has_ever_success: bool

    @property
    def attempted(self) -> bool:
        return self.latest_attempt_index is not None

    @property
    def produced(self) -> bool:
        return self.latest_verdict == VERDICT_CORRECT

    @property
    def in_debt_count(self) -> bool:
        return not self.has_ever_success


def composition_feature_enabled(default: bool = True) -> bool:
    value = get_env("VOCABBUILDER_COMPOSITION")
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def composition_words_per_attempt(default: int = 3) -> int:
    return _positive_env_int("VOCABBUILDER_COMPOSITION_WORDS", default)


def composition_set_size(default: int = 3) -> int:
    return _positive_env_int("VOCABBUILDER_COMPOSITION_SET_SIZE", default)


def _positive_env_int(name: str, default: int) -> int:
    value = get_env(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 1 else default


class CompositionScheduler:
    """Derive production state and debt ordering from vocab + JSONL history."""

    def __init__(self, vocab_repo: Any, history_paths: Sequence[Path]) -> None:
        self.vocab_repo = vocab_repo
        self.history_paths = tuple(Path(path) for path in history_paths)
        self._debt_count_cache: tuple[tuple[Any, ...], int] | None = None

    def invalidate(self) -> None:
        self._debt_count_cache = None

    def debt_count(self) -> int:
        signature = self._signature()
        if self._debt_count_cache and self._debt_count_cache[0] == signature:
            return self._debt_count_cache[1]
        count = sum(1 for state in self.production_states() if state.in_debt_count)
        self._debt_count_cache = (signature, count)
        return count

    def ordered_states(self) -> list[ProductionState]:
        states = self.production_states()
        never_attempted = [state for state in states if not state.attempted]
        failed = [
            state
            for state in states
            if state.attempted and state.latest_verdict != VERDICT_CORRECT
        ]
        produced = [state for state in states if state.latest_verdict == VERDICT_CORRECT]

        never_attempted.sort(key=lambda state: state.entry.entry_index)
        failed.sort(
            key=lambda state: (
                -(state.latest_failure_index if state.latest_failure_index is not None else -1),
                state.entry.entry_index,
            )
        )
        produced.sort(
            key=lambda state: (
                state.latest_success_index if state.latest_success_index is not None else 10**12,
                state.entry.entry_index,
            )
        )
        return never_attempted + failed + produced

    def sample_words(
        self,
        count: int,
        *,
        exclude_keys: Optional[Iterable[str]] = None,
    ) -> list[ScheduledWord]:
        excluded = set(exclude_keys or ())
        words: list[ScheduledWord] = []
        for state in self.ordered_states():
            if state.entry.key in excluded:
                continue
            words.append(state.entry)
            if len(words) >= count:
                break
        return words

    def sample_reverse_word(
        self,
        *,
        exclude_keys: Optional[Iterable[str]] = None,
    ) -> Optional[ScheduledWord]:
        excluded = set(exclude_keys or ())
        for state in self.ordered_states():
            if state.entry.key in excluded:
                continue
            if state.entry.examples:
                return state.entry
        return None

    def production_states(self) -> list[ProductionState]:
        entries = _entries_from_repo(self.vocab_repo)
        history = _read_history_records(self.history_paths)
        derived = _derive_history_by_word_key(_history_events(history))

        states: list[ProductionState] = []
        for entry in entries:
            normalized = normalize_word_key(entry.word)
            word_history = derived.get(normalized, _DerivedWordHistory())

            states.append(
                ProductionState(
                    entry=entry,
                    latest_verdict=word_history.latest_verdict,
                    latest_attempt_index=word_history.latest_attempt_index,
                    latest_success_index=word_history.latest_success_index,
                    latest_failure_index=word_history.latest_failure_index,
                    has_ever_success=word_history.has_ever_success,
                )
            )
        return states

    def _signature(self) -> tuple[Any, ...]:
        parts: list[Any] = []
        latex_file = getattr(self.vocab_repo, "latex_file", None)
        if latex_file is not None:
            parts.append(("vocab", _file_signature(Path(latex_file))))
        else:
            entries = getattr(self.vocab_repo, "word_entries", {})
            parts.append(("vocab-memory", len(entries), tuple(entries.keys())))
        for path in self.history_paths:
            parts.append(("history", str(path), _file_signature(path)))
        return tuple(parts)


@dataclass(frozen=True)
class _HistoryEvent:
    index: int
    ts: str
    verdicts_by_key: Mapping[str, str]


@dataclass
class _DerivedWordHistory:
    latest_verdict: Optional[str] = None
    latest_attempt_index: Optional[int] = None
    latest_success_index: Optional[int] = None
    latest_failure_index: Optional[int] = None
    has_ever_success: bool = False


def _derive_history_by_word_key(events: Sequence[_HistoryEvent]) -> dict[str, _DerivedWordHistory]:
    derived: dict[str, _DerivedWordHistory] = {}
    for event in events:
        for word_key, verdict in event.verdicts_by_key.items():
            state = derived.setdefault(word_key, _DerivedWordHistory())
            state.latest_verdict = verdict
            state.latest_attempt_index = event.index
            if verdict == VERDICT_CORRECT:
                state.has_ever_success = True
                state.latest_success_index = event.index
            else:
                state.latest_failure_index = event.index
    return derived


def _file_signature(path: Path) -> tuple[float, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime, stat.st_size)


def _entries_from_repo(vocab_repo: Any) -> list[ScheduledWord]:
    ensure = getattr(vocab_repo, "ensure_entries_loaded", None)
    if callable(ensure):
        ensure()

    raw_entries = getattr(vocab_repo, "word_entries", {}) or {}
    entries: list[ScheduledWord] = []
    for index, (key, entry) in enumerate(raw_entries.items()):
        word = _entry_value(entry, "word", str(key)).strip()
        if not word:
            continue
        entries.append(
            ScheduledWord(
                key=str(key),
                word=word,
                word_type=_entry_value(entry, "type", ""),
                first_definition=_first_definition(entry),
                entry_index=index,
                examples=_examples_from_entry(entry),
            )
        )
    return entries


def _entry_value(entry: Any, name: str, default: str) -> str:
    if isinstance(entry, Mapping):
        value = entry.get(name, default)
    else:
        value = getattr(entry, name, default)
    return str(value or "")


def _first_definition(entry: Any) -> str:
    definitions = None
    if isinstance(entry, Mapping):
        definitions = entry.get("definitions_list")
        if not definitions:
            definitions = entry.get("definitions")
    else:
        definitions = getattr(entry, "definitions", None)

    if isinstance(definitions, str):
        return definitions.split(";")[0].strip()
    if isinstance(definitions, Sequence):
        for definition in definitions:
            text = str(definition).strip()
            if text:
                return text
    return ""


def _examples_from_entry(entry: Any) -> tuple[tuple[str, str], ...]:
    if isinstance(entry, Mapping):
        raw_examples: Any = entry.get("examples_list")
        if not raw_examples:
            raw_examples = entry.get("examples")
    else:
        raw_examples = getattr(entry, "examples", None)

    if isinstance(raw_examples, str):
        iterable: Iterable[Any] = _parse_examples_text(raw_examples)
    elif isinstance(raw_examples, Iterable):
        iterable = raw_examples
    else:
        iterable = ()

    pairs: list[tuple[str, str]] = []
    for item in iterable:
        if not isinstance(item, Sequence) or isinstance(item, (str, bytes)) or len(item) < 2:
            continue
        target = str(item[0] or "").strip()
        english = str(item[1] or "").strip()
        if target and english:
            pairs.append((target, english))
    return tuple(pairs)


def _parse_examples_text(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for example in text.split(";"):
        candidate = example.strip()
        if not candidate or not candidate.endswith(")") or "(" not in candidate:
            continue
        target, english = candidate.rsplit("(", 1)
        target = target.strip()
        english = english[:-1].strip()
        if target and english:
            pairs.append((target, english))
    return pairs


def _read_history_records(paths: Sequence[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(record, dict):
                        records.append(record)
        except OSError:
            continue
    return records


def _history_events(records: Sequence[Mapping[str, Any]]) -> list[_HistoryEvent]:
    sortable: list[tuple[str, int, Mapping[str, Any]]] = []
    for index, record in enumerate(records):
        ts = str(record.get("ts") or record.get("timestamp") or "")
        sortable.append((ts, index, record))
    sortable.sort(key=lambda item: (item[0], item[1]))

    events: list[_HistoryEvent] = []
    for index, (_ts, _raw_index, record) in enumerate(sortable):
        raw_verdicts = record.get("word_verdicts")
        if not isinstance(raw_verdicts, Mapping):
            continue
        verdicts_by_key: dict[str, str] = {}
        for word, verdict in raw_verdicts.items():
            normalized_verdict = _normalize_verdict(verdict)
            if normalized_verdict is None:
                continue
            key = normalize_word_key(str(word))
            if key:
                verdicts_by_key[key] = normalized_verdict
        if verdicts_by_key:
            events.append(
                _HistoryEvent(
                    index=index,
                    ts=str(record.get("ts") or record.get("timestamp") or ""),
                    verdicts_by_key=verdicts_by_key,
                )
            )
    return events


def _normalize_verdict(value: Any) -> Optional[str]:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in VALID_VERDICTS:
        return normalized
    return None


__all__ = [
    "CompositionScheduler",
    "ProductionState",
    "ScheduledWord",
    "VALID_VERDICTS",
    "VERDICT_CORRECT",
    "VERDICT_INCORRECT",
    "VERDICT_NOT_USED",
    "composition_feature_enabled",
    "composition_set_size",
    "composition_words_per_attempt",
]
