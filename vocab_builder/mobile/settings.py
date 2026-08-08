"""Private, non-interactive provider and file-location settings."""

from __future__ import annotations

import threading
from typing import Any


class MobileSettings:
    def __init__(self, builder: Any, *, ai_lock: threading.Lock):
        self.builder = builder
        self._ai_lock = ai_lock

    def describe(self) -> dict[str, Any]:
        settings = self.builder.provider_settings()
        settings["files"] = {
            "vocabulary": self.builder.latex_file.name,
            "english_to_target": (
                self.builder.eng_to_target_latex_file.name
                if self.builder.eng_to_target_latex_file
                else None
            ),
            "target_to_english": (
                self.builder.target_to_eng_latex_file.name
                if self.builder.target_to_eng_latex_file
                else None
            ),
            "anki_tracking": self.builder.exported_words_file.name,
            "history_enabled": bool(
                self.builder.history_logger and self.builder.history_logger.enabled
            ),
        }
        return settings

    def configure(self, provider: str, api_key: str | None = None) -> dict[str, Any]:
        with self._ai_lock:
            ok, message = self.builder.configure_provider_noninteractive(
                provider,
                api_key,
            )
        return {"ok": ok, "message": message, **self.describe()}

    def test_connection(self) -> dict[str, Any]:
        with self._ai_lock:
            ok, message = self.builder.test_provider_connection()
        return {"ok": ok, "message": message, **self.describe()}


__all__ = ["MobileSettings"]
