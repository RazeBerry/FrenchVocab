import pytest

import FrenchVocab


def test_main_exits_cleanly_for_invalid_language() -> None:
    with pytest.raises(SystemExit) as exc_info:
        FrenchVocab.main(["--language", "es"])

    assert "Unsupported language code 'es'" in str(exc_info.value)


def test_main_exits_cleanly_for_invalid_provider() -> None:
    with pytest.raises(SystemExit) as exc_info:
        FrenchVocab.main(["--language", "fr", "--provider", "bogus"])

    assert "Unknown provider 'bogus'" in str(exc_info.value)
