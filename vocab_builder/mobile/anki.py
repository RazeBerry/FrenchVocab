"""Non-interactive Anki export and reconciliation operations."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import threading
from typing import Any, Callable


_SAFE_DOWNLOAD = re.compile(r"^[A-Za-z0-9._-]+\.apkg$")


class MobileAnki:
    def __init__(
        self,
        builder: Any,
        *,
        token_factory: Callable[[], str],
        state_lock: threading.RLock,
    ):
        self.builder = builder
        self._token_factory = token_factory
        self._state_lock = state_lock
        self.export_root = builder.latex_file.parent / "exports"

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            manager = self.builder.get_anki_manager()
            pending, stale = manager.compare_entries_and_exports()
            return {
                "pending_count": len(pending),
                "stale_count": len(stale),
                "pending_words": sorted(pending),
                "stale_words": sorted(stale),
                "last_export": manager.last_export_metadata,
                "snapshot": manager.snapshot_export_metadata,
            }

    def export(
        self,
        mode: str,
        *,
        selected_words: list[str] | None = None,
        include_mistakes: bool = False,
    ) -> dict[str, Any]:
        if mode not in {"incremental", "rebuild", "selected", "reconcile"}:
            raise ValueError("Choose incremental, rebuild, selected, or reconcile export.")
        with self._state_lock:
            manager = self.builder.get_anki_manager()
            selected = None
            include_exported = mode == "rebuild"
            if mode == "selected":
                selected = self._resolve_selected(selected_words or [])
                if not selected:
                    raise ValueError("None of the selected words are in this collection.")
                include_exported = True
            elif mode == "reconcile":
                selected, _stale = manager.compare_entries_and_exports()
                if not selected:
                    raise ValueError("There are no missing Anki entries to reconcile.")

            token = self._token_factory().replace("_", "-")
            filename = f"{self.builder.language_code}-{mode}-{token}.apkg"
            destination = self.export_root / filename
            manager.export_to_anki(
                self.builder.language_config.anki.default_deck_name,
                include_exported_words=include_exported,
                selected_words=selected,
                auto_retry_on_empty=False,
                output_path=destination,
                export_context=f"mobile_{mode}",
                include_mistake_deck=include_mistakes,
            )
            if not destination.exists() or destination.stat().st_size <= 0:
                raise RuntimeError("Anki could not create a deck for that selection.")
            return {
                "filename": filename,
                "download_url": f"/api/anki/download/{filename}",
                "size": destination.stat().st_size,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "mode": mode,
            }

    def remove_stale_tracking(self) -> dict[str, Any]:
        with self._state_lock:
            manager = self.builder.get_anki_manager()
            removed = manager.remove_stale_export_tracking()
            return {"removed": removed, **self.status()}

    def resolve_download(self, filename: str) -> Path:
        if not _SAFE_DOWNLOAD.fullmatch(filename):
            raise ValueError("Invalid Anki download name.")
        candidate = (self.export_root / filename).resolve()
        root = self.export_root.resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise FileNotFoundError(filename)
        return candidate

    def _resolve_selected(self, words: list[str]) -> set[str]:
        selected = set()
        for word in words:
            existing = self.builder.check_duplicate(word)
            if existing:
                selected.add(existing)
        return selected


__all__ = ["MobileAnki"]
