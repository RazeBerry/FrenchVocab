import json
from pathlib import Path
from types import SimpleNamespace

from vocab_builder.core import VocabBuilder
from vocab_builder.core import composition as composition_module
from vocab_builder.core.llm_coordinator import InitState
from vocab_builder.core.session_ui import show_main_menu
from vocab_builder.languages import get_language_config


class _FakeLLMClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def stream(self, prompt: str):
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        yield response
        return {"usage": {"output_tokens": 10, "total_tokens": 20}}

    def model_label(self):
        return "Fake Gemini"


class _CaptureUI:
    def __init__(self, choices=None, confirm_answers=None):
        self.choices = list(choices or [])
        self.confirm_answers = list(confirm_answers or [])
        self.confirm_prompts = []
        self.panels = []
        self.options_seen = []
        self.warnings = []
        self.errors = []
        self.infos = []

    def confirm(self, message, *, default=True):  # noqa: ARG002
        self.confirm_prompts.append(message)
        if self.confirm_answers:
            return self.confirm_answers.pop(0)
        return False

    def panel(self, content, title="", **kwargs):
        self.panels.append({"content": content, "title": title, **kwargs})

    def interactive_menu(self, _title, options, *_args, **_kwargs):
        self.options_seen.append(options)
        if self.choices:
            return self.choices.pop(0)
        return "back"

    def warning(self, message, *args, **kwargs):  # noqa: ARG002
        self.warnings.append(message)

    def error(self, message, *args, **kwargs):  # noqa: ARG002
        self.errors.append(message)

    def info(self, message, *args, **kwargs):  # noqa: ARG002
        self.infos.append(message)

    def success(self, message, *args, **kwargs):  # noqa: ARG002
        return None

    def display_metrics(self, _metrics):
        return None


class _StubLLM:
    init_state = InitState.READY

    def await_init(self, timeout=None):  # noqa: ARG002
        return True


def _response_for(words, *, unknown=False):
    unknown_section = "- renverser: to knock over" if unknown else "none"
    verdict_lines = "\n".join(f"- {word}: correct" for word in words)
    return f"""
Corrected Text:
Phrase corrigee avec {", ".join(words)}.

Corrections:
1. "mal dit" -> "bien dit"
   Why: More idiomatic.
   Alternative: Formulation plus naturelle.

Word Verdicts:
{verdict_lines}

Unknown Word Candidates:
{unknown_section}

Register: consistent
""".strip()


def _read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _build_builder(tmp_path, monkeypatch, responses, *, set_size="3", words_per_attempt="3"):
    monkeypatch.setenv("VOCABBUILDER_HISTORY_DIR", str(tmp_path / "history"))
    monkeypatch.setenv("VOCABBUILDER_COMPOSITION_SET_SIZE", set_size)
    monkeypatch.setenv("VOCABBUILDER_COMPOSITION_WORDS", words_per_attempt)
    return VocabBuilder(
        str(tmp_path / "vocab.tex"),
        provider="gemini",
        verbose=False,
        client=_FakeLLMClient(responses),
        language="fr",
    )


def _seed_entries(builder, count, examples_factory=None):
    builder.word_entries = {
        f"mot{i}": {
            "word": f"mot{i}",
            "type": "noun",
            "definitions_list": [f"definition {i}"],
            "examples_list": list(examples_factory(i)) if examples_factory else [],
        }
        for i in range(1, count + 1)
    }
    builder._vocab_repo._entries_loaded = True
    builder._vocab_repo.entry_count = count


def _reverse_response(word, corrected_text, *, verdict="correct"):
    return f"""
Corrected Text:
{corrected_text}

Corrections:
none

Word Verdicts:
- {word}: {verdict}

Unknown Word Candidates:
none

Register: consistent
""".strip()


