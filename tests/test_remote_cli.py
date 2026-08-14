from __future__ import annotations

from io import BytesIO
import json
from urllib.error import HTTPError

import pytest
from vocab_builder.cli.remote_client import (
    RemoteAPI,
    RemoteAPIError,
    RemoteCLI,
    resolve_base_url,
)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_remote_api_adds_language_and_sends_json():
    calls = []

    def opener(request, *, timeout):
        calls.append((request, timeout))
        return _Response({"ok": True})

    api = RemoteAPI("https://private.example", opener=opener)
    api.language = "fr"

    assert api.request(
        "/api/preview?mode=full",
        method="POST",
        payload={"text": "chrysanthème"},
        timeout=12,
    ) == {"ok": True}

    request, timeout = calls[0]
    assert request.full_url == "https://private.example/api/preview?mode=full&language=fr"
    assert request.method == "POST"
    assert json.loads(request.data.decode("utf-8")) == {"text": "chrysanthème"}
    assert timeout == 12


def test_remote_api_preserves_structured_errors():
    body = {
        "error": {
            "code": "duplicate_entry",
            "message": "Already collected.",
            "existing_entry": {"word": "mot"},
        }
    }

    def opener(_request, *, timeout):  # noqa: ARG001
        raise HTTPError(
            "https://private.example/api/preview",
            409,
            "Conflict",
            {},
            BytesIO(json.dumps(body).encode("utf-8")),
        )

    with pytest.raises(RemoteAPIError) as caught:
        RemoteAPI("https://private.example", opener=opener).request("/api/preview")

    assert caught.value.code == "duplicate_entry"
    assert caught.value.details["existing_entry"] == {"word": "mot"}


def test_resolve_base_url_uses_tailscale_dns_name():
    status = {
        "MagicDNSSuffix": "tail.example.ts.net",
        "Peer": {
            "peer": {
                "HostName": "vocabbuilder-mobile",
                "DNSName": "vocabbuilder-mobile.tail.example.ts.net.",
            }
        },
    }

    assert resolve_base_url(
        "vocabbuilder-mobile", status_loader=lambda: status
    ) == "https://vocabbuilder-mobile.tail.example.ts.net"


def test_remote_cli_uses_api_catalog_without_constructing_server_builder(monkeypatch):
    calls = []

    class API:
        language = None

        def request(self, path, **_kwargs):
            calls.append(path)
            if path == "/api/collections":
                return {
                    "default_language": "fr",
                    "collections": [
                        {
                            "language": "fr",
                            "language_name": "French",
                            "provider": "Gemini",
                            "entry_count": 12,
                        }
                    ],
                }
            if path == "/api/status":
                return {
                    "language": "fr",
                    "language_name": "French",
                    "entry_count": 12,
                    "ai_available": True,
                    "supports_translation": True,
                    "supports_practice": True,
                }
            raise AssertionError(path)

    monkeypatch.setattr(
        "vocab_builder.cli.remote_client.interactive_select",
        lambda *_args, **_kwargs: "exit",
    )
    monkeypatch.setattr(RemoteCLI, "_welcome", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(RemoteCLI, "_goodbye", lambda *_args, **_kwargs: None)
    client = RemoteCLI(
        API(),  # type: ignore[arg-type]
        requested_language="fr",
    )

    client.run()

    assert calls == ["/api/collections", "/api/status"]
    assert client.api.language == "fr"
