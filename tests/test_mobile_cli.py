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


def test_the_server_serves_every_collection_by_default(tmp_path, monkeypatch):
    """Without --languages the served app lists Polish beside the other three,
    in the order the switch shows them. Driven through main() and the real
    catalog; only the HTTP server itself is replaced."""
    import httpx
    import uvicorn

    from vocab_builder.mobile.cli import main

    served = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **_: served.setdefault("app", app))
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "x" * 36)
    monkeypatch.setenv("VOCABBUILDER_SKIP_KEYRING", "1")
    monkeypatch.setenv("VOCABBUILDER_FORCE_SYNC_LOAD", "1")
    # main() writes both into os.environ; setting them here first lets
    # monkeypatch restore the originals afterwards.
    monkeypatch.setenv("VOCABBUILDER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("VOCABBUILDER_HISTORY_DIR", str(tmp_path / "history"))

    main(["--config-dir", str(tmp_path)])

    async def collections():
        transport = httpx.ASGITransport(app=served["app"])
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return (await client.get("/api/collections")).json()

    import asyncio

    payload = asyncio.run(collections())
    assert [item["language"] for item in payload["collections"]] == ["fr", "de", "en", "pl"]
    assert payload["default_language"] == "fr"