def test_composition_use_words_daily_set_writes_history_and_summary(tmp_path, monkeypatch):
    responses = [
        _response_for(["mot1", "mot2", "mot3"], unknown=True),
        _response_for(["mot4", "mot5", "mot6"]),
        _response_for(["mot7", "mot8", "mot9"]),
    ]
    builder = _build_builder(tmp_path, monkeypatch, responses)
    _seed_entries(builder, 9)

    coach = builder._ensure_composition_coach()
    capture = _CaptureUI(choices=["use_words"])
    coach.ui = capture

    lines = iter(
        [
            "Phrase avec mot1 mot2 mot3.",
            "",
            "Phrase avec mot4 mot5 mot6.",
            "",
            "Phrase avec mot7 mot8 mot9.",
            "",
        ]
    )
    monkeypatch.setattr(composition_module, "read_line", lambda _prompt="": next(lines))

    assert builder.composition_debt_count() == 9

    builder.handle_composition()

    history_path = tmp_path / "history" / "fr_compositions.jsonl"
    records = _read_jsonl(history_path)
    assert len(records) == 3
    assert records[0]["mode"] == "use_words"
    assert records[0]["english_gloss"] is None
    assert records[0]["target_words"] == ["mot1", "mot2", "mot3"]
    assert records[0]["unknown_candidates"] == [
        {"word": "renverser", "gloss": "to knock over"}
    ]
    assert records[0]["provider"] == "Fake Gemini"
    assert len({record["session_id"] for record in records}) == 1
    assert builder.composition_debt_count() == 0
    assert any(panel["title"] == "Composition Summary" for panel in capture.panels)
    assert len(builder.client.prompts) == 3
    assert "mot1" in builder.client.prompts[0]


def test_composition_escape_after_one_attempt_writes_partial_summary(tmp_path, monkeypatch):
    builder = _build_builder(
        tmp_path,
        monkeypatch,
        [_response_for(["mot1", "mot2", "mot3"])],
    )
    _seed_entries(builder, 6)

    coach = builder._ensure_composition_coach()
    capture = _CaptureUI(choices=["use_words"])
    coach.ui = capture

    lines = iter(["Phrase avec mot1 mot2 mot3.", "", "\x1b"])
    monkeypatch.setattr(composition_module, "read_line", lambda _prompt="": next(lines))

    builder.handle_composition()

    records = _read_jsonl(tmp_path / "history" / "fr_compositions.jsonl")
    assert len(records) == 1
    assert len(builder.client.prompts) == 1
    assert any("cancelled" in warning.lower() for warning in capture.warnings)
    assert any(panel["title"] == "Composition Summary" for panel in capture.panels)


def test_composition_reverse_daily_set_writes_history_and_shows_reference(tmp_path, monkeypatch):
    builder = _build_builder(
        tmp_path,
        monkeypatch,
        [_reverse_response("mot1", "La pluie tombe.")],
        set_size="1",
    )
    _seed_entries(
        builder,
        1,
        examples_factory=lambda i: [(f"Phrase cible {i}.", f"English source {i}.")],
    )

    coach = builder._ensure_composition_coach()
    capture = _CaptureUI(choices=["reverse"])
    coach.ui = capture

    lines = iter(["Phrase cible 1.", ""])
    monkeypatch.setattr(composition_module, "read_line", lambda _prompt="": next(lines))

    builder.handle_composition()

    history_path = tmp_path / "history" / "fr_compositions.jsonl"
    records = _read_jsonl(history_path)
    assert len(records) == 1
    assert records[0]["mode"] == "reverse"
    assert records[0]["english_gloss"] is None
    assert records[0]["target_words"] == ["mot1"]
    assert records[0]["source_english"] == "English source 1."
    assert records[0]["reference_target"] == "Phrase cible 1."
    assert records[0]["user_text"] == "Phrase cible 1."
    assert records[0]["provider"] == "Fake Gemini"
    assert len(builder.client.prompts) == 1
    assert "English source 1." in builder.client.prompts[0]
    assert "Phrase cible 1." in builder.client.prompts[0]
    assert any(
        "Stored original" in panel["content"] and "Phrase cible 1." in panel["content"]
        for panel in capture.panels
    )
    assert "[M2]" not in str(capture.options_seen[0])


