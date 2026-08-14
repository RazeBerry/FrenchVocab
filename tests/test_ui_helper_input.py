from __future__ import annotations

import vocab_builder.ui_helper as ui_helper


class _Console:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def input(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


def test_low_latency_read_line_bypasses_prompt_toolkit(monkeypatch):
    monkeypatch.setenv("VOCABBUILDER_LOW_LATENCY_INPUT", "yes")
    monkeypatch.setattr(
        ui_helper,
        "_prompt_with_prompt_toolkit",
        lambda _prompt: (_ for _ in ()).throw(AssertionError("raw prompt used")),
    )
    console = _Console("bonjour")

    assert ui_helper.read_line("Text: ", console=console) == "bonjour"
    assert console.prompts == ["Text: "]
