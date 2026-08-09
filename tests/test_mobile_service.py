from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import importlib
from importlib.resources import files
import json
import re
import sys
import threading
from types import SimpleNamespace

import httpx
import pytest
from rich.console import Console

from vocab_builder.core.llm_coordinator import LLMCoordinator
from vocab_builder.core.vocab import VocabBuilder
from vocab_builder.mobile.app import create_app
from vocab_builder.mobile.catalog import MobileVocabCatalog
from vocab_builder.mobile.service import (
    AIUnavailableError,
    DuplicateEntryError,
    MobileVocabService,
)
from vocab_builder.ui_helper import NonInteractiveError, UIHelper


AI_RESPONSE = """Correctly Spelt Word: chrysanthème
Word Type: noun
Definitions:
a. A flowering plant in the daisy family.
b. A flower associated with autumn in France.
Examples:
1. Elle a posé un chrysanthème sur la table.
   [She placed a chrysanthemum on the table.]
2. Les chrysanthèmes fleurissent en automne.
   [Chrysanthemums bloom in autumn.]
"""


class FakeClient:
    def __init__(self, response: str = AI_RESPONSE):
        self.response = response
        self.prompts: list[str] = []

    def stream(self, prompt: str, **_kwargs):
        self.prompts.append(prompt)
        yield self.response
        return {"usage": {"prompt_tokens": 1, "output_tokens": 1, "total_tokens": 2}}

    def model_label(self) -> str:
        return "Test provider (test-model-1)"

    def model_name(self) -> str:
        return "test-model-1"


def build_service(
    tmp_path,
    monkeypatch,
    *,
    language: str = "fr",
    ttl: timedelta = timedelta(minutes=20),
):
    monkeypatch.setenv("VOCABBUILDER_FORCE_SYNC_LOAD", "1")
    monkeypatch.setenv("VOCABBUILDER_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("VOCABBUILDER_HISTORY_DIR", str(tmp_path / "history"))
    builder = VocabBuilder(
        latex_file=str(
            tmp_path
            / {
                "fr": "FrenchVocab.tex",
                "de": "GermanVocab.tex",
                "en": "EnglishVocab.tex",
            }[language]
        ),
        provider="gemini",
        language=language,
        client=FakeClient(),
        interactive=False,
    )
    return MobileVocabService(builder, preview_ttl=ttl, token_factory=lambda: "preview-token-123")


def test_preview_and_save_reuse_existing_workflow(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch)

    preview = service.preview("  chrysantheme  ")

    assert preview.original_input == "chrysantheme"
    assert preview.language == "fr"
    assert preview.word == "chrysanthème"
    assert preview.word_type == "noun"
    assert len(preview.definitions) == 2
    assert preview.examples[0][0].startswith("Elle a posé")

    saved = service.save(preview.token)
    content = (tmp_path / "FrenchVocab.tex").read_text(encoding="utf-8")

    assert saved["word"] == "chrysanthème"
    assert re.search(r"\\entry\{Chrysanthème\}\{noun\}", content)
    assert service.search("flower")[0]["word"] == "Chrysanthème"
    assert service.recent()[0]["word"] == "Chrysanthème"


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("interactive_menu", ("Choose", [("one", "One")], "Select one")),
        ("prompt", ("Type something",)),
        ("confirm", ("Continue?",)),
    ],
)
def test_noninteractive_ui_backstop_rejects_prompts(method_name, args):
    ui = UIHelper(Console(), interactive=False)

    with pytest.raises(NonInteractiveError, match=rf"{method_name}.*no console"):
        getattr(ui, method_name)(*args)


def test_classified_provider_error_is_503_without_reading_stdin(
    tmp_path,
    monkeypatch,
):
    class FailingClient:
        def stream(self, _prompt):
            raise RuntimeError("quota exceeded")
            yield ""  # pragma: no cover - keeps this a generator

        def model_label(self):
            return "Test provider"

    class ExplodingStdin:
        def isatty(self):
            return True

        def read(self, *_args, **_kwargs):
            raise AssertionError("headless request attempted to read stdin")

        readline = read

        def fileno(self):
            raise AssertionError("headless request attempted to inspect stdin")

    service = build_service(tmp_path, monkeypatch)
    service.builder.client = FailingClient()
    monkeypatch.setattr(sys, "stdin", ExplodingStdin())
    monkeypatch.setattr(
        LLMCoordinator,
        "_classify_provider_error",
        staticmethod(lambda _provider, _exc: ("quota", "Provider quota is exhausted.")),
    )
    app = create_app(service)

    async def exercise_app():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/api/preview", json={"text": "chrysantheme"})

    import asyncio

    response = asyncio.run(exercise_app())
    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "ai_unavailable",
        "message": "Provider quota is exhausted.",
    }


