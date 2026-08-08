from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import asyncio
import threading
import time

import httpx
import pytest

from vocab_builder.core.composition import CompositionFeedback, CompositionPrompt
from vocab_builder.core.composition_parser import ParsedCompositionResponse
from vocab_builder.core.composition_scheduler import ScheduledWord
from vocab_builder.core.translator import TranslationDraft, TranslationSaveResult
from vocab_builder.mobile.practice import MobilePractice
from vocab_builder.mobile.app import create_app
from vocab_builder.mobile.translations import MobileTranslations

from test_mobile_service import AI_RESPONSE, build_service


def test_capture_preview_and_receipt_survive_service_restart(tmp_path, monkeypatch):
    first = build_service(tmp_path, monkeypatch)
    preview = first.preview("chrysantheme")

    restarted = build_service(tmp_path, monkeypatch)
    saved = restarted.save(preview.token)
    restarted_again = build_service(tmp_path, monkeypatch)

    assert restarted_again.save(preview.token) == saved
    content = (tmp_path / "FrenchVocab.tex").read_text(encoding="utf-8")
    assert content.count(r"\entry{Chrysanthème}") == 1


def test_partial_capture_side_effects_are_repaired_without_second_primary_write(
    tmp_path,
    monkeypatch,
):
    service = build_service(tmp_path, monkeypatch)
    logger = service.builder.history_logger
    real_log = logger.log_vocab_entry
    monkeypatch.setattr(logger, "log_vocab_entry", lambda **_kwargs: False)

    preview = service.preview("chrysantheme")
    receipt = service.save(preview.token)

    assert receipt["sync_pending"] is True
    assert service.status()["sync_pending"] == 1
    monkeypatch.setattr(logger, "log_vocab_entry", real_log)

    repaired = service.status()
    assert repaired["sync_pending"] == 0
    assert logger.has_operation(preview.token, flow="vocab")
    content = (tmp_path / "FrenchVocab.tex").read_text(encoding="utf-8")
    assert content.count(r"\entry{Chrysanthème}") == 1


def test_crash_after_primary_write_reconstructs_receipt_without_duplicate(
    tmp_path,
    monkeypatch,
):
    service = build_service(tmp_path, monkeypatch)
    preview = service.preview("chrysantheme")
    real_commit = service._commit_transaction_primary

    def commit_then_crash(transaction):
        real_commit(transaction)
        raise RuntimeError("simulated process loss after primary write")

    monkeypatch.setattr(service, "_commit_transaction_primary", commit_then_crash)
    try:
        service.save(preview.token)
    except RuntimeError as exc:
        assert "simulated process loss" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("Fault injection should interrupt the first save")

    restarted = build_service(tmp_path, monkeypatch)
    receipt = restarted.save(preview.token)

    assert receipt["word"] == "chrysanthème"
    assert receipt["sync_pending"] is False
    content = (tmp_path / "FrenchVocab.tex").read_text(encoding="utf-8")
    assert content.count(r"\entry{Chrysanthème}") == 1


def test_crash_after_merge_replays_idempotently(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch)
    tokens = iter(("initial-token", "merge-token"))
    service._token_factory = lambda: next(tokens)
    service.save(service.preview("chrysantheme").token)
    service.builder.client.response = AI_RESPONSE.replace(
        "b. A flower associated with autumn in France.",
        "b. A crash-safe merged sense.",
    )
    preview = service.preview("chrysanthème", duplicate_action="merge")
    real_commit = service._commit_transaction_primary

    def merge_then_crash(transaction):
        real_commit(transaction)
        raise RuntimeError("simulated process loss after merge")

    monkeypatch.setattr(service, "_commit_transaction_primary", merge_then_crash)
    with pytest.raises(RuntimeError, match="process loss after merge"):
        service.save(preview.token)

    restarted = build_service(tmp_path, monkeypatch)
    receipt = restarted.save(preview.token)
    page = restarted.library.page(query="crash-safe", page_size=10)

    assert receipt["action"] == "merged"
    assert page["total"] == 1
    assert page["items"][0]["definitions"].count("A crash-safe merged sense.") == 1


def test_duplicate_merge_and_variant_are_explicit_and_non_destructive(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch)
    tokens = iter(("preview-token-one", "preview-token-two", "preview-token-three"))
    service._token_factory = lambda: next(tokens)
    service.save(service.preview("chrysantheme").token)

    service.builder.client.response = AI_RESPONSE.replace(
        "b. A flower associated with autumn in France.",
        "b. A newly recorded botanical sense.",
    )
    merged = service.save(
        service.preview("chrysanthème", duplicate_action="merge").token
    )
    variant = service.save(
        service.preview("chrysanthème", duplicate_action="variant").token
    )

    assert merged["action"] == "merged"
    assert variant["word"] == "chrysanthème - alt"
    page = service.library.page(query="botanical", page_size=20)
    assert page["total"] == 2
    assert {item["word"] for item in page["items"]} == {
        "Chrysanthème",
        "Chrysanthème - alt",
    }


