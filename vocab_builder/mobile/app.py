"""FastAPI application for the private mobile VocabBuilder surface."""

from __future__ import annotations

from importlib.resources import files
import os
from pathlib import Path
from typing import Any, Optional, Union

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .catalog import MobileVocabCatalog
from .service import MobileServiceError, MobileVocabService, PrivateAccessError


class PreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class SaveRequest(BaseModel):
    token: str = Field(min_length=8, max_length=256)
    use_original: bool = False


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
        return service.preview(payload.text).as_json()

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

    static_root = files("vocab_builder.mobile").joinpath("static")
    static_path = Path(str(static_root))
    app.mount("/static", StaticFiles(directory=static_path), name="static")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def manifest() -> FileResponse:
        return FileResponse(
            static_path / "manifest.webmanifest",
            media_type="application/manifest+json",
        )

    @app.get("/service-worker.js", include_in_schema=False)
    async def service_worker() -> FileResponse:
        return FileResponse(
            static_path / "service-worker.js",
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/", include_in_schema=False, dependencies=private)
    async def index() -> FileResponse:
        return FileResponse(static_path / "index.html")

    return app
