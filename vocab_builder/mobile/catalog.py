"""Language collection registry for the private mobile application."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from .service import MobileServiceError, MobileVocabService


class UnsupportedMobileLanguageError(MobileServiceError):
    status_code = 404
    code = "unsupported_language"


class MobileVocabCatalog:
    """Own the independently mutable services exposed by one mobile app."""

    def __init__(
        self,
        services: Mapping[str, MobileVocabService],
        *,
        default_language: Optional[str] = None,
    ):
        if not services:
            raise ValueError("At least one mobile vocabulary service is required.")

        normalized: dict[str, MobileVocabService] = {}
        for language, service in services.items():
            code = language.strip().casefold()
            if not code:
                raise ValueError("Mobile language codes cannot be empty.")
            if code in normalized:
                raise ValueError(f"Duplicate mobile language code: {code}")
            if service.builder.language_code != code:
                raise ValueError(
                    f"Service registered as {code} manages "
                    f"{service.builder.language_code} instead."
                )
            normalized[code] = service

        requested_default = (default_language or next(iter(normalized))).strip().casefold()
        if requested_default not in normalized:
            raise ValueError(
                f"Default mobile language {requested_default!r} is not configured."
            )

        self._services = normalized
        self.default_language = requested_default

    def service_for(self, language: Optional[str] = None) -> MobileVocabService:
        code = (language or self.default_language).strip().casefold()
        try:
            return self._services[code]
        except KeyError as exc:
            available = ", ".join(self._services)
            raise UnsupportedMobileLanguageError(
                f"Language {code!r} is not available. Choose one of: {available}."
            ) from exc

    def describe(self) -> dict[str, object]:
        return {
            "default_language": self.default_language,
            "collections": [service.status() for service in self._services.values()],
        }


__all__ = ["MobileVocabCatalog", "UnsupportedMobileLanguageError"]
