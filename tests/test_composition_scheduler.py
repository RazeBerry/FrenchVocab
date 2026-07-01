import json
from pathlib import Path

from vocab_builder.core.composition_scheduler import (
    CompositionScheduler,
    composition_feature_enabled,
    composition_set_size,
    composition_words_per_attempt,
)


class _Repo:
    def __init__(self, tmp_path: Path, words):
        self.latex_file = tmp_path / "vocab.tex"
        self.latex_file.write_text("% vocab\n", encoding="utf-8")
        self.word_entries = {
            word.lower(): {
                "word": word,
                "type": word_type,
                "definitions_list": [definition],
            }
            for word, word_type, definition in words
        }

    def ensure_entries_loaded(self):
        return None


def _write_history(path: Path, records):
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def test_scheduler_counts_unproduced_words_and_orders_debt(tmp_path):
    repo = _Repo(
        tmp_path,
        [
            ("alpha", "noun", "first"),
            ("beta", "verb", "second"),
            ("gamma", "adverb", "third"),
            ("delta", "noun", "fourth"),
        ],
    )
    history = tmp_path / "fr_compositions.jsonl"
    _write_history(
        history,
        [
            {"ts": "2026-06-12T10:00:00Z", "word_verdicts": {"beta": "incorrect"}},
            {"ts": "2026-06-12T11:00:00Z", "word_verdicts": {"gamma": "not_used"}},
            {"ts": "2026-06-12T12:00:00Z", "word_verdicts": {"delta": "correct"}},
            {"ts": "2026-06-12T13:00:00Z", "word_verdicts": {"beta": "incorrect"}},
        ],
    )

    scheduler = CompositionScheduler(repo, [history])

    assert scheduler.debt_count() == 3
    assert [state.entry.word for state in scheduler.ordered_states()] == [
        "alpha",
        "beta",
        "gamma",
        "delta",
    ]
    assert [word.word for word in scheduler.sample_words(2)] == ["alpha", "beta"]


def test_scheduler_orders_produced_words_by_stalest_success(tmp_path):
    repo = _Repo(
        tmp_path,
        [
            ("alpha", "noun", "first"),
            ("beta", "verb", "second"),
        ],
    )
    history = tmp_path / "fr_compositions.jsonl"
    _write_history(
        history,
        [
            {"ts": "2026-06-12T10:00:00Z", "word_verdicts": {"beta": "correct"}},
            {"ts": "2026-06-12T11:00:00Z", "word_verdicts": {"alpha": "correct"}},
        ],
    )

    scheduler = CompositionScheduler(repo, [history])

    assert scheduler.debt_count() == 0
    assert [state.entry.word for state in scheduler.ordered_states()] == ["beta", "alpha"]


def test_debt_count_cache_invalidates_when_history_file_changes(tmp_path):
    repo = _Repo(tmp_path, [("alpha", "noun", "first")])
    history = tmp_path / "fr_compositions.jsonl"
    scheduler = CompositionScheduler(repo, [history])

    assert scheduler.debt_count() == 1

    _write_history(
        history,
        [{"ts": "2026-06-12T10:00:00Z", "word_verdicts": {"alpha": "correct"}}],
    )

    assert scheduler.debt_count() == 0


def test_composition_env_knobs(monkeypatch):
    monkeypatch.setenv("VOCABBUILDER_COMPOSITION", "0")
    monkeypatch.setenv("VOCABBUILDER_COMPOSITION_WORDS", "5")
    monkeypatch.setenv("VOCABBUILDER_COMPOSITION_SET_SIZE", "2")

    assert composition_feature_enabled(default=True) is False
    assert composition_words_per_attempt() == 5
    assert composition_set_size() == 2

    monkeypatch.setenv("VOCABBUILDER_COMPOSITION_WORDS", "0")
    monkeypatch.setenv("VOCABBUILDER_COMPOSITION_SET_SIZE", "bad")

    assert composition_words_per_attempt() == 3
    assert composition_set_size() == 3
