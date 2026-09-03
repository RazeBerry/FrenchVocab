"""FastAPI application for the private mobile VocabBuilder surface."""

from __future__ import annotations

from importlib.resources import files
import os
from pathlib import Path
from typing import Any, Literal, Optional, Union

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr
from starlette.middleware.gzip import GZipMiddleware

from .catalog import MobileVocabCatalog
from .service import (
    AIUnavailableError,
    EntryNotFoundError,
    MobileServiceError,
    MobileVocabService,
    PrivateAccessError,
    SaveFailedError,
)


class RevalidatingStaticFiles(StaticFiles):
    """Serve assets that must revalidate instead of aging into staleness.

    With no directive a browser assigns heuristic freshness of roughly a tenth
    of the file's age, so a long-untouched asset can be trusted for days after a
    deployment. Revalidation costs one conditional request that the
    network-first service worker already makes, and answers 304 with no body.
    """

    def file_response(self, *args: Any, **kwargs: Any):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


class PreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    duplicate_action: Literal["reject", "merge", "variant"] = "reject"


class SaveRequest(BaseModel):
    token: str = Field(min_length=8, max_length=256)
    use_original: bool = False


class TranslationPreviewRequest(BaseModel):
    direction: Literal["auto", "eng_to_target", "target_to_eng"]
    text: str = Field(min_length=1, max_length=10000)


class TokenRequest(BaseModel):
    token: str = Field(min_length=8, max_length=256)


class PracticePromptRequest(BaseModel):
    mode: Literal["use_words", "reverse"]
    exclude_keys: list[str] = Field(default_factory=list, max_length=500)
    session_id: Optional[str] = Field(default=None, max_length=256)


class PracticeGradeRequest(TokenRequest):
    text: str = Field(min_length=1, max_length=10000)


class AnkiExportRequest(BaseModel):
    mode: Literal["incremental", "rebuild", "selected", "reconcile"]
    selected_words: list[str] = Field(default_factory=list, max_length=1000)
    include_mistakes: bool = False


class ProviderConfigureRequest(BaseModel):
    provider: Literal["gemini", "claude"]
    api_key: Optional[SecretStr] = None