def test_composition_reverse_accepts_equivalent_variant_as_production(tmp_path, monkeypatch):
    builder = _build_builder(
        tmp_path,
        monkeypatch,
        [_reverse_response("mot1", "Phrase cible reformulee.")],
        set_size="1",
    )
    _seed_entries(
        builder,
        1,
        examples_factory=lambda _i: [("Phrase cible.", "The target sentence.")],
    )

    coach = builder._ensure_composition_coach()
    capture = _CaptureUI(choices=["reverse"])
    coach.ui = capture

    lines = iter(["Phrase cible reformulee.", ""])
    monkeypatch.setattr(composition_module, "read_line", lambda _prompt="": next(lines))

    assert builder.composition_debt_count() == 1

    builder.handle_composition()

    records = _read_jsonl(tmp_path / "history" / "fr_compositions.jsonl")
    assert records[0]["word_verdicts"] == {"mot1": "correct"}
    assert builder.composition_debt_count() == 0
    assert "not the only acceptable answer" in builder.client.prompts[0]


def test_composition_reverse_skips_entries_without_usable_examples(tmp_path, monkeypatch):
    builder = _build_builder(tmp_path, monkeypatch, [], set_size="1")
    _seed_entries(builder, 2)

    coach = builder._ensure_composition_coach()
    capture = _CaptureUI(choices=["reverse"])
    coach.ui = capture

    builder.handle_composition()

    assert builder.client.prompts == []
    assert not (tmp_path / "history" / "fr_compositions.jsonl").exists()
    assert any("stored examples" in warning.lower() for warning in capture.warnings)


def test_composition_reverse_escape_cancels_before_grading(tmp_path, monkeypatch):
    builder = _build_builder(tmp_path, monkeypatch, [], set_size="1")
    _seed_entries(
        builder,
        1,
        examples_factory=lambda _i: [("Phrase cible.", "The target sentence.")],
    )

    coach = builder._ensure_composition_coach()
    capture = _CaptureUI(choices=["reverse"])
    coach.ui = capture

    lines = iter(["\x1b"])
    monkeypatch.setattr(composition_module, "read_line", lambda _prompt="": next(lines))

    builder.handle_composition()

    assert builder.client.prompts == []
    assert not (tmp_path / "history" / "fr_compositions.jsonl").exists()
    assert any("cancelled" in warning.lower() for warning in capture.warnings)
    assert not any(panel["title"] == "Composition Summary" for panel in capture.panels)


def test_reverse_grading_prompts_configured_for_french_and_german():
    for language in ("fr", "de"):
        template = get_language_config(language).composition.reverse_grading_prompt_template

        assert "{source_english}" in template
        assert "{reference_target}" in template
        assert "Word Verdicts:" in template
        assert "not the only acceptable answer" in template


def test_main_menu_includes_composition_debt_counter(tmp_path):
    ui = _CaptureUI(choices=["exit"])
    app = SimpleNamespace(
        eng_to_target_translator=None,
        target_to_eng_translator=None,
        eng_to_target_latex_file=tmp_path / "EnglishToFrench.tex",
        target_to_eng_latex_file=tmp_path / "FrenchToEnglish.tex",
        language_config=get_language_config("fr"),
        entry_count=12,
        _llm=_StubLLM(),
        ui=ui,
        _ui_text=lambda _key, fallback: fallback,
        enable_composition=True,
        composition_debt_count=lambda: 7,
    )

    assert show_main_menu(app) == "exit"

    labels = [label for _key, label in ui.options_seen[0]]
    assert "Composition practice   (7 unproduced)" in labels