def test_inflight_preview_does_not_block_same_service_status(tmp_path, monkeypatch):
    started = threading.Event()
    release = threading.Event()

    class EventGatedClient(FakeClient):
        def stream(self, prompt):
            self.prompts.append(prompt)
            started.set()
            if not release.wait(timeout=2):
                raise TimeoutError("test provider gate was not released")
            yield self.response
            return {"usage": {"prompt_tokens": 1, "output_tokens": 1, "total_tokens": 2}}

    service = build_service(tmp_path, monkeypatch)
    service.builder.client = EventGatedClient()
    executor = ThreadPoolExecutor(max_workers=2)
    preview_future = executor.submit(service.preview, "chrysantheme")
    try:
        assert started.wait(timeout=1)
        status_future = executor.submit(service.status)
        status = status_future.result(timeout=0.25)
        assert status["language"] == "fr"
        assert not preview_future.done()
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)

    assert preview_future.result(timeout=0).word == "chrysanthème"


def test_degraded_preview_silently_restores_provider(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch)
    coordinator = service.builder._llm
    coordinator._enter_degraded_mode("Temporary provider failure.")
    resolution = SimpleNamespace(
        metadata=coordinator.provider_metadata,
        api_key="resolved-test-key",
    )
    resolve_calls = []
    create_calls = []
    monkeypatch.setattr(
        coordinator._provider_manager,
        "resolve_provider_silently",
        lambda metadata: resolve_calls.append(metadata) or resolution,
    )

    def create_client(provider, api_key=None):
        create_calls.append((provider, api_key))
        return FakeClient()

    # Other tests deliberately reload ``llm_client`` while exercising optional
    # SDK imports. Patch the class currently owned by the module, not a stale
    # class imported during collection.
    current_llm_client = importlib.import_module("vocab_builder.llm_client")
    monkeypatch.setattr(current_llm_client.ProviderFactory, "create", create_client)

    preview = service.preview("chrysantheme")

    assert preview.word == "chrysanthème"
    assert len(resolve_calls) == 1
    assert create_calls == [("gemini", "resolved-test-key")]
    assert service.builder.api_available is True


def test_silent_provider_recovery_obeys_cooldown(tmp_path, monkeypatch):
    monkeypatch.setenv("VOCABBUILDER_PROVIDER_RETRY_COOLDOWN", "30")
    service = build_service(tmp_path, monkeypatch)
    coordinator = service.builder._llm
    coordinator._enter_degraded_mode("Keep this diagnostic.")
    resolve_calls = []
    monkeypatch.setattr(
        coordinator._provider_manager,
        "resolve_provider_silently",
        lambda metadata: resolve_calls.append(metadata) or None,
    )

    with pytest.raises(AIUnavailableError, match="Keep this diagnostic"):
        service.preview("chrysantheme")
    with pytest.raises(AIUnavailableError, match="Keep this diagnostic"):
        service.preview("chrysantheme")

    assert len(resolve_calls) == 1


def test_phone_saves_persist_acquisition_order_without_history(tmp_path, monkeypatch):
    monkeypatch.setenv("VOCABBUILDER_HISTORY_DISABLED", "1")
    service = build_service(tmp_path, monkeypatch)
    tokens = iter(("preview-token-alpha", "preview-token-beta"))
    service._token_factory = lambda: next(tokens)

    def response_for(word):
        return f"""Correctly Spelt Word: {word}
Word Type: noun
Definitions:
a. Definition of {word}.
Examples:
1. Example with {word}.
   [Example explanation.]
"""

    service.builder.client.response = response_for("alpha")
    service.save(service.preview("alpha").token)
    service.builder.client.response = response_for("beta")
    service.save(service.preview("beta").token)

    payload = json.loads(service.builder.exported_words_file.read_text(encoding="utf-8"))
    assert payload["entry_order"][-2:] == ["alpha", "beta"]
    assert service.builder.history_logger.enabled is False


