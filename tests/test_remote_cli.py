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


class _CaptureAPI:
    """A private API that holds "Ronger" and answers one merge look-up."""

    language = "fr"

    def __init__(self, merge_preview):
        self.merge_preview = merge_preview
        self.calls = []

    def request(self, path, *, method="GET", payload=None, **_kwargs):
        self.calls.append((path, payload))
        if path == "/api/preview" and payload["duplicate_action"] == "reject":
            raise RemoteAPIError(
                "Ronger is already in your vocabulary.",
                code="duplicate_entry",
                details={
                    "existing_entry": {"word": "Ronger", "word_type": "verb", "definitions": ["To gnaw."], "examples": []},
                    "corrected_from": "ronjer",
                },
            )
        if path == "/api/preview":
            return self.merge_preview
        if path == "/api/save":
            return {"word": "Ronger", "action": "merged", "added_definitions": 2, "added_examples": 1}
        raise AssertionError(path)


class _RecordingConsole:
    def __init__(self):
        self.lines = []

    def print(self, *objects, **_kwargs):
        self.lines.append(" ".join(str(item) for item in objects))

    def status(self, *_args, **_kwargs):
        from contextlib import nullcontext

        return nullcontext()

    def export_text(self):
        return "\n".join(self.lines)


def _capture(monkeypatch, api, answers):
    menus = []

    def select(_console, title, options, *_args, **_kwargs):
        menus.append((title, options))
        return answers[title]

    monkeypatch.setattr("vocab_builder.cli.remote_client.interactive_select", select)
    client = RemoteCLI(api, console=_RecordingConsole())  # type: ignore[arg-type]
    client.status = {"language_name": "French"}
    monkeypatch.setattr(client, "_prompt", lambda _prompt: "ronjer")
    # Entry panels need the real Rich tables the suite stubs out.
    monkeypatch.setattr(client, "_show_entry", lambda *_args, **_kwargs: None)
    client._capture()
    return client.console.export_text(), menus


def test_a_corrected_duplicate_merges_into_the_held_headword_and_counts_both_kinds(monkeypatch):
    api = _CaptureAPI({
        "token": "t",
        "word": "Ronger",
        "word_type": "verb",
        "definitions": ["To erode.", "To torment."],
        "examples": [],
        "duplicate_action": "merge",
        "new_definitions": ["To erode.", "To torment."],
        "new_examples": [["L'eau ronge la pierre.", "Water eats away the stone."]],
    })

    output, menus = _capture(monkeypatch, api, {"Existing Entry": "merge", "Confirm Entry": "save"})

    assert "Corrected to Ronger, which you already have." in output
    assert api.calls[1] == ("/api/preview", {"text": "Ronger", "duplicate_action": "merge"})
    assert menus[1][1][0] == ("save", "Add 2 senses, 1 example")
    assert "Ronger gained 2 senses and 1 example." in output


def test_a_merge_that_finds_nothing_missing_offers_no_save(monkeypatch):
    api = _CaptureAPI({
        "token": "t",
        "word": "Ronger",
        "word_type": "verb",
        "definitions": [],
        "examples": [],
        "duplicate_action": "merge",
        "new_definitions": [],
        "new_examples": [],
    })

    output, menus = _capture(monkeypatch, api, {"Existing Entry": "merge"})

    assert "Nothing new: the model found no sense your entry lacks." in output
    assert [title for title, _ in menus] == ["Existing Entry"]
    assert all(path != "/api/save" for path, _ in api.calls)
