import json
from pathlib import Path

from core.history_logger import TranslationLogger


def _read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def test_logger_writes_per_language(tmp_path):
    logger_fr = TranslationLogger(language_code="fr", base_dir=tmp_path, enabled=True)
    logger_de = TranslationLogger(language_code="de", base_dir=tmp_path, enabled=True)

    fr_tex = tmp_path / "FrenchVocab.tex"
    de_tex = tmp_path / "GermanVocab.tex"

    logger_fr.log_vocab_entry(
        word="bonjour",
        word_type="noun",
        definitions=["greeting"],
        examples=[("Bonjour", "Hello")],
        source_text="bonjour",
        normalized_key="bonjour",
        provider="gemini",
        latex_file=fr_tex,
        action="new",
    )
    logger_fr.log_merge_entry(
        word="bonjour",
        final_type="noun",
        merged_definitions=["greeting", "salutation"],
        merged_examples=[("Bonjour, tout le monde", "Hello everyone")],
        added_definitions=["salutation"],
        added_examples=[("Bonjour, tout le monde", "Hello everyone")],
        provider="gemini",
        latex_file=fr_tex,
        normalized_key="bonjour",
    )

    logger_de.log_translator_entry(
        direction="eng_to_target",
        source_text="good morning",
        target_text="guten Morgen",
        normalized_key="good morning",
        provider="gemini",
        latex_file=de_tex,
        source_label="English",
        target_label="German",
    )

    fr_log = tmp_path / "fr_translations.jsonl"
    de_log = tmp_path / "de_translations.jsonl"

    fr_records = _read_jsonl(fr_log)
    de_records = _read_jsonl(de_log)

    assert len(fr_records) == 2
    assert fr_records[0]["flow"] == "vocab"
    assert fr_records[1]["metadata"]["added_definitions"] == ["salutation"]
    assert de_records[0]["flow"] == "translator"
    assert de_records[0]["target_text"] == "guten Morgen"


def test_logger_disabled(tmp_path):
    logger = TranslationLogger(language_code="fr", base_dir=tmp_path, enabled=False)
    logger.log_vocab_entry(
        word="bonjour",
        word_type="noun",
        definitions=["greeting"],
        examples=[],
        source_text="bonjour",
        normalized_key="bonjour",
        provider="gemini",
        latex_file=tmp_path / "FrenchVocab.tex",
        action="new",
    )
    assert not (tmp_path / "fr_translations.jsonl").exists()
