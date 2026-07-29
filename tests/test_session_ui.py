from pathlib import Path
from types import SimpleNamespace

from vocab_builder.core.anki_manager import AnkiSnapshotResult, AnkiSnapshotStatus
from vocab_builder.core.llm_coordinator import InitState
from vocab_builder.core.session_ui import refresh_anki_snapshot_on_exit, show_main_menu
from vocab_builder.core.vocab import VocabBuilder
from vocab_builder.languages import get_language_config


class _StubUI:
    def __init__(self):
        self.panels = []

    def panel(self, content, **kwargs):
        self.panels.append((content, kwargs))

    def interactive_menu(self, *_args, **_kwargs):
        return "exit"


class _StubLLM:
    init_state = InitState.IN_PROGRESS

    def await_init(self, timeout=None):  # noqa: ARG002
        return False


def test_main_menu_counts_translation_files_while_ai_initializes(tmp_path: Path):
    eng_to_target = tmp_path / "EnglishToFrench.tex"
    target_to_eng = tmp_path / "FrenchToEnglish.tex"
    eng_to_target.write_text(
        r"""% Usage: \engfre{English Text}{French Translation}
Literal percent \% before command: \engfre{hello}{bonjour}
""",
        encoding="utf-8",
    )
    target_to_eng.write_text(
        r"""% \freeng{commented}{ignored}
\freeng{salut}{hi}
""",
        encoding="utf-8",
    )

    app = SimpleNamespace(
        eng_to_target_translator=None,
        target_to_eng_translator=None,
        eng_to_target_latex_file=eng_to_target,
        target_to_eng_latex_file=target_to_eng,
        language_config=get_language_config("fr"),
        entry_count=462,
        _llm=_StubLLM(),
        ui=_StubUI(),
        _ui_text=lambda _key, fallback: fallback,
    )

    assert show_main_menu(app) == "exit"

    status_text = app.ui.panels[0][0]
    assert "Library:[/bold] 462 vocab words" in status_text
    assert "Translations:[/bold] 2 pairs" in status_text
    assert "AI:[/bold] [yellow]Initializing[/yellow]" in status_text


def test_clean_exit_refreshes_snapshot_without_prompting(tmp_path: Path):
    destination = tmp_path / "anki_exports" / "French Vocabulary.apkg"

    class _SnapshotManager:
        def __init__(self):
            self.calls = []

        def export_snapshot_if_changed(self, **kwargs):
            self.calls.append(kwargs)
            return AnkiSnapshotResult(
                AnkiSnapshotStatus.EXPORTED,
                path=destination,
                packaged_count=2,
            )

    class _ExitUI:
        def __init__(self):
            self.panels = []
            self.warnings = []

        def panel(self, content, **kwargs):
            self.panels.append((content, kwargs))

        def warning(self, message, **_kwargs):
            self.warnings.append(message)

    builder = object.__new__(VocabBuilder)
    builder._anki = _SnapshotManager()
    builder.ui = _ExitUI()
    builder.verbose = False
    builder.language_config = get_language_config("fr")
    builder.alphabetize_entries = lambda *, silent=False: None  # noqa: ARG005
    builder._ui_text = lambda _key, fallback: fallback
    builder._format_token_summary = lambda: ""

    builder.exit_screen()

    assert builder._anki.calls == [{"export_context": "clean_exit", "quiet": True}]
    assert builder.ui.warnings == []
    assert str(destination) in builder.ui.panels[-1][0]


def test_clean_exit_snapshot_can_be_disabled(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VOCABBUILDER_EXIT_SNAPSHOT", "0")

    class _App:
        def _ensure_anki_manager(self):
            raise AssertionError("disabled snapshots must not initialize Anki")

    assert refresh_anki_snapshot_on_exit(_App()) is None
    assert list(tmp_path.iterdir()) == []
