"""Composition-practice use cases for the private mobile surface."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import threading
from typing import Any, Callable

from vocab_builder.core.composition import CompositionPrompt
from vocab_builder.core.composition_scheduler import ScheduledWord


class MobilePractice:
    """Keep mobile practice state durable while reusing the CLI coach."""

    def __init__(
        self,
        builder: Any,
        *,
        attempts: dict[str, dict[str, Any]],
        token_factory: Callable[[], str],
        persist: Callable[[], None],
        ai_lock: threading.Lock,
        state_lock: threading.RLock,
    ):
        self.builder = builder
        self._attempts = attempts
        self._token_factory = token_factory
        self._persist = persist
        self._ai_lock = ai_lock
        self._state_lock = state_lock
        self._workflow_lock = threading.RLock()

    def describe(self) -> dict[str, Any]:
        with self._workflow_lock:
            if not getattr(self.builder, "enable_composition", False):
                return {"available": False, "debt_count": None, "modes": []}
            coach = self.builder.get_composition_coach()
            self.repair_history()
            return {
                "available": True,
                "debt_count": coach.scheduler.debt_count(),
                "set_size": coach.set_size,
                "words_per_attempt": coach.words_per_attempt,
                "modes": [
                    {"id": "use_words", "label": coach.config.use_words_label},
                    {"id": "reverse", "label": coach.config.reverse_label},
                ],
            }

    def create_prompt(
        self,
        mode: str,
        *,
        exclude_keys: list[str] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        with self._workflow_lock:
            if not getattr(self.builder, "enable_composition", False):
                raise ValueError("Composition practice is disabled.")
            coach = self.builder.get_composition_coach()
            prompt = coach.create_prompt(mode, exclude_keys=set(exclude_keys or ()))
            if prompt is None:
                raise ValueError("No suitable vocabulary entries are available for this practice mode.")
            token = self._token_factory()
            payload = {
                "token": token,
                "session_id": session_id or token,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "prompt": _prompt_to_json(prompt),
            }
            with self._state_lock:
                self._attempts[token] = payload
                self._persist()
            return _public_prompt(payload)

    def grade(self, token: str, user_text: str) -> dict[str, Any]:
        with self._workflow_lock:
            with self._ai_lock:
                with self._state_lock:
                    payload = self._attempts.get(token)
                    if payload is None:
                        raise KeyError("That practice prompt expired. Start another attempt.")
                    existing = payload.get("feedback")
                    if isinstance(existing, dict):
                        self._repair_one(payload)
                        return dict(payload["feedback"])
                    prompt = _prompt_from_json(dict(payload["prompt"]))
                coach = self.builder.get_composition_coach()
                feedback = coach.grade_prompt(
                    prompt,
                    user_text,
                    session_id=str(payload["session_id"]),
                    record_history=False,
                )
            if feedback is None:
                raise RuntimeError("The composition grader returned no usable feedback.")

            response = asdict(feedback.parsed)
            response.update(
                {
                    "token": token,
                    "attempt_id": feedback.attempt_id,
                    "history_pending": True,
                    "target_words": [word.word for word in prompt.words],
                    "mode": prompt.mode,
                    "source_english": prompt.source_english,
                    "reference_target": prompt.reference_target,
                }
            )
            with self._state_lock:
                payload["history_record"] = feedback.history_record
                payload["feedback"] = response
                self._persist()
                self._repair_one(payload)
                self._persist()
                return dict(payload["feedback"])

    def repair_history(self) -> None:
        with self._state_lock:
            changed = False
            for payload in self._attempts.values():
                if self._repair_one(payload):
                    changed = True
            if changed:
                self._persist()

    def _repair_one(self, payload: dict[str, Any]) -> bool:
        response = payload.get("feedback")
        record = payload.get("history_record")
        if not isinstance(response, dict) or not isinstance(record, dict):
            return False
        if not response.get("history_pending"):
            return False
        coach = self.builder.get_composition_coach()
        attempt_id = str(record.get("attempt_id", ""))
        saved = coach.logger.has_attempt(attempt_id) or coach.logger.log_attempt(record)
        if saved:
            response["history_pending"] = False
            coach.scheduler.invalidate()
            return True
        return False


def _prompt_to_json(prompt: CompositionPrompt) -> dict[str, Any]:
    return {
        "mode": prompt.mode,
        "words": [asdict(word) for word in prompt.words],
        "source_english": prompt.source_english,
        "reference_target": prompt.reference_target,
    }


def _prompt_from_json(payload: dict[str, Any]) -> CompositionPrompt:
    words = []
    for raw in payload.get("words", []):
        data = dict(raw)
        data["examples"] = tuple(tuple(pair) for pair in data.get("examples", []))
        words.append(ScheduledWord(**data))
    return CompositionPrompt(
        mode=str(payload["mode"]),
        words=tuple(words),
        source_english=(
            str(payload["source_english"])
            if payload.get("source_english") is not None
            else None
        ),
        reference_target=(
            str(payload["reference_target"])
            if payload.get("reference_target") is not None
            else None
        ),
    )


def _public_prompt(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = dict(payload["prompt"])
    return {
        "token": payload["token"],
        "session_id": payload["session_id"],
        "mode": prompt["mode"],
        "words": prompt["words"],
        "source_english": prompt.get("source_english"),
        "reference_target": prompt.get("reference_target"),
    }


__all__ = ["MobilePractice"]
