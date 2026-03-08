from pathlib import Path

from rich.console import Console

from core.translator import TranslatorCLI
from languages import get_language_config


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
