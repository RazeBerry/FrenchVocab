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

from vocab_builder.anki_exporter import AnkiExportEntry, AnkiExporter
from vocab_builder.core.llm_coordinator import LLMCoordinator
from vocab_builder.core.vocab import VocabBuilder
from vocab_builder.mobile.app import create_app
from vocab_builder.mobile.catalog import MobileVocabCatalog
from vocab_builder.models import WordEntry
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

MERGE_AI_RESPONSE = """Correctly Spelt Word: chrysanthème
Word Type: noun
Definitions:
a. A FLOWERING   PLANT in the daisy family.
b. A newly recorded botanical sense.
Examples:
1. ELLE  a posé un chrysanthème sur la table.
   [She placed a chrysanthemum on the table.]
2. Ce sens botanique est nouveau.
   [This botanical sense is new.]
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


def test_flexible_response_survives_mobile_save_reload_and_anki_export(
    tmp_path,
    monkeypatch,
):
    service = build_service(tmp_path, monkeypatch)
    service.builder.client.response = """Spelling Check: OK
Correctly Spelt Word: encombrants
Word Type: noun
Definitions:
a. Bulky household waste collected separately by a municipality.
b. Usage note: Usually used in the plural for discarded furniture and appliances.
Examples:
1. La mairie ramasse les encombrants mardi.
(The council collects bulky waste on Tuesday.)
2. Ce vieux canapé partira avec les encombrants.
(This old sofa will go out with the bulky-waste collection.)
"""

    preview = service.preview("encombrants")

    assert preview.word == "encombrants"
    assert preview.word_type == "noun"
    assert len(preview.definitions) == 2
    assert len(preview.examples) == 2
    assert preview.definitions[1].startswith("Usage note:")

    service.save(preview.token)
    service.builder._vocab_repo.load_existing_entries()
    stored = service.builder.word_entries["encombrants"]

    assert stored["definitions_list"] == preview.definitions
    assert stored["examples_list"] == preview.examples

    config = service.builder.language_config
    deck = AnkiExporter(config.anki.default_deck_name, config.anki).build_deck(
        [
            AnkiExportEntry(
                word=stored["word"],
                word_type=stored["type"],
                definitions=stored["definitions_list"],
                examples=stored["examples_list"],
            )
        ]
    )
    fields = deck.notes[0].fields
    assert "Bulky household waste" in fields[2]
    assert "Usage note:" in fields[2]
    assert "La mairie ramasse" in fields[3]
    assert "Ce vieux canapé" in fields[3]


def test_mobile_rejects_misaligned_response_instead_of_saving_it_silently(
    tmp_path,
    monkeypatch,
):
    service = build_service(tmp_path, monkeypatch)
    service.builder.client.response = """Correctly Spelt Word: dépanner
