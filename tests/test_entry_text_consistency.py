from unittest.mock import MagicMock

from vocab_builder.core.vocab import FrenchVocabBuilder
from vocab_builder.core.word_entry_workflow import WordEntryWorkflow
from vocab_builder.languages import get_language_config


def _workflow() -> WordEntryWorkflow:
    return WordEntryWorkflow(
        vocab_repo=MagicMock(),
        llm=MagicMock(),
        ui=MagicMock(),
        language_config=get_language_config("fr"),
    )


def test_input_type_detection_is_consistent_between_builder_and_workflow() -> None:
    builder = object.__new__(FrenchVocabBuilder)
    workflow = _workflow()
    candidate = "Ceci est une phrase."

    assert builder.detect_input_type(candidate) == workflow._detect_input_type(candidate) == "sentence"


def test_input_sanitization_is_consistent_between_builder_and_workflow() -> None:
    raw = "  C’est\u200b déjà  "

    assert FrenchVocabBuilder._sanitize_word_input(raw) == WordEntryWorkflow._sanitize_input(raw) == "C'est déjà"


def test_translator_titles_use_the_same_format() -> None:
    builder = object.__new__(FrenchVocabBuilder)
    workflow = _workflow()
    config = get_language_config("fr").target_to_eng

    assert builder._translator_title(config) == workflow._translator_title(config)