def test_duplicate_is_rejected_before_ai_query(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch)
    service.save(service.preview("chrysantheme").token)
    prompt_count = len(service.builder.client.prompts)

    try:
        service.preview("chrysanthème")
    except DuplicateEntryError as exc:
        assert exc.details["existing_word"] == "Chrysanthème"
    else:  # pragma: no cover - assertion guard
        raise AssertionError("Expected duplicate error")

    assert len(service.builder.client.prompts) == prompt_count


def test_save_retry_returns_the_original_receipt_without_a_second_write(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch)
    preview = service.preview("chrysantheme")
    first = service.save(preview.token)
    second = service.save(preview.token)

    assert second == first
    content = (tmp_path / "FrenchVocab.tex").read_text(encoding="utf-8")
    assert content.count(r"\entry{Chrysanthème}") == 1


def test_two_sessions_cannot_commit_the_same_word(tmp_path, monkeypatch):
    first = build_service(tmp_path, monkeypatch)
    second = build_service(tmp_path, monkeypatch)
    first_preview = first.preview("chrysantheme")
    second_preview = second.preview("chrysantheme")

    first.save(first_preview.token)

    with pytest.raises(DuplicateEntryError):
        second.save(second_preview.token)

    content = (tmp_path / "FrenchVocab.tex").read_text(encoding="utf-8")
    assert content.count(r"\entry{Chrysanthème}") == 1


def test_sentences_do_not_enter_the_spelling_correction_branch(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch)
    sentence = "Ceci est une phrase."

    preview = service.preview(sentence)

    assert preview.input_type == "sentence"
    assert preview.word == sentence
    assert preview.spelling_suggestion is None


def test_tailscale_identity_header_can_be_required(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch)
    app = create_app(service, allowed_tailscale_user="reader@example.com")

    async def exercise_app():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            denied = await client.get("/api/status")
            allowed = await client.get(
                "/api/status",
                headers={"Tailscale-User-Login": "reader@example.com"},
            )
            preview = await client.post(
                "/api/preview",
                headers={"Tailscale-User-Login": "reader@example.com"},
                json={"text": "chrysantheme"},
            )
        return denied, allowed, preview

    import asyncio

    denied, allowed, preview = asyncio.run(exercise_app())
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "private_access_denied"
    assert allowed.status_code == 200
    assert preview.status_code == 200
    assert preview.json()["word"] == "chrysanthème"


def test_unversioned_documents_must_revalidate(tmp_path, monkeypatch):
    """A home-screen app should never keep a stale shell after a deployment.

    Without an explicit directive these responses fall back to heuristic
    freshness, which grows with the file's age, so an installed app can serve
    an old build for days without contacting the server.
    """
    service = build_service(tmp_path, monkeypatch)
    app = create_app(service, allowed_tailscale_user="reader@example.com")
    identity = {"Tailscale-User-Login": "reader@example.com"}

    async def exercise_app():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            index = await client.get("/", headers=identity)
            worker = await client.get("/service-worker.js")
            manifest = await client.get("/manifest.webmanifest")
        return index, worker, manifest

    import asyncio

    index, worker, manifest = asyncio.run(exercise_app())
    for response in (index, worker, manifest):
        assert response.status_code == 200
        assert response.headers.get("cache-control") == "no-cache"