def test_same_language_ai_work_is_serialized(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch)
    active = 0
    maximum = 0
    guard = threading.Lock()

    class MeasuringClient:
        def stream(self, _prompt):
            nonlocal active, maximum
            with guard:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.04)
            yield AI_RESPONSE
            with guard:
                active -= 1
            return {"usage": {}}

        def model_label(self):
            return "Measured"

    service.builder.client = MeasuringClient()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(service.preview, ("first", "second")))

    assert len(results) == 2
    assert maximum == 1


def test_sentence_preview_recommends_the_same_translation_route_as_cli(
    tmp_path,
    monkeypatch,
):
    service = build_service(tmp_path, monkeypatch)
    service.builder.client.response = AI_RESPONSE.replace(
        "Correctly Spelt Word: chrysanthème",
        "Correctly Spelt Word: Ceci est une phrase.",
    ).replace("Word Type: noun", "Word Type: sentence")

    preview = service.preview("Ceci est une phrase.")

    assert preview.route_recommended is True
    assert preview.as_json()["route_recommended"] is True


def test_storage_downloads_are_read_only_and_restricted_to_known_data(
    tmp_path,
    monkeypatch,
):
    service = build_service(tmp_path, monkeypatch)
    preview = service.preview("chrysantheme")
    service.save(preview.token)
    (tmp_path / "unrelated.txt").write_text("private", encoding="utf-8")

    listing = service.storage.describe()
    vocab = next(
        item for item in listing["current"] if item["filename"] == "FrenchVocab.tex"
    )

    assert service.storage.resolve_download(vocab["filename"]) == (
        tmp_path / "FrenchVocab.tex"
    )
    try:
        service.storage.resolve_download("unrelated.txt")
    except FileNotFoundError:
        pass
    else:  # pragma: no cover - assertion guard
        raise AssertionError("Unrelated files must not become browser-downloadable")


def test_mobile_api_exposes_each_cli_capability_without_leaking_credentials(
    tmp_path,
    monkeypatch,
):
    service = build_service(tmp_path, monkeypatch)
    service.save(service.preview("chrysantheme").token)
    app = create_app(service)

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            responses = {
                "library": await client.get("/api/library?q=flower"),
                "stats": await client.get("/api/library/stats"),
                "translations": await client.get("/api/translations"),
                "practice": await client.get("/api/practice"),
                "anki": await client.get("/api/anki"),
                "settings": await client.get("/api/settings"),
                "storage": await client.get("/api/storage"),
            }
            filename = responses["storage"].json()["current"][0]["filename"]
            responses["download"] = await client.get(
                f"/api/storage/download/{filename}"
            )
            return responses

    responses = asyncio.run(exercise())

    assert all(response.status_code == 200 for response in responses.values())
    assert responses["library"].json()["total"] == 1
    assert responses["practice"].json()["available"] is True
    assert responses["translations"].json()["available"] is True
    assert "api_key" not in responses["settings"].text.casefold()
    assert "credential" not in responses["settings"].text.casefold()
    assert responses["download"].content.startswith(b"\\documentclass")


def test_monolingual_status_disables_only_translation_navigation(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch, language="en")

    status = service.status()

    assert status["supports_translation"] is False
    assert status["supports_practice"] is True


@dataclass
class _TranslationResult:
    translation: str
    direction: str
    notes: str = ""


class _FakeTranslator:
    source_label = "English"
    target_label = "French"

    def __init__(self):
        self.pairs = {}
        self.save_calls = 0
        self.repair_calls = 0

    @property
    def entry_count(self):
        return len(self.pairs)

    def preview_translation(self, source, provided_translation=None):
        target = provided_translation or "bonjour"
        return TranslationDraft(
            source_text=source,
            target_text=target,
            normalized_key=source.casefold(),
            suspicious=False,
            dropped_fragment=None,
            existing_entry=None,
        )

    def save_translation(self, draft, *, operation_id=None):
        self.save_calls += 1
        self.pairs[draft.normalized_key] = {
            "source": draft.source_text,
            "target": draft.target_text,
        }
        return TranslationSaveResult(
            status="saved",
            source_text=draft.source_text,
            target_text=draft.target_text,
            existing_entry=None,
        )

    def repair_translation_history(self, _draft, *, operation_id=None):
        self.repair_calls += 1
        return bool(operation_id)


class _FakeAutoTranslator:
    def __init__(self, translator):
        self.translator = translator

    def preview_translation(self, _source):
        return _TranslationResult("bonjour", "english_to_french", "Detected English")

    def translator_for_direction(self, _direction):
        return self.translator

    @staticmethod
    def translation_is_suspicious(source, translation):
        return source.casefold() in translation.casefold()


