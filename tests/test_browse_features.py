"""Tests for the browse vocabulary submenu features."""

import json
from pathlib import Path
from types import SimpleNamespace

import core.vocab_display_mixin as vocab_display_module
from core.history_logger import TranslationLogger
from core.vocab_display_mixin import VocabDisplayMixin


# --------------------------------------------------------------------------- #
# TranslationLogger.read_recent_vocab_entries
# --------------------------------------------------------------------------- #


def _write_jsonl(path: Path, records):
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def test_read_recent_vocab_entries_basic(tmp_path):
    logger = TranslationLogger(language_code="fr", base_dir=tmp_path)
    path = tmp_path / "fr_translations.jsonl"

    records = [
        {"timestamp": "2025-01-01T00:00:00+00:00", "language": "fr", "flow": "vocab",
         "action": "new", "word": "bonjour", "word_type": "noun"},
        {"timestamp": "2025-01-02T00:00:00+00:00", "language": "fr", "flow": "translator",
         "direction": "eng_to_target", "source_text": "hello"},
        {"timestamp": "2025-01-03T00:00:00+00:00", "language": "fr", "flow": "vocab",
         "action": "new", "word": "merci", "word_type": "interjection"},
        {"timestamp": "2025-01-04T00:00:00+00:00", "language": "fr", "flow": "vocab",
         "action": "merge", "word": "bonjour", "word_type": "noun"},
    ]
    _write_jsonl(path, records)

    result = logger.read_recent_vocab_entries(limit=10)

    # Should return only vocab records, newest first
    assert len(result) == 3
    assert result[0]["word"] == "bonjour"
    assert result[0]["action"] == "merge"
    assert result[1]["word"] == "merci"
    assert result[2]["word"] == "bonjour"
    assert result[2]["action"] == "new"


def test_read_recent_vocab_entries_limit(tmp_path):
    logger = TranslationLogger(language_code="fr", base_dir=tmp_path)
    path = tmp_path / "fr_translations.jsonl"

    records = [
        {"timestamp": f"2025-01-{i:02d}T00:00:00+00:00", "language": "fr",
         "flow": "vocab", "action": "new", "word": f"word{i}", "word_type": "noun"}
        for i in range(1, 21)
    ]
    _write_jsonl(path, records)

    result = logger.read_recent_vocab_entries(limit=5)
    assert len(result) == 5
    # Newest first
    assert result[0]["word"] == "word20"
    assert result[4]["word"] == "word16"


def test_read_recent_vocab_entries_supports_action_filter_and_unbounded_reads(tmp_path):
    logger = TranslationLogger(language_code="fr", base_dir=tmp_path)
    path = tmp_path / "fr_translations.jsonl"

    records = [
        {"timestamp": "2025-01-01T00:00:00+00:00", "language": "fr", "flow": "vocab",
         "action": "new", "word": "bonjour", "word_type": "noun"},
        {"timestamp": "2025-01-02T00:00:00+00:00", "language": "fr", "flow": "vocab",
         "action": "merge", "word": "bonjour", "word_type": "noun"},
        {"timestamp": "2025-01-03T00:00:00+00:00", "language": "fr", "flow": "vocab",
         "action": "force", "word": "bonjour 2", "word_type": "noun"},
    ]
    _write_jsonl(path, records)

    result = logger.read_recent_vocab_entries(limit=None, actions={"new", "force"})

    assert [record["action"] for record in result] == ["force", "new"]
    assert [record["word"] for record in result] == ["bonjour 2", "bonjour"]


def test_read_recent_vocab_entries_missing_file(tmp_path):
    logger = TranslationLogger(language_code="fr", base_dir=tmp_path)
    assert logger.read_recent_vocab_entries() == []


def test_read_recent_vocab_entries_empty_file(tmp_path):
    logger = TranslationLogger(language_code="fr", base_dir=tmp_path)
    path = tmp_path / "fr_translations.jsonl"
    path.write_text("")
    assert logger.read_recent_vocab_entries() == []


def test_read_recent_vocab_entries_malformed_lines(tmp_path):
    logger = TranslationLogger(language_code="fr", base_dir=tmp_path)
    path = tmp_path / "fr_translations.jsonl"
    path.write_text(
        'not valid json\n'
        '{"timestamp": "2025-01-01T00:00:00+00:00", "flow": "vocab", "action": "new", "word": "ok"}\n'
    )
    result = logger.read_recent_vocab_entries()
    assert len(result) == 1
    assert result[0]["word"] == "ok"


