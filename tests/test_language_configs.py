import tempfile
from pathlib import Path

import pytest

import FrenchVocab
from languages import available_language_codes


@pytest.mark.parametrize("language_code", ["fr", "de"])
def test_builder_initializes_for_language(language_code, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x" * 40)
    with tempfile.TemporaryDirectory() as tmpdir:
        tex_path = Path(tmpdir) / f"{language_code}_vocab.tex"
        builder = FrenchVocab.FrenchVocabBuilder(
            str(tex_path),
            provider="gemini",
            verbose=False,
            language=language_code,
        )
        assert builder.language_code == language_code
        assert builder.entry_command.startswith("\\")
        builder.create_initial_tex_file()
        assert tex_path.exists()


def test_available_language_codes_include_german():
    codes = available_language_codes()
    assert "fr" in codes
    assert "de" in codes
