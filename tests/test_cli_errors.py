import pytest

import FrenchVocab
from vocab_builder.cli.main import main


def test_main_exits_cleanly_for_invalid_language() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--language", "es"])

    assert "Unsupported language code 'es'" in str(exc_info.value)


def test_main_exits_cleanly_for_invalid_provider() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--language", "fr", "--provider", "bogus"])

    assert "Unknown provider 'bogus'" in str(exc_info.value)


def test_legacy_entrypoint_shim_reexports_main() -> None:
    assert FrenchVocab.main is main


def test_main_stops_when_backups_prove_the_collection_was_lost(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VOCABBUILDER_CONFIG_DIR", str(tmp_path))
    latex_file = tmp_path / "FrenchVocab.tex"
    (tmp_path / "FrenchVocab.tex.bak").write_text("older saved content", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        main(["--language", "fr", "--latex-file", str(latex_file)])

    assert "FrenchVocab.tex is missing" in str(exc_info.value)
    assert not latex_file.exists()