def create_app(
    backend: Union[MobileVocabCatalog, MobileVocabService],
    *,
    allowed_tailscale_user: Optional[str] = None,
) -> FastAPI:
    catalog = (
        backend
        if isinstance(backend, MobileVocabCatalog)
        else MobileVocabCatalog(
            {backend.builder.language_code: backend},
            default_language=backend.builder.language_code,
        )
    )
    app = FastAPI(
        title="VocabBuilder Mobile",
        version="1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    # The glossary crosses a private transatlantic link. Compressing its JSON
    # and static shell avoids moving tens or hundreds of kilobytes of repeated
    # prose while leaving small responses alone.
    app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)
    expected_user = (
        allowed_tailscale_user
        if allowed_tailscale_user is not None
        else os.environ.get("VOCABBUILDER_ALLOWED_TAILSCALE_USER", "")
    ).strip().casefold()

    async def require_private_user(
        tailscale_user_login: Optional[str] = Header(
            default=None,
            alias="Tailscale-User-Login",
        ),
    ) -> None:
        if not expected_user:
            return
        if (tailscale_user_login or "").strip().casefold() != expected_user:
            raise PrivateAccessError(
                "This private vocabulary app is not available to this Tailscale user."
            )

    private = [Depends(require_private_user)]

    def resolve_service(language: Optional[str] = Query(default=None)) -> MobileVocabService:
        return catalog.service_for(language)

    @app.exception_handler(MobileServiceError)
    async def handle_service_error(_request: Request, exc: MobileServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, **exc.details}},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "That request was incomplete or too long.",
                }
            },
        )

    @app.exception_handler(ValueError)
    async def handle_value_error(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_operation", "message": str(exc)}},
        )

    @app.exception_handler(KeyError)
    async def handle_key_error(_request: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "workflow_not_found",
                    "message": str(exc.args[0]) if exc.args else "That workflow expired.",
                }
            },
        )

    @app.get("/api/collections", dependencies=private)
    def collections() -> dict[str, object]:
        return catalog.describe()

    @app.get("/api/status", dependencies=private)
    def status(
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        return service.status()

    @app.post("/api/preview", dependencies=private)
    def preview(
        payload: PreviewRequest,
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        return service.preview(
            payload.text,
            duplicate_action=payload.duplicate_action,
        ).as_json()

    @app.post("/api/save", dependencies=private)
    def save(
        payload: SaveRequest,
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        return service.save(payload.token, use_original=payload.use_original)

    @app.get("/api/recent", dependencies=private)
    def recent(
        limit: int = Query(default=8, ge=1, le=30),
        service: MobileVocabService = Depends(resolve_service),
    ) -> list[dict[str, Any]]:
        return service.recent(limit)

    @app.get("/api/search", dependencies=private)
    def search(
        q: str = Query(min_length=1, max_length=200),
        limit: int = Query(default=20, ge=1, le=50),
        service: MobileVocabService = Depends(resolve_service),
    ) -> list[dict[str, Any]]:
        return service.search(q, limit)

    @app.get("/api/library", dependencies=private)
    def library(
        q: str = Query(default="", max_length=200),
        word_type: str = Query(default="", max_length=100),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        return service.library.page(
            query=q,
            word_type=word_type,
            page=page,
            page_size=page_size,
        )

    @app.get("/api/library/index", dependencies=private)
    def library_index(
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        return service.library.index()

    @app.get("/api/library/search", dependencies=private)
    def library_search(
        q: str = Query(min_length=1, max_length=200),
        limit: int = Query(default=200, ge=1, le=200),
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        return service.library.search_index(q, limit=limit)

    @app.get("/api/library/entry", dependencies=private)
    def library_entry(
        word: str = Query(min_length=1, max_length=200),
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        entry = service.library.entry(word)
        if entry is None:
            raise EntryNotFoundError("That word is not in this collection.")
        return entry

    @app.get("/api/library/stats", dependencies=private)
    def library_stats(
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        return service.library.stats()

    @app.get("/api/library/random", dependencies=private)
    def random_entry(
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        entry = service.library.random_entry()
        if entry is None:
            raise ValueError("This collection has no vocabulary entries yet.")
        return entry

    @app.get("/api/translations", dependencies=private)
    def translations(
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        return service.translations.describe()

    @app.get("/api/translations/pairs", dependencies=private)
    def translation_pairs(
        direction: Literal["eng_to_target", "target_to_eng"],
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        return service.translations.pairs(direction, page=page, page_size=page_size)

    @app.post("/api/translations/preview", dependencies=private)
    def translation_preview(
        payload: TranslationPreviewRequest,
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        try:
            return service.translations.preview(payload.direction, payload.text)
        except RuntimeError as exc:
            raise AIUnavailableError(str(exc)) from exc

    @app.post("/api/translations/save", dependencies=private)
    def translation_save(
        payload: TokenRequest,
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        return service.translations.save(payload.token)

    @app.get("/api/practice", dependencies=private)
    def practice_status(
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        return service.practice.describe()

    @app.post("/api/practice/prompt", dependencies=private)
    def practice_prompt(
        payload: PracticePromptRequest,
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        return service.practice.create_prompt(
            payload.mode,
            exclude_keys=payload.exclude_keys,
            session_id=payload.session_id,
        )

    @app.post("/api/practice/grade", dependencies=private)
    def practice_grade(
        payload: PracticeGradeRequest,
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        try:
            return service.practice.grade(payload.token, payload.text)
        except RuntimeError as exc:
            raise AIUnavailableError(str(exc)) from exc

    @app.get("/api/anki", dependencies=private)
    def anki_status(
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        return service.anki.status()

    @app.post("/api/anki/export", dependencies=private)
    def anki_export(
        payload: AnkiExportRequest,
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        try:
            return service.anki.export(
                payload.mode,
                selected_words=payload.selected_words,
                include_mistakes=payload.include_mistakes,
            )
        except RuntimeError as exc:
            raise SaveFailedError(str(exc)) from exc

    @app.post("/api/anki/remove-stale", dependencies=private)
    def anki_remove_stale(
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        return service.anki.remove_stale_tracking()

    @app.get("/api/anki/download/{filename}", dependencies=private)
    def anki_download(
        filename: str,
        service: MobileVocabService = Depends(resolve_service),
    ) -> FileResponse:
        try:
            path = service.anki.resolve_download(filename)
        except FileNotFoundError as exc:
            raise KeyError("That Anki export is no longer available.") from exc
        return FileResponse(
            path,
            media_type="application/octet-stream",
            filename=path.name,
        )

    @app.get("/api/settings", dependencies=private)
    def settings(
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        return service.settings.describe()

    @app.post("/api/settings/provider", dependencies=private)
    def configure_provider(
        payload: ProviderConfigureRequest,
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        key = payload.api_key.get_secret_value() if payload.api_key else None
        result = service.settings.configure(payload.provider, key)
        if not result["ok"]:
            raise AIUnavailableError(str(result["message"]))
        return result

    @app.post("/api/settings/test", dependencies=private)
    def test_provider(
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        result = service.settings.test_connection()
        if not result["ok"]:
            raise AIUnavailableError(str(result["message"]))
        return result

    @app.get("/api/storage", dependencies=private)
    def storage(
        service: MobileVocabService = Depends(resolve_service),
    ) -> dict[str, Any]:
        return service.storage.describe()

    @app.get("/api/storage/download/{filename}", dependencies=private)
    def storage_download(
        filename: str,
        service: MobileVocabService = Depends(resolve_service),
    ) -> FileResponse:
        try:
            path = service.storage.resolve_download(filename)
        except FileNotFoundError as exc:
            raise KeyError("That data copy is no longer available.") from exc
        return FileResponse(
            path,
            media_type="application/octet-stream",
            filename=path.name,
        )

    static_root = files("vocab_builder.mobile").joinpath("static")
    static_path = Path(str(static_root))
    app.mount("/static", RevalidatingStaticFiles(directory=static_path), name="static")

    # Unversioned documents must revalidate. Without an explicit directive a
    # browser applies heuristic freshness (roughly a tenth of the file's age),
    # so a home-screen app can keep serving a months-old shell for days after a
    # deployment and never ask the server. Static assets use the same explicit
    # revalidation policy, so neither query-string versioning nor guesswork is
    # required.
    REVALIDATE = {"Cache-Control": "no-cache"}

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def manifest() -> FileResponse:
        return FileResponse(
            static_path / "manifest.webmanifest",
            media_type="application/manifest+json",
            headers=REVALIDATE,
        )

    @app.get("/service-worker.js", include_in_schema=False)
    async def service_worker() -> FileResponse:
        return FileResponse(
            static_path / "service-worker.js",
            media_type="application/javascript",
            headers=REVALIDATE,
        )

    @app.get("/", include_in_schema=False, dependencies=private)
    async def index() -> FileResponse:
        return FileResponse(static_path / "index.html", headers=REVALIDATE)

    return app