# --------------------------------------------------------------------------- #
# VocabDisplayMixin._collect_type_counts
# --------------------------------------------------------------------------- #


class _FakeDisplayMixin(VocabDisplayMixin):
    """Minimal fake to test mixin methods that only need word_entries."""

    DEFINITION_PREVIEW_LIMIT = 60

    def __init__(self, entries, ui=None, history_logger=None):
        self.word_entries = entries
        self.normalized_entries = {self.normalize_word(key): key for key in entries}
        self.ui = ui or _FakeUI()
        self.history_logger = history_logger
        self.displayed_entries = []
        self.language_config = SimpleNamespace(display_name="French")

    @staticmethod
    def normalize_word(word):
        return word.lower()

    def _ensure_entries_loaded(self):
        return None

    def display_existing_entry(self, word):
        self.displayed_entries.append(word)


class _FakeUI:
    def __init__(self, menu_choices=None):
        self.menu_choices = list(menu_choices or [])
        self.tables = []
        self.panels = []
        self.warnings = []
        self.infos = []

    def interactive_menu(self, _title, _options, *_args, **_kwargs):
        if not self.menu_choices:
            raise AssertionError("interactive_menu called without a queued choice")
        return self.menu_choices.pop(0)

    def render_table(self, **kwargs):
        self.tables.append(kwargs)

    def panel(self, content, **kwargs):
        self.panels.append({"content": content, **kwargs})

    def info(self, message, *args, **kwargs):
        self.infos.append(message)

    def warning(self, message, *args, **kwargs):
        self.warnings.append(message)


def test_collect_type_counts():
    entries = {
        "chat": {"word": "Chat", "type": "noun", "definitions": "cat"},
        "manger": {"word": "Manger", "type": "verb", "definitions": "to eat"},
        "beau": {"word": "Beau", "type": "adjective", "definitions": "beautiful"},
        "chien": {"word": "Chien", "type": "noun", "definitions": "dog"},
        "courir": {"word": "Courir", "type": "verb", "definitions": "to run"},
    }
    mixin = _FakeDisplayMixin(entries)
    counts = mixin._collect_type_counts()

    assert counts["noun"] == 2
    assert counts["verb"] == 2
    assert counts["adjective"] == 1


def test_collect_type_counts_list_types():
    entries = {
        "grand": {"word": "Grand", "type": ["adjective", "adverb"], "definitions": "big"},
    }
    mixin = _FakeDisplayMixin(entries)
    counts = mixin._collect_type_counts()
    assert counts["adjective, adverb"] == 1


def test_browse_vocabulary_routes_choices_until_back():
    class _BrowseApp(_FakeDisplayMixin):
        def __init__(self):
            super().__init__({}, ui=_FakeUI(menu_choices=["recent", "stats", "back"]))
            self.calls = []

        def show_recently_added(self, limit=15):
            self.calls.append(("recent", limit))

        def show_vocab_stats(self):
            self.calls.append(("stats", None))

    mixin = _BrowseApp()
    mixin.browse_vocabulary()

    assert mixin.calls == [("recent", 15), ("stats", None)]


def test_show_recently_added_skips_deleted_and_fills_limit_from_older_history(tmp_path):
    logger = TranslationLogger(language_code="fr", base_dir=tmp_path)
    path = tmp_path / "fr_translations.jsonl"
    records = [
        {"timestamp": "2025-01-01T00:00:00+00:00", "language": "fr", "flow": "vocab",
         "action": "new", "word": "alpha", "word_type": "noun"},
        {"timestamp": "2025-01-02T00:00:00+00:00", "language": "fr", "flow": "vocab",
         "action": "new", "word": "beta", "word_type": "noun"},
        {"timestamp": "2025-01-03T00:00:00+00:00", "language": "fr", "flow": "vocab",
         "action": "force", "word": "beta", "word_type": "noun"},
        {"timestamp": "2025-01-04T00:00:00+00:00", "language": "fr", "flow": "vocab",
         "action": "new", "word": "deleted", "word_type": "noun"},
        {"timestamp": "2025-01-05T00:00:00+00:00", "language": "fr", "flow": "vocab",
         "action": "merge", "word": "beta", "word_type": "noun"},
    ]
    _write_jsonl(path, records)

    ui = _FakeUI()
    mixin = _FakeDisplayMixin(
        {
            "alpha": {"word": "Alpha", "type": "noun", "definitions": "first"},
            "beta": {"word": "Beta", "type": "noun", "definitions": "second"},
        },
        ui=ui,
        history_logger=logger,
    )
    mixin._prompt_definition_number = lambda: None

    mixin.show_recently_added(limit=2)

    assert len(ui.tables) == 1
    rows = ui.tables[0]["rows"]
    assert rows == [
        ["1", "Beta", "noun", "variant", "14mo ago"],
        ["2", "Alpha", "noun", "added", "14mo ago"],
    ]