Word Type: verb
Definitions:
a. to help someone out of a practical difficulty
b. to repair a vehicle temporarily
Examples:
1. Tu peux me dépanner ce soir ?
(Can you help me out tonight?)
"""

    with pytest.raises(AIUnavailableError, match="one example per definition"):
        service.preview("dépanner")

    assert "dépanner" not in service.builder.word_entries
    assert service._previews == {}


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


def test_transient_provider_error_preserves_precise_mobile_feedback(
    tmp_path,
    monkeypatch,
):
    class FailingClient:
        def stream(self, _prompt):
            raise RuntimeError("503 UNAVAILABLE: reported high demand")
            yield ""  # pragma: no cover - keeps this a generator

        def model_label(self):
            return "Google Gemini (test)"

    reason = (
        "Google Gemini rejected the request with 503 UNAVAILABLE "
        "(reported high demand)."
    )
    service = build_service(tmp_path, monkeypatch)
    service.builder.client = FailingClient()
    monkeypatch.setattr(
        LLMCoordinator,
        "_classify_provider_error",
        staticmethod(lambda _provider, _exc: ("transient", reason)),
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
        "message": reason,
    }
    assert service.builder.api_available is True
    assert service.builder.api_error_reason is None


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


def test_merge_preview_contains_full_existing_entry_and_only_new_content(
    tmp_path,
    monkeypatch,
):
    service = build_service(tmp_path, monkeypatch)
    service._token_factory = iter(("initial-preview-token", "merge-preview-token")).__next__
    service.save(service.preview("chrysantheme").token)
    service.builder.client.response = MERGE_AI_RESPONSE

    preview = service.preview("chrysanthème", duplicate_action="merge")

    assert preview.existing_entry == {
        "word": "Chrysanthème",
        "word_type": "noun",
        "definitions": [
            "A flowering plant in the daisy family.",
            "A flower associated with autumn in France.",
        ],
        "examples": [
            {
                "source": "Elle a posé un chrysanthème sur la table.",
                "target": "She placed a chrysanthemum on the table.",
            },
            {
                "source": "Les chrysanthèmes fleurissent en automne.",
                "target": "Chrysanthemums bloom in autumn.",
            },
        ],
    }
    assert preview.new_definitions == ["A newly recorded botanical sense."]
    assert preview.new_examples == [
        ("Ce sens botanique est nouveau.", "This botanical sense is new.")
    ]


def test_empty_merge_is_byte_identical_and_returns_unchanged(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch)
    service._token_factory = iter(("initial-preview-token", "merge-preview-token")).__next__
    service.save(service.preview("chrysantheme").token)
    preview = service.preview("chrysanthème", duplicate_action="merge")
    latex_file = tmp_path / "FrenchVocab.tex"
    before = latex_file.read_bytes()

    receipt = service.save(preview.token)

    assert latex_file.read_bytes() == before
    assert receipt["action"] == "unchanged"
    assert receipt["added_definitions"] == 0
    assert receipt["added_examples"] == 0
    assert receipt["sync_pending"] is False
    assert preview.token not in service._transactions


def test_real_merge_receipt_reports_added_definition_and_example_counts(
    tmp_path,
    monkeypatch,
):
    service = build_service(tmp_path, monkeypatch)
    service._token_factory = iter(("initial-preview-token", "merge-preview-token")).__next__
    service.save(service.preview("chrysantheme").token)
    service.builder.client.response = MERGE_AI_RESPONSE

    receipt = service.save(
        service.preview("chrysanthème", duplicate_action="merge").token
    )

    assert receipt["action"] == "merged"
    assert receipt["added_definitions"] == 1
    assert receipt["added_examples"] == 1


def test_spell_corrected_duplicate_reuses_one_generation_as_merge_preview(
    tmp_path,
    monkeypatch,
):
    service = build_service(tmp_path, monkeypatch)
    service._token_factory = iter(("initial-preview-token", "merge-preview-token")).__next__
    service.save(service.preview("chrysantheme").token)
    calls_before = len(service.builder.client.prompts)

    preview = service.preview("krizantem")

    assert preview.duplicate_action == "merge"
    assert preview.existing_entry["word"] == "Chrysanthème"
    assert len(service.builder.client.prompts) == calls_before + 1


def test_variant_preview_name_matches_the_committed_variant(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch)
    service._token_factory = iter(("initial-preview-token", "variant-preview-token")).__next__
    service.save(service.preview("chrysantheme").token)

    preview = service.preview("chrysanthème", duplicate_action="variant")
    receipt = service.save(preview.token)

    assert preview.variant_word == "chrysanthème - alt"
    assert receipt["word"] == preview.variant_word


def test_duplicate_preview_fields_round_trip_through_state_store(
    tmp_path,
    monkeypatch,
):
    service = build_service(tmp_path, monkeypatch)
    service._token_factory = iter(("initial-preview-token", "variant-preview-token")).__next__
    service.save(service.preview("chrysantheme").token)
    service.builder.client.response = MERGE_AI_RESPONSE
    preview = service.preview("chrysanthème", duplicate_action="variant")

    restarted = build_service(tmp_path, monkeypatch)
    restored = restarted._previews[preview.token]

    assert restored == preview
    assert restored.as_json() == preview.as_json()


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


def get_api(app, path: str):
    """Issue one private GET against the ASGI app."""

    async def exercise_app():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)

    import asyncio

    return asyncio.run(exercise_app())


def seed_entries(service, entries: list[tuple[str, str, str]]) -> None:
    """Write entries straight to the collection, bypassing acquisition order."""
    report = service.builder.add_vocab_entries(
        [
            WordEntry(word=word, type=word_type, definitions=[gloss], examples=[])
            for word, word_type, gloss in entries
        ],
        on_duplicate="error",
    )
    assert report.count("added") == len(entries)


def ai_response_for(word: str, definition: str) -> str:
    return f"""Correctly Spelt Word: {word}
