from vocab_builder.core.composition_parser import parse_composition_response


def test_parse_composition_response_full_contract():
    response = """
Corrected Text:
J'ai renverse le verre, bien que la piece soit calme.

Corrections:
1. "goss" -> "renverse"
   Why: The learner used a non-French form.
   Alternative: J'ai fait tomber le verre.

Word Verdicts:
- verser: incorrect
- bien que: correct
- quietude: not_used

Unknown Word Candidates:
- renverser: to knock over or spill

Register: consistent
""".strip()

    parsed = parse_composition_response(response)

    assert parsed.corrected_text.startswith("J'ai renverse")
    assert parsed.corrections[0].original == "goss"
    assert parsed.corrections[0].replacement == "renverse"
    assert parsed.corrections[0].why == "The learner used a non-French form."
    assert parsed.word_verdicts == {
        "verser": "incorrect",
        "bien que": "correct",
        "quietude": "not_used",
    }
    assert parsed.unknown_candidates[0].word == "renverser"
    assert parsed.unknown_candidates[0].gloss == "to knock over or spill"
    assert parsed.register == "consistent"
    assert parsed.parsing_warnings == []


def test_parse_composition_response_warns_on_missing_sections():
    parsed = parse_composition_response("Corrected Text:\nBonjour.")

    assert parsed.corrected_text == "Bonjour."
    assert parsed.corrections == []
    assert parsed.word_verdicts == {}
    assert parsed.unknown_candidates == []
    assert any("corrections" in warning for warning in parsed.parsing_warnings)
    assert any("word verdicts" in warning for warning in parsed.parsing_warnings)
    assert any("unknown word candidates" in warning for warning in parsed.parsing_warnings)
    assert any("register" in warning for warning in parsed.parsing_warnings)


def test_parse_composition_response_skips_invalid_verdicts():
    response = """
Corrected Text:
Text.

English Gloss:
The corrected English intent.

Corrections:
none

Word Verdicts:
- obwohl: excellent
- verser: correct

Unknown Word Candidates:
none

Register: consistent
""".strip()

    parsed = parse_composition_response(response)

    assert parsed.word_verdicts == {"verser": "correct"}
    assert any("invalid word verdict" in warning for warning in parsed.parsing_warnings)


def test_parse_composition_response_handles_unknown_without_gloss():
    response = """
Corrected Text:
Text.

Corrections:
none

Word Verdicts:
- obwohl: correct

Unknown Word Candidates:
- immerhin

Register: consistent
""".strip()

    parsed = parse_composition_response(response)

    assert parsed.unknown_candidates[0].word == "immerhin"
    assert parsed.unknown_candidates[0].gloss == ""


def test_parse_composition_response_parses_optional_english_gloss():
    response = """
Corrected Text:
Text.

English Gloss:
The corrected English intent.

Corrections:
none

Word Verdicts:
- obwohl: correct

Unknown Word Candidates:
none

Register: consistent
""".strip()

    parsed = parse_composition_response(response)

    assert parsed.english_gloss == "The corrected English intent."
    assert parsed.parsing_warnings == []