def test_catalog_routes_preview_tokens_and_state_by_language(tmp_path, monkeypatch):
    french = build_service(tmp_path / "fr", monkeypatch, language="fr")
    german = build_service(tmp_path / "de", monkeypatch, language="de")
    catalog = MobileVocabCatalog(
        {"fr": french, "de": german},
        default_language="fr",
    )
    app = create_app(catalog, allowed_tailscale_user="reader@example.com")
    headers = {"Tailscale-User-Login": "reader@example.com"}

    async def exercise_app():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            collections = await client.get("/api/collections", headers=headers)
            default_status = await client.get("/api/status", headers=headers)
            german_status = await client.get(
                "/api/status?language=de",
                headers=headers,
            )
            preview = await client.post(
                "/api/preview?language=fr",
                headers=headers,
                json={"text": "chrysantheme"},
            )
            wrong_collection = await client.post(
                "/api/save?language=de",
                headers=headers,
                json={"token": preview.json()["token"]},
            )
            saved = await client.post(
                "/api/save?language=fr",
                headers=headers,
                json={"token": preview.json()["token"]},
            )
            unsupported = await client.get(
                "/api/status?language=es",
                headers=headers,
            )
        return (
            collections,
            default_status,
            german_status,
            preview,
            wrong_collection,
            saved,
            unsupported,
        )

    import asyncio

    responses = asyncio.run(exercise_app())
    collections, default_status, german_status, preview, wrong, saved, unsupported = responses
    assert collections.status_code == 200
    assert collections.json()["default_language"] == "fr"
    assert [item["language"] for item in collections.json()["collections"]] == ["fr", "de"]
    assert default_status.json()["language"] == "fr"
    assert default_status.json()["supports_translation"] is True
    assert german_status.json()["language"] == "de"
    assert german_status.json()["data_file"] == "GermanVocab.tex"
    assert preview.json()["language"] == "fr"
    assert wrong.status_code == 404
    assert wrong.json()["error"]["code"] == "preview_not_found"
    assert saved.status_code == 200
    assert unsupported.status_code == 404
    assert unsupported.json()["error"]["code"] == "unsupported_language"


def test_blocking_previews_run_in_worker_threads_per_language():
    import asyncio
    import threading
    from types import SimpleNamespace

    rendezvous = threading.Barrier(2)

    class PreviewResult:
        def __init__(self, language):
            self.language = language

        def as_json(self):
            return {"language": self.language}

    class ConcurrentService:
        def __init__(self, language):
            self.builder = SimpleNamespace(language_code=language)
            self.language = language

        def preview(self, _text, **_kwargs):
            rendezvous.wait(timeout=2)
            return PreviewResult(self.language)

        def status(self):
            return {"language": self.language}

        def save(self, *_args, **_kwargs):
            return {}

        def recent(self, _limit):
            return []

        def search(self, _query, _limit):
            return []

    app = create_app(
        MobileVocabCatalog(
            {
                "fr": ConcurrentService("fr"),
                "de": ConcurrentService("de"),
            },
            default_language="fr",
        )
    )

    async def exercise_app():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await asyncio.gather(
                client.post("/api/preview?language=fr", json={"text": "one"}),
                client.post("/api/preview?language=de", json={"text": "two"}),
            )

    responses = asyncio.run(exercise_app())
    assert [response.status_code for response in responses] == [200, 200]


def test_service_worker_precaches_the_unversioned_shell_assets():
    """Freshness comes from Cache-Control, not from a hand-maintained ?v=.

    Every asset under /static is served with `no-cache`, so a version query
    would add nothing and a stale one would silently pin the old file. The
    shell cache name is stable for the same reason: the activate handler drops
    every other cache and the network-first fetch handler overwrites entries.
    """
    static = files("vocab_builder.mobile").joinpath("static")
    html = static.joinpath("index.html").read_text(encoding="utf-8")
    app_js = static.joinpath("app.js").read_text(encoding="utf-8")
    worker = static.joinpath("service-worker.js").read_text(encoding="utf-8")

    shell_assets = set(re.findall(r'/(static/(?:app\.js|styles\.css))\b', html))
    assert shell_assets == {"static/app.js", "static/styles.css"}
    assert not re.search(r'static/(?:app\.js|styles\.css)\?v=', html)
    assert not re.search(r"\?v=", worker)
    assert all(f'"/{asset}"' in worker for asset in shell_assets)
    assert re.search(r'const SHELL_CACHE = "vocabbuilder-shell";', worker)

    assert 'document.addEventListener("visibilitychange"' in app_js
    assert "views.capture.refresh()" in app_js
    for module in (
        "api.js",
        "ui.js",
        "entry-list.js",
        "capture-view.js",
        "library-view.js",
        "translation-view.js",
        "practice-view.js",
        "tools-view.js",
    ):
        assert f'"/static/{module}"' in worker
