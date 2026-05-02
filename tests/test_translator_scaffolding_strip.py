from pathlib import Path

from rich.console import Console

from vocab_builder.core.translator import TranslatorCLI
from vocab_builder.languages import get_language_config


def _de_translator(tmp_path: Path) -> TranslatorCLI:
    return TranslatorCLI(
        console=Console(),
        client=None,
        config=get_language_config("de").eng_to_target,
        latex_file_path=tmp_path / "translations.tex",
    )


def _de_to_en_translator(tmp_path: Path) -> TranslatorCLI:
    return TranslatorCLI(
        console=Console(),
        client=None,
        config=get_language_config("de").target_to_eng,
        latex_file_path=tmp_path / "translations.tex",
    )


def test_strips_leading_german_translation_label(tmp_path):
    t = _de_translator(tmp_path)
    raw = "German translation: Ich gehöre nicht zur Partei des Proletariats."
    assert t._strip_translation_scaffolding(raw) == "Ich gehöre nicht zur Partei des Proletariats."


def test_strips_label_case_insensitively(tmp_path):
    t = _de_translator(tmp_path)
    assert t._strip_translation_scaffolding("german TRANSLATION: foo") == "foo"
    assert t._strip_translation_scaffolding("Translation:   bar") == "bar"


def test_strips_trailing_notes_optional_block(tmp_path):
    t = _de_translator(tmp_path)
    raw = (
        "Ich bemitleide Sie\n"
        "Notes (optional): Although \"dich\" (informal singular) is grammatically possible, "
        "the formal Sie is the most resonant choice here."
    )
    assert t._strip_translation_scaffolding(raw) == "Ich bemitleide Sie"


def test_strips_bare_notes_block(tmp_path):
    t = _de_translator(tmp_path)
    raw = "Hallo Welt\nNotes: nothing notable"
    assert t._strip_translation_scaffolding(raw) == "Hallo Welt"


def test_strips_both_label_and_notes_in_one_pass(tmp_path):
    t = _de_translator(tmp_path)
    raw = (
        "German translation: Welches größere Vergnügen könnte mir überhaupt noch zuteilwerden?\n"
        "Notes (optional): The German is elevated and slightly archaic to match the rhetorical English."
    )
    assert (
        t._strip_translation_scaffolding(raw)
        == "Welches größere Vergnügen könnte mir überhaupt noch zuteilwerden?"
    )


def test_handles_de_to_en_english_translation_label(tmp_path):
    t = _de_to_en_translator(tmp_path)
    raw = "English Translation: It's already almost midnight."
    assert t._strip_translation_scaffolding(raw) == "It's already almost midnight."


def test_preserves_clean_translation_unchanged(tmp_path):
    t = _de_translator(tmp_path)
    raw = "Letztendlich"
    assert t._strip_translation_scaffolding(raw) == "Letztendlich"


def test_preserves_multiline_translation_body(tmp_path):
    t = _de_translator(tmp_path)
    raw = (
        "German translation: Erste Zeile\n"
        "Zweite Zeile\n"
        "Dritte Zeile\n"
        "Notes (optional): irrelevant"
    )
    assert (
        t._strip_translation_scaffolding(raw)
        == "Erste Zeile\nZweite Zeile\nDritte Zeile"
    )


def test_empty_input_returns_empty(tmp_path):
    t = _de_translator(tmp_path)
    assert t._strip_translation_scaffolding("") == ""
    assert t._strip_translation_scaffolding("   \n\n  ") == ""


def test_does_not_strip_notes_at_position_zero(tmp_path):
    """A response that is *only* a Notes block should leave nothing behind so
    the empty-response check downstream can flag it. Confirming current behaviour."""
    t = _de_translator(tmp_path)
    raw = "Notes (optional): The model produced no actual translation."
    assert t._strip_translation_scaffolding(raw) == ""


# ---------------------------------------------------------------------------
# Truncated-paste sanitization
# ---------------------------------------------------------------------------


def test_truncation_detector_passes_through_short_input():
    sanitized, dropped = _truncation("Hallo Welt")
    assert sanitized == "Hallo Welt"
    assert dropped is None


def test_truncation_detector_passes_through_well_terminated_long_input():
    text = "Wir treffen uns morgen am Bahnhof, weil das Wetter besser wird und wir wandern gehen wollen."
    sanitized, dropped = _truncation(text)
    assert sanitized == text
    assert dropped is None


def test_truncation_detector_catches_mid_word_clip():
    text = (
        "Approximately 115 million RM nominal value of the bond remained permanently "
        "in the possession of the Reich and were placed into the statutory sinking fund verwan"
    )
    sanitized, dropped = _truncation(text)
    assert dropped == "verwan"
    assert sanitized.endswith("statutory sinking fund")


def test_truncation_detector_respects_terminal_quote():
    text = (
        '"Inflation, das gäb\' ja eine Revolution, glatt eine Revolution"'
        + " " * 30  # padding to reach threshold
    )
    text = text.rstrip()  # trailing whitespace gets stripped
    sanitized, dropped = _truncation(text)
    assert dropped is None


def test_truncation_detector_respects_terminal_punctuation():
    text = "Es ist schon fast Mitternacht. Deshalb sollten wir jetzt nach Hause gehen."
    sanitized, dropped = _truncation(text)
    assert sanitized == text
    assert dropped is None


def test_truncation_detector_handles_single_long_token():
    text = "abcdefghijklmnopqrstuvwxyz" * 10  # 260 chars, no whitespace
    sanitized, dropped = _truncation(text)
    assert sanitized == text
    assert dropped is None


def test_truncation_detector_strips_trailing_whitespace_only():
    text = "Es ist schon fast Mitternacht. Deshalb sollten wir jetzt nach Hause gehen.   \n"
    sanitized, dropped = _truncation(text)
    assert sanitized == text.rstrip()
    assert dropped is None


def _truncation(text: str):
    from vocab_builder.core.translator import TranslatorCLI

    return TranslatorCLI._detect_truncated_input(text)