def _run_single_attempt_with_unknown(tmp_path, monkeypatch, *, confirm_answers,
                                     run_word_entry=None, known=()):
    builder = _build_builder(
        tmp_path,
        monkeypatch,
        [_response_for(["mot1", "mot2", "mot3"], unknown=True)],
        set_size="1",
    )
    _seed_entries(builder, 3)
    if known:
        builder.normalized_entries = {word: word for word in known}

    coach = builder._ensure_composition_coach()
    capture = _CaptureUI(choices=["use_words"], confirm_answers=confirm_answers)
    coach.ui = capture
    if run_word_entry is not None:
        coach.run_word_entry = run_word_entry

    lines = iter(["Phrase avec mot1 mot2 mot3.", ""])
    monkeypatch.setattr(composition_module, "read_line", lambda _prompt="": next(lines))
    builder.handle_composition()
    return capture


def test_summary_capture_runs_seeded_workflow_for_confirmed_candidates(tmp_path, monkeypatch):
    added = []
    capture = _run_single_attempt_with_unknown(
        tmp_path, monkeypatch, confirm_answers=[True], run_word_entry=added.append
    )

    assert added == ["renverser"]
    assert any("renverser" in prompt for prompt in capture.confirm_prompts)
    assert any(panel["title"] == "Capture Unknown Words" for panel in capture.panels)


def test_summary_capture_filters_already_known_candidates(tmp_path, monkeypatch):
    added = []
    capture = _run_single_attempt_with_unknown(
        tmp_path,
        monkeypatch,
        confirm_answers=[True],
        run_word_entry=added.append,
        known=("renverser",),
    )

    assert added == []
    assert capture.confirm_prompts == []
    assert any("already in your vocabulary" in info for info in capture.infos)


def test_summary_capture_decline_all_adds_nothing(tmp_path, monkeypatch):
    added = []
    capture = _run_single_attempt_with_unknown(
        tmp_path, monkeypatch, confirm_answers=[False], run_word_entry=added.append
    )

    assert added == []
    assert len(capture.confirm_prompts) == 1


def test_summary_without_candidates_shows_no_capture_ui(tmp_path, monkeypatch):
    builder = _build_builder(
        tmp_path,
        monkeypatch,
        [_response_for(["mot1", "mot2", "mot3"])],
        set_size="1",
    )
    _seed_entries(builder, 3)

    coach = builder._ensure_composition_coach()
    capture = _CaptureUI(choices=["use_words"])
    coach.ui = capture

    lines = iter(["Phrase avec mot1 mot2 mot3.", ""])
    monkeypatch.setattr(composition_module, "read_line", lambda _prompt="": next(lines))
    builder.handle_composition()

    assert capture.confirm_prompts == []
    assert not any(panel["title"] == "Capture Unknown Words" for panel in capture.panels)


def test_summary_capture_reports_failed_words_instead_of_losing_them(tmp_path, monkeypatch):
    def boom(_word):
        raise RuntimeError("provider unavailable")

    capture = _run_single_attempt_with_unknown(
        tmp_path, monkeypatch, confirm_answers=[True], run_word_entry=boom
    )

    assert any("Could not add 'renverser'" in warning for warning in capture.warnings)
    assert any("Skipped candidates" in warning for warning in capture.warnings)


def test_coach_wires_seeded_word_entry_runner(tmp_path, monkeypatch):
    builder = _build_builder(tmp_path, monkeypatch, [])
    coach = builder._ensure_composition_coach()

    assert coach.run_word_entry == builder._run_seeded_word_entry


def test_build_word_entry_workflow_preseeds_word_input(tmp_path, monkeypatch):
    builder = _build_builder(tmp_path, monkeypatch, [])

    seeded = builder._build_word_entry_workflow(get_word_input_fn=lambda: "renverser")
    assert seeded._get_word_input_fn() == "renverser"

    default = builder._build_word_entry_workflow()
    assert default._get_word_input_fn == builder.get_word_input
