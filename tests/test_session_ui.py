from pathlib import Path
from types import SimpleNamespace

from vocab_builder.core.llm_coordinator import InitState
from vocab_builder.core.session_ui import show_main_menu
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


def test_clean_exit_does_not_build_an_anki_package():
    class _ExitUI:
        def __init__(self):
            self.panels = []
            self.warnings = []

        def panel(self, content, **kwargs):
            self.panels.append((content, kwargs))

        def warning(self, message, **_kwargs):
            self.warnings.append(message)

    def _forbidden():
        raise AssertionError("a clean exit must not initialize the Anki manager")

    builder = object.__new__(VocabBuilder)
    builder._anki = None
    builder._ensure_anki_manager = _forbidden
    builder.ui = _ExitUI()
    builder.verbose = False
    builder.language_config = get_language_config("fr")
    builder.alphabetize_entries = lambda *, silent=False: None  # noqa: ARG005
    builder._ui_text = lambda _key, fallback: fallback
    builder._format_token_summary = lambda: ""

    builder.exit_screen()

    assert builder.ui.warnings == []
    content, kwargs = builder.ui.panels[-1]
    assert kwargs["title"] == "Goodbye!"
    assert "Anki" not in content