Word Type: noun
Definitions:
a. {definition}
Examples:
1. Voici {word} dans une phrase.
   [Here is {word} in a sentence.]
"""


def test_library_index_ships_slim_rows_sorted_by_the_collection_key(
    tmp_path,
    monkeypatch,
):
    """A letter rail needs the whole index, and the letters it can jump to.

    The rail's counts have to agree with the order the rows arrive in, so an
    accented headword files under its base letter instead of trailing the
    Latin block the way a raw code-point sort would leave it.
    """
    service = build_service(tmp_path, monkeypatch)
    seed_entries(
        service,
        [
            ("Zèbre", "noun", "A zebra."),
            ("Étourdissant", "adjective", "Stunning, dazzling."),
            ("Dot", "noun", "Dowry brought by a bride."),
        ],
    )
    app = create_app(service)

    response = get_api(app, "/api/library/index")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sort"] == "alpha"
    assert payload["total"] == 4  # the three seeded words and the sample entry
    assert payload["letters"] == {"A": 1, "D": 1, "E": 1, "Z": 1}
    assert [item["word"] for item in payload["items"]] == [
        "agaçante",
        "Dot",
        "Étourdissant",
        "Zèbre",
    ]
    assert payload["items"][1:] == [
        {"word": "Dot", "word_type": "noun", "gloss": "Dowry brought by a bride."},
        {
            "word": "Étourdissant",
            "word_type": "adjective",
            "gloss": "Stunning, dazzling.",
        },
        {"word": "Zèbre", "word_type": "noun", "gloss": "A zebra."},
    ]


def test_library_search_scans_rich_content_but_ships_only_finder_rows(
    tmp_path,
    monkeypatch,
):
    """Typing search must not move every matching definition and example.

    The server still searches those cold fields, then the existing entry route
    supplies them only if the reader opens one result.
    """
    service = build_service(tmp_path, monkeypatch)
    report = service.builder.add_vocab_entries(
        [
            WordEntry(
                word="Dot",
                type="noun",
                definitions=["A dowry.", "A historical legal sense."],
                examples=[("La dot fut versée.", "The hidden search phrase.")],
            )
        ],
        on_duplicate="error",
    )
    assert report.count("added") == 1
    app = create_app(service)

    response = get_api(app, "/api/library/search?q=hidden%20search&limit=200")

    assert response.status_code == 200
    assert response.json() == {
        "items": [{"word": "Dot", "word_type": "noun", "gloss": "A dowry."}],
        "total": 1,
    }
    detail = get_api(app, "/api/library/entry?word=Dot").json()
    assert detail["definitions"] == ["A dowry.", "A historical legal sense."]
    assert detail["examples"] == [
        {"source": "La dot fut versée.", "target": "The hidden search phrase."}
    ]


def test_library_index_added_sort_follows_the_anki_acquisition_order(
    tmp_path,
    monkeypatch,
):
    """The glossary and the deck must agree on what "newest" means.

    Acquisition order is the order the Anki manager already persists, so the
    index reuses it rather than re-deriving one from history. An entry that
    order has never seen cannot claim a position in it and follows the ordered
    words alphabetically.
    """
    service = build_service(tmp_path, monkeypatch)
    tokens = iter(("preview-token-one", "preview-token-two"))
    service._token_factory = lambda: next(tokens)
    for word, definition in (("dot", "Dowry."), ("zèbre", "A zebra.")):
        service.builder.client.response = ai_response_for(word, definition)
        service.save(service.preview(word).token)
    seed_entries(service, [("Étourdissant", "adjective", "Stunning.")])
    app = create_app(service)

    response = get_api(app, "/api/library/index?sort=added")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sort"] == "added"
    assert service.builder.get_anki_manager().entry_order == (
        "agaçante",
        "dot",
        "zèbre",
    )
    assert [item["word"] for item in payload["items"]] == [
        "Zèbre",
        "Dot",
        "agaçante",
        "Étourdissant",
    ]


def test_library_index_rejects_an_unknown_sort(tmp_path, monkeypatch):
    """An unrecognised order is a rejected request, never a quiet default."""
    service = build_service(tmp_path, monkeypatch)
    app = create_app(service)

    response = get_api(app, "/api/library/index?sort=oldest")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_library_entry_route_answers_with_one_full_entry_or_404(tmp_path, monkeypatch):
    """The row is a finder; opening it loads the record the slim index omits."""
    service = build_service(tmp_path, monkeypatch)
    service.save(service.preview("chrysantheme").token)
    app = create_app(service)

    found = get_api(app, "/api/library/entry?word=CHRYSANTHEME")
    missing = get_api(app, "/api/library/entry?word=introuvable")

    assert found.status_code == 200
    assert found.json()["word"] == "Chrysanthème"
    assert len(found.json()["definitions"]) == 2
    assert found.json()["examples"][0]["source"].startswith("Elle a posé")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "entry_not_found"


def test_recent_merge_records_count_what_the_merge_added(tmp_path, monkeypatch):
    """A merge that added two senses must not read like a new word.

    The counts come from the diff computed against reloaded disk state at save
    time, because after the write those senses are simply part of the entry.
    """
    service = build_service(tmp_path, monkeypatch)
    tokens = iter(("preview-token-one", "preview-token-two"))
    service._token_factory = lambda: next(tokens)
    service.save(service.preview("chrysantheme").token)
    service.builder.client.response = MERGE_AI_RESPONSE
    merged = service.save(
        service.preview("chrysanthème", duplicate_action="merge").token
    )
    app = create_app(service)

    response = get_api(app, "/api/recent")

    assert merged["action"] == "merged"
    assert response.status_code == 200
    merge_row, new_row = response.json()
    assert merge_row["action"] == "merge"
    assert merge_row["added"] == {"definitions": 1, "examples": 1}
    assert new_row["action"] == "new"
    assert "added" not in new_row


def test_journal_written_before_merge_metadata_existed_still_replays(
    tmp_path,
    monkeypatch,
):
    """The request journal outlives a deploy, so replay must read older records.

    A transaction journaled by the previous release has its primary write on
    disk and its history step still pending, but no `history_metadata`. The
    repair loop swallows exceptions, so demanding that field would not crash:
    it would leave the entry permanently pending and never append its history.
    """
    service = build_service(tmp_path, monkeypatch)
    logger = service.builder.history_logger
    real_log = logger.log_vocab_entry
    monkeypatch.setattr(logger, "log_vocab_entry", lambda **_kwargs: False)
    preview = service.preview("chrysantheme")
    receipt = service.save(preview.token)
    monkeypatch.setattr(logger, "log_vocab_entry", real_log)

    state_path = service._state_store.path
    journal = json.loads(state_path.read_text(encoding="utf-8"))
    for transaction in journal["transactions"].values():
        del transaction["history_metadata"]
    state_path.write_text(json.dumps(journal), encoding="utf-8")

    restarted = build_service(tmp_path, monkeypatch)

    assert receipt["sync_pending"] is True
    assert "history_metadata" not in journal["transactions"][preview.token]
    assert restarted.status()["sync_pending"] == 0
    assert logger.has_operation(preview.token, flow="vocab")
    replayed = restarted.save(preview.token)
    assert replayed["word"] == "chrysanthème"
    assert replayed["sync_pending"] is False
    content = (tmp_path / "FrenchVocab.tex").read_text(encoding="utf-8")
    assert content.count(r"\entry{Chrysanthème}") == 1
