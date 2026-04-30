from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from vocab_builder.core.translator import TranslatorCLI
from vocab_builder.languages import get_language_config


class _StubClient:
    def stream(self, _prompt: str, *, thinking_level: str = "low"):  # noqa: ARG002
        yield "bonjour"

    def model_label(self) -> str:
        return "Stub Translator"


def _translator(tmp_path: Path) -> TranslatorCLI:
    return TranslatorCLI(
        console=Console(),
        client=_StubClient(),
        config=get_language_config("fr").eng_to_target,
        latex_file_path=tmp_path / "translations.tex",
    )


def test_translate_and_save_stops_on_file_write_failure(tmp_path):
    translator = _translator(tmp_path)
    translator.confirm_translation = lambda *_args, **_kwargs: True

    recorded = {"memory": 0, "history": 0}

    translator._add_entry_to_file = lambda _entry: False
    translator._add_entry_to_memory = lambda *_args, **_kwargs: recorded.__setitem__("memory", recorded["memory"] + 1)
    translator._log_saved_translation = lambda *_args, **_kwargs: recorded.__setitem__("history", recorded["history"] + 1)

    assert translator.translate_and_save("hello", provided_translation="bonjour") is False
    assert recorded["memory"] == 0
    assert recorded["history"] == 0


def test_translator_loader_ignores_usage_comments(tmp_path):
    translator = _translator(tmp_path)

    translator.load_existing_entries()

    assert translator.pairs == {}


def test_translator_loader_keeps_escaped_percent_before_command(tmp_path):
    translator = _translator(tmp_path)
    translator.latex_file.write_text(
        r"""\documentclass{article}
\begin{document}
\begin{itemize}[leftmargin=*]
Literal percent \% before a command does not comment it out: \engfre{hello}{bonjour}
% \engfre{commented}{ignored}
\end{itemize}
\end{document}
""",
        encoding="utf-8",
    )

    translator.load_existing_entries()

    assert list(translator.pairs.values()) == [{"source": "hello", "target": "bonjour"}]


def test_translator_loader_preserves_duplicate_pairs(tmp_path):
    translator = _translator(tmp_path)
    translator.latex_file.write_text(
        get_language_config("fr").eng_to_target.initial_tex_content
        + r"\engfre{hello}{bonjour}"
        + "\n"
        + r"\engfre{hello!}{salut}"
        + "\n\n"
        + get_language_config("fr").eng_to_target.final_tex_content,
        encoding="utf-8",
    )

    translator.load_existing_entries()

    assert len(translator.pairs) == 2
    assert translator.check_duplicate("hello") == {"source": "hello", "target": "bonjour"}
    duplicate_entries = [
        entry for entry in translator.pairs.values()
        if entry.get("duplicate_of") == "hello"
    ]
    assert duplicate_entries == [{"source": "hello!", "target": "salut", "duplicate_of": "hello"}]


def test_translator_restores_backup_instead_of_blank_template(tmp_path):
    path = tmp_path / "translations.tex"
    backup = path.with_suffix(".tex.bak")
    backup.write_text(
        get_language_config("fr").eng_to_target.initial_tex_content
        + r"\engfre{saved source}{saved target}"
        + "\n\n"
        + get_language_config("fr").eng_to_target.final_tex_content,
        encoding="utf-8",
    )

    translator = TranslatorCLI(
        console=Console(),
        client=_StubClient(),
        config=get_language_config("fr").eng_to_target,
        latex_file_path=path,
    )

    assert path.read_text(encoding="utf-8") == backup.read_text(encoding="utf-8")
    assert list(translator.pairs.values()) == [{"source": "saved source", "target": "saved target"}]


def test_translator_does_not_replace_failed_backup_restore_with_template(tmp_path):
    path = tmp_path / "translations.tex"
    backup = path.with_suffix(".tex.bak")
    backup.write_text(
        get_language_config("fr").eng_to_target.initial_tex_content
        + r"\engfre{saved source}{saved target}"
        + "\n\n"
        + get_language_config("fr").eng_to_target.final_tex_content,
        encoding="utf-8",
    )

    def fail_copy(_source, temp_destination):
        Path(temp_destination).write_text("partial restore", encoding="utf-8")
        raise OSError("simulated restore failure")

    with patch("vocab_builder.core.file_safety.shutil.copy2", side_effect=fail_copy):
        TranslatorCLI(
            console=Console(),
            client=_StubClient(),
            config=get_language_config("fr").eng_to_target,
            latex_file_path=path,
        )

    assert not path.exists()
    assert "saved source" in backup.read_text(encoding="utf-8")
