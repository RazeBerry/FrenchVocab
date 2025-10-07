import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from _stubs import install_basic_stubs

install_basic_stubs()

import eng_to_fr_translator  # noqa: E402
import fr_to_eng_translator  # noqa: E402


class _SilentConsole:
    def print(self, *args, **kwargs):
        pass


def _make_fake_prompt(responses):
    iterator = iter(responses)

    class _FakePrompt:
        @staticmethod
        def ask(*_args, **_kwargs):
            return next(iterator)

    return _FakePrompt


def test_eng_to_fr_confirm_accepts_uppercase(monkeypatch):
    translator = object.__new__(eng_to_fr_translator.EnglishToFrenchTranslator)
    translator.console = _SilentConsole()
    fake_prompt = _make_fake_prompt(["Y"])
    monkeypatch.setattr(eng_to_fr_translator, "Prompt", fake_prompt)

    assert translator._confirm_yes_no("Save translation?", default=True) is True


def test_fr_to_eng_confirm_accepts_uppercase(monkeypatch):
    translator = object.__new__(fr_to_eng_translator.FrenchToEnglishTranslator)
    translator.console = _SilentConsole()
    fake_prompt = _make_fake_prompt(["N"])
    monkeypatch.setattr(fr_to_eng_translator, "Prompt", fake_prompt)

    assert translator._confirm_yes_no("Save translation?", default=True) is False
