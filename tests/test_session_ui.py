from pathlib import Path
from types import SimpleNamespace

from vocab_builder.core.llm_coordinator import InitState
from vocab_builder.core.session_ui import show_main_menu
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
    eng_to_fr = tmp_path / "EnglishToFrench.tex"
    fr_to_eng = tmp_path / "FrenchToEnglish.tex"
    eng_to_fr.write_text(
        r"""% Usage: \engfre{English Text}{French Translation}
Literal percent \% before command: \engfre{hello}{bonjour}
""",
        encoding="utf-8",
    )
    fr_to_eng.write_text(
        r"""% \freeng{commented}{ignored}
\freeng{salut}{hi}
""",
        encoding="utf-8",
    )

    app = SimpleNamespace(
        eng_to_fr_translator=None,
        fr_to_eng_translator=None,
        eng_to_fr_latex_file=eng_to_fr,
        fr_to_eng_latex_file=fr_to_eng,
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