def test_translation_preview_save_and_retry_share_one_idempotent_use_case():
    translator = _FakeTranslator()
    builder = SimpleNamespace(
        api_available=True,
        api_error_reason=None,
        eng_to_target_translator=translator,
        target_to_eng_translator=None,
        auto_translator=_FakeAutoTranslator(translator),
        try_restore_ai=lambda: True,
    )
    previews = {}
    tokens = iter(("translation-token",))
    mobile = MobileTranslations(
        builder,
        previews=previews,
        token_factory=lambda: next(tokens),
        persist=lambda: None,
        ai_lock=threading.Lock(),
        state_lock=threading.RLock(),
    )

    preview = mobile.preview("auto", "hello")
    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(executor.map(mobile.save, (preview["token"], preview["token"])))

    assert receipts[0] == receipts[1]
    assert translator.save_calls == 1
    assert translator.repair_calls == 1
    assert mobile.pairs("eng_to_target")["items"] == [
        {"source": "hello", "target": "bonjour"}
    ]


def test_competing_translation_does_not_acquire_this_requests_history():
    class ConflictingTranslator(_FakeTranslator):
        def save_translation(self, draft, *, operation_id=None):
            self.save_calls += 1
            return TranslationSaveResult(
                status="duplicate",
                source_text=draft.source_text,
                target_text="a different stored translation",
                existing_entry={
                    "source": draft.source_text,
                    "target": "a different stored translation",
                },
            )

    translator = ConflictingTranslator()
    builder = SimpleNamespace(
        api_available=True,
        api_error_reason=None,
        eng_to_target_translator=translator,
        target_to_eng_translator=None,
        auto_translator=None,
        try_restore_ai=lambda: True,
    )
    previews = {}
    mobile = MobileTranslations(
        builder,
        previews=previews,
        token_factory=lambda: "translation-token",
        persist=lambda: None,
        ai_lock=threading.Lock(),
        state_lock=threading.RLock(),
    )

    preview = mobile.preview("eng_to_target", "hello")
    receipt = mobile.save(preview["token"])

    assert receipt["status"] == "duplicate"
    assert receipt["target_text"] == "a different stored translation"
    assert receipt["history_pending"] is False
    assert translator.repair_calls == 0


class _FakePracticeLogger:
    def __init__(self):
        self.records = {}

    def has_attempt(self, attempt_id):
        return attempt_id in self.records

    def log_attempt(self, record):
        self.records[record["attempt_id"]] = record
        return True


class _FakeCoach:
    set_size = 3
    words_per_attempt = 1
    config = SimpleNamespace(use_words_label="Use words", reverse_label="Recall")

    def __init__(self):
        self.grade_calls = 0
        self.logger = _FakePracticeLogger()
        self.scheduler = SimpleNamespace(debt_count=lambda: 1, invalidate=lambda: None)

    def create_prompt(self, mode, exclude_keys):
        assert not exclude_keys
        return CompositionPrompt(
            mode=mode,
            words=(ScheduledWord("bonjour", "bonjour", "noun", "hello", 1),),
        )

    def grade_prompt(self, prompt, text, *, session_id, record_history):
        self.grade_calls += 1
        parsed = ParsedCompositionResponse(
            corrected_text=text,
            corrections=[],
            word_verdicts={"bonjour": "correct"},
            unknown_candidates=[],
            register="natural",
            parsing_warnings=[],
        )
        record = {"attempt_id": "attempt-one", "session_id": session_id}
        return CompositionFeedback(parsed, False, "attempt-one", record)


def test_practice_grade_retry_is_idempotent_and_history_is_durable():
    coach = _FakeCoach()
    builder = SimpleNamespace(
        enable_composition=True,
        get_composition_coach=lambda: coach,
    )
    attempts = {}
    mobile = MobilePractice(
        builder,
        attempts=attempts,
        token_factory=lambda: "practice-token",
        persist=lambda: None,
        ai_lock=threading.Lock(),
        state_lock=threading.RLock(),
    )
    prompt = mobile.create_prompt("use_words")

    with ThreadPoolExecutor(max_workers=2) as executor:
        feedback = list(
            executor.map(
                lambda _value: mobile.grade(prompt["token"], "Bonjour !"),
                range(2),
            )
        )

    assert feedback[0] == feedback[1]
    assert feedback[0]["history_pending"] is False
    assert coach.grade_calls == 1
    assert list(coach.logger.records) == ["attempt-one"]


def test_mobile_javascript_is_modular_and_every_module_is_precached():
    static = Path(__file__).parents[1] / "vocab_builder" / "mobile" / "static"
    worker = (static / "service-worker.js").read_text(encoding="utf-8")
    app = (static / "app.js").read_text(encoding="utf-8")

    for module in (
        "capture-view.js",
        "library-view.js",
        "translation-view.js",
        "practice-view.js",
        "tools-view.js",
    ):
        assert f'from "./{module}"' in app
        assert f'"/static/{module}"' in worker
    assert app.count("\n") < 250
    assert "views.translate = new TranslationView" in app
    assert "views.translation" not in app
    assert 'translateTab.hidden = !status.supports_translation' in app