def test_browse_by_word_type_renders_only_selected_entries():
    ui = _FakeUI(menu_choices=["noun"])
    mixin = _FakeDisplayMixin(
        {
            "chat": {"word": "Chat", "type": "noun", "definitions": "cat"},
            "chien": {"word": "Chien", "type": "noun", "definitions": "dog"},
            "courir": {"word": "Courir", "type": "verb", "definitions": "to run"},
        },
        ui=ui,
    )

    mixin.browse_by_word_type()

    assert len(ui.tables) == 1
    rows = ui.tables[0]["rows"]
    assert rows == [["1", "Chat", "cat"], ["2", "Chien", "dog"]]


def test_random_flashcard_reveals_selected_entry(monkeypatch):
    ui = _FakeUI()
    mixin = _FakeDisplayMixin(
        {
            "chat": {"word": "Chat", "type": "noun", "definitions": "cat"},
            "chien": {"word": "Chien", "type": "noun", "definitions": "dog"},
        },
        ui=ui,
    )

    monkeypatch.setattr("random.choice", lambda seq: "chien")
    responses = iter(["", "n"])
    monkeypatch.setattr(vocab_display_module, "read_line", lambda _prompt="": next(responses))

    mixin.random_flashcard()

    assert mixin.displayed_entries == ["chien"]
    assert ui.panels[0]["content"] == "[bold magenta]Chien[/bold magenta]"


def test_show_vocab_stats_counts_all_recent_additions_and_ignores_merges(tmp_path):
    from datetime import datetime, timedelta, timezone

    logger = TranslationLogger(language_code="fr", base_dir=tmp_path)
    path = tmp_path / "fr_translations.jsonl"
    now = datetime.now(timezone.utc)
    records = [
        {
            "timestamp": (now - timedelta(hours=119 - i)).isoformat(),
            "language": "fr",
            "flow": "vocab",
            "action": "new",
            "word": f"word{i}",
            "word_type": "noun",
        }
        for i in range(120)
    ]
    records.append(
        {
            "timestamp": now.isoformat(),
            "language": "fr",
            "flow": "vocab",
            "action": "merge",
            "word": "merged-word",
            "word_type": "noun",
        }
    )
    _write_jsonl(path, records)

    ui = _FakeUI()
    mixin = _FakeDisplayMixin(
        {
            "bonjour": {"word": "Bonjour", "type": "noun", "definitions": "hello"},
            "salut": {"word": "Salut", "type": "noun", "definitions": "hi"},
        },
        ui=ui,
        history_logger=logger,
    )

    mixin.show_vocab_stats()

    assert len(ui.panels) == 1
    content = ui.panels[0]["content"]
    assert '[bold]Last added:[/bold] "word119"' in content
    assert "[bold]This week:[/bold]  +120 entries" in content


# --------------------------------------------------------------------------- #
# VocabDisplayMixin._format_relative_time
# --------------------------------------------------------------------------- #


def test_format_relative_time_invalid():
    assert VocabDisplayMixin._format_relative_time("not-a-date") == "unknown"
    assert VocabDisplayMixin._format_relative_time("") == "unknown"


def test_format_relative_time_recent():
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    ts = (now - timedelta(minutes=5)).isoformat()
    result = VocabDisplayMixin._format_relative_time(ts)
    assert result == "5m ago"


def test_format_relative_time_hours():
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    ts = (now - timedelta(hours=3)).isoformat()
    result = VocabDisplayMixin._format_relative_time(ts)
    assert result == "3h ago"


def test_format_relative_time_days():
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    ts = (now - timedelta(days=5)).isoformat()
    result = VocabDisplayMixin._format_relative_time(ts)
    assert result == "5d ago"


def test_show_vocab_stats_renders_without_errors():
    ui = _FakeUI()
    mixin = _FakeDisplayMixin(
        {
            "chat": {"word": "Chat", "type": "noun", "definitions": "cat"},
            "courir": {"word": "Courir", "type": "verb", "definitions": "to run"},
        },
        ui=ui,
    )

    mixin.show_vocab_stats()

    assert len(ui.panels) == 1
    assert "Total words" in ui.panels[0]["content"]
