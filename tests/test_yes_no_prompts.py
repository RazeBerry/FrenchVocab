import vocab_builder.core.translator as translator_module


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


def _translator_stub():
    translator = object.__new__(translator_module.TranslatorCLI)
    translator.console = _SilentConsole()
    translator.source_label = "Source"
    translator.target_label = "Target"
    translator.prompt_variable = "text"
    translator.prompt_template = ""
    translator.latex_command = "cmd"
    translator.pairs = {}
    translator.entry_count = 0
    return translator


def test_confirm_accepts_uppercase(monkeypatch):
    translator = _translator_stub()
    fake_prompt = _make_fake_prompt(["Y"])
    monkeypatch.setattr(translator_module, "Prompt", fake_prompt)

    assert translator._confirm_yes_no("Save translation?", default=True) is True


def test_confirm_accepts_uppercase_no(monkeypatch):
    translator = _translator_stub()
    fake_prompt = _make_fake_prompt(["N"])
    monkeypatch.setattr(translator_module, "Prompt", fake_prompt)

    assert translator._confirm_yes_no("Save translation?", default=True) is False
