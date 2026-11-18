"""Offline checks of the prompt panel: templates, scorer and tokenizer."""

import importlib
import json
import sys
from pathlib import Path

import pytest

import vocab_builder
from vocab_builder.ai_prompts import AI_PROMPT_TEMPLATE, GERMAN_PROMPT_TEMPLATE
from vocab_builder.ai_response_parser import parse_ai_response_text


def _import_run_panel():
    """Import the panel runner against the real llm_client, then put back the
    conftest stub, which lacks the DEFAULT_THINKING_LEVEL the runner reads."""
    stub = sys.modules.pop("vocab_builder.llm_client", None)
    try:
        return importlib.import_module("scripts.prompt_panel.run_panel")
    finally:
        if stub is not None:
            sys.modules["vocab_builder.llm_client"] = stub
            vocab_builder.llm_client = stub


run_panel = _import_run_panel()
PANEL = json.loads((Path(run_panel.__file__).parent / "panel.json").read_text(encoding="utf-8"))
SPECS = {spec["word"]: spec for spec in PANEL["words"]}

POSZEDL = """Spelling Check: OK
Correctly Spelt Word: pójść
Word Type: perfective verb
Definitions:
a. To go on foot. Imperfective: iść.
b. Usage note: The past tense is irregular: poszedł, poszła.
Examples:
1. Marek poszedł do sklepu.
(Marek went to the shop.)
2. Anna poszła do pracy.
(Anna went to work.)
"""


def test_every_panel_language_has_a_candidate_template():
    templates = run_panel.load_templates("candidate")
    assert {spec["language"] for spec in PANEL["words"]} <= set(templates)


def test_french_and_german_candidates_are_the_shipped_prompts():
    # The Polish-only fields are empty for French and German, so the candidate
    # module still generates the literals that ai_prompts.py ships.
    templates = run_panel.load_templates("candidate")
    assert templates["fr"] == AI_PROMPT_TEMPLATE
    assert templates["de"] == GERMAN_PROMPT_TEMPLATE


def test_score_matches_polish_lemma_type_and_partner_with_diacritics():
    result = run_panel.score(SPECS["poszedł"], parse_ai_response_text(POSZEDL), "pójść", PANEL["hedges"])
    assert result["corrected_ok"] and result["type_ok"] and result["required_ok"]
    assert result["passed"]


@pytest.mark.parametrize(
    ("old", "new", "check"),
    [
        ("Correctly Spelt Word: pójść", "Correctly Spelt Word: iść", "corrected_ok"),
        ("Word Type: perfective verb", "Word Type: imperfective verb", "type_ok"),
        ("Imperfective: iść.", "Imperfective: chodzić.", "required_ok"),
    ],
)
def test_score_fails_the_wrong_polish_lemma_type_or_partner(old, new, check):
    raw = POSZEDL.replace(old, new)
    corrected = raw.split("Correctly Spelt Word: ")[1].splitlines()[0]
    result = run_panel.score(SPECS["poszedł"], parse_ai_response_text(raw), corrected, PANEL["hedges"])
    assert not result[check]
    assert not result["passed"]


def test_content_words_keep_polish_letters_and_skip_aspect_labels():
    assert run_panel.content_words("To write. Perfective: napisać.") == {"write", "napisać"}
