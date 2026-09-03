"""Static assets must revalidate rather than age into heuristic freshness.

Kept separate from `test_mobile_service.py` so this caching contract is legible
on its own: the asset URLs carry no version query, so correctness depends
entirely on the response headers.
"""

from __future__ import annotations

import asyncio
import re

import httpx

from vocab_builder.core.vocab import VocabBuilder
from vocab_builder.mobile.app import create_app
from vocab_builder.mobile.service import MobileVocabService


class _SilentClient:
    def stream(self, prompt: str):
        yield ""
        return {"usage": {}}

    def model_label(self) -> str:
        return "Test provider"


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("VOCABBUILDER_FORCE_SYNC_LOAD", "1")
    monkeypatch.setenv("VOCABBUILDER_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("VOCABBUILDER_HISTORY_DIR", str(tmp_path / "history"))
    builder = VocabBuilder(
        latex_file=str(tmp_path / "FrenchVocab.tex"),
        provider="gemini",
        language="fr",
        client=_SilentClient(),
        interactive=False,
    )
    return create_app(MobileVocabService(builder))


def _get(app, path: str) -> httpx.Response:
    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)

    return asyncio.run(exercise())


def test_static_assets_revalidate(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)

    for path in (
        "/static/styles.css",
        "/static/app.js",
        "/static/api.js",
        "/static/capture-view.js",
        "/static/library-view.js",
        "/static/translation-view.js",
        "/static/practice-view.js",
        "/static/tools-view.js",
        "/static/icon.svg",
    ):
        response = _get(app, path)
        assert response.status_code == 200, path
        assert response.headers.get("cache-control") == "no-cache", path


def test_asset_urls_carry_no_version_query(tmp_path, monkeypatch):
    """The headers make versioning unnecessary; a stale ?v= would be a trap."""
    app = _app(tmp_path, monkeypatch)

    index = _get(app, "/").text
    service_worker = _get(app, "/service-worker.js").text

    assert "styles.css?v=" not in index
    assert "app.js?v=" not in index
    assert "?v=" not in service_worker


def test_static_assets_still_answer_conditional_requests(tmp_path, monkeypatch):
    """no-cache means revalidate, not re-download: the ETag must still 304."""
    app = _app(tmp_path, monkeypatch)

    first = _get(app, "/static/styles.css")
    etag = first.headers.get("etag")
    assert etag

    async def conditional():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/static/styles.css", headers={"If-None-Match": etag})

    assert asyncio.run(conditional()).status_code == 304


def test_production_navigation_exposes_capture_translation_and_library(tmp_path, monkeypatch):
    index = _get(_app(tmp_path, monkeypatch), "/").text
    matches = re.findall(
        r'<button class="tab[^\"]*"([^>]*)data-tab="([^\"]+)"([^>]*)>',
        index,
    )
    tabs = {name: before + after for before, name, after in matches}

    assert "hidden" not in tabs["capture"]
    assert "hidden" not in tabs["translate"]
    assert "hidden" not in tabs["library"]
    assert "hidden" in tabs["practice"]
    assert "hidden" in tabs["tools"]
    # The ledger also keeps its contextual route into the same collection.
    assert not re.search(r'data-go="library"[^>]*hidden', index)
