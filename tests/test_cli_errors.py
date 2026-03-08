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
