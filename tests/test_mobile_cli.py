import pytest

from vocab_builder.languages import available_language_codes
from vocab_builder.mobile.cli import build_parser


@pytest.mark.parametrize("language_code", available_language_codes())
def test_single_language_flag_accepts_every_registered_language(language_code):
    args = build_parser().parse_args(["--language", language_code])

    assert args.language == language_code


def test_single_language_flag_rejects_an_unregistered_code():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--language", "xx"])
