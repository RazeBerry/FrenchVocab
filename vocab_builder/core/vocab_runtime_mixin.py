"""Runtime flag and history logger helpers for VocabBuilder."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from vocab_builder.compat import get_env

from .history_logger import TranslationLogger, default_history_base_dir


class VocabRuntimeMixin:
    @staticmethod
    def _parse_bool_flag(value: object) -> Optional[bool]:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "y", "on")
        return None

    @staticmethod
    def _parse_positive_int(value: object) -> Optional[int]:
        try:
            parsed = int(value)
        except (ValueError, TypeError):
            return None
        return parsed if parsed > 0 else None

    def _apply_config_bool_override(self, limits: Dict[str, Any], key: str, attr_name: str) -> None:
        if key not in limits:
            return
        parsed = self._parse_bool_flag(limits.get(key))
        if parsed is None:
            return
        setattr(self, attr_name, parsed)

    def _apply_input_limits_from_config(self, limits: Dict[str, Any]) -> None:
        max_chars = self._parse_positive_int(limits.get("max_chars"))
        if max_chars is not None:
            self.max_word_length = max_chars

        if "max_words" in limits:
            self.max_words = self._parse_positive_int(limits.get("max_words"))

        self._apply_config_bool_override(limits, "sentence_mode", "allow_sentence_punctuation")
        self._apply_config_bool_override(limits, "route_sentences", "route_sentences")
        self._apply_config_bool_override(limits, "sentence_examples", "sentence_examples_in_vocab")

    def _load_input_limits_from_config_file(self) -> None:
        try:
            cfg_path = Path(__file__).parent.parent.parent / str(self.config_file)
            if not cfg_path.exists():
                return
            with cfg_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            if self.verbose:
                self.ui.debug(f"Skipping config load from {self.config_file}: {exc}")
            return

        self._config_data = data if isinstance(data, dict) else {}
        if not isinstance(data, dict):
            return

        limits = data.get("input_limits", {})
        if isinstance(limits, dict):
            self._apply_input_limits_from_config(limits)

    def _apply_env_max_chars_override(self) -> None:
        env_chars = get_env("VOCABBUILDER_MAX_CHARS")
        if not env_chars:
            return
        try:
            parsed = int(env_chars)
        except (ValueError, TypeError):
            return
        if parsed > 0:
            self.max_word_length = parsed

    def _apply_env_max_words_override(self) -> None:
        env_words = get_env("VOCABBUILDER_MAX_WORDS")
        if env_words is None:
            return
        try:
            parsed = int(env_words)
        except (ValueError, TypeError):
            return
        if parsed > 0:
            self.max_words = parsed
        else:
            self.max_words = None

    def _apply_env_sentence_mode_override(self) -> None:
        env_sentence = get_env("VOCABBUILDER_SENTENCE_MODE") or get_env("VOCABBUILDER_ALLOW_PUNCT")
        if env_sentence is None:
            return
        self.allow_sentence_punctuation = str(env_sentence).strip().lower() in (
            "1",
            "true",
            "yes",
            "y",
            "on",
        )

    def _apply_env_bool_override(self, env_var: str, attr_name: str) -> None:
        env_value = get_env(env_var)
        if env_value is None:
            return
        parsed = self._parse_bool_flag(env_value)
        if parsed is None:
            return
        setattr(self, attr_name, parsed)

    def _load_input_limits(self) -> None:
        """Load UI/input and routing options from env or optional JSON config.

        Priority: defaults < config file < environment variables.
        - Env vars: VOCABBUILDER_MAX_CHARS, VOCABBUILDER_MAX_WORDS
        - Config file (JSON): {"input_limits": {"max_chars": int, "max_words": int|null}}
        Any non-positive or null max_words disables the word-count limit.
        """
        self._load_input_limits_from_config_file()
        self._apply_env_max_chars_override()
        self._apply_env_max_words_override()
        self._apply_env_sentence_mode_override()
        self._apply_env_bool_override("VOCABBUILDER_ROUTE_SENTENCES", "route_sentences")
        self._apply_env_bool_override("VOCABBUILDER_SENTENCE_EXAMPLES", "sentence_examples_in_vocab")

    def _should_enable_auto_translator(self) -> bool:
        env_value = get_env("VOCABBUILDER_AUTO_TRANSLATOR")
        if env_value is not None:
            return str(env_value).strip().lower() in ("1", "true", "yes", "y", "on")
        return bool(getattr(self.language_config, "auto_prompt_template", None))

    def _create_history_logger(self) -> TranslationLogger:
        config_section: Dict[str, Any] = {}
        raw_config = self._config_data.get("history_logging") if isinstance(self._config_data, dict) else None
        if isinstance(raw_config, dict):
            config_section = raw_config

        enabled = bool(config_section.get("enabled", True))
        env_disabled = get_env("VOCABBUILDER_HISTORY_DISABLED")
        if env_disabled and env_disabled.strip().lower() in ("1", "true", "yes", "y", "on"):
            enabled = False
        env_enabled = get_env("VOCABBUILDER_HISTORY_ENABLED")
        if env_enabled and env_enabled.strip().lower() in ("1", "true", "yes", "y", "on"):
            enabled = True

        base_dir_override = get_env("VOCABBUILDER_HISTORY_DIR")
        if base_dir_override:
            base_dir = Path(base_dir_override)
        else:
            configured_dir = config_section.get("directory")
            if configured_dir:
                base_dir = Path(configured_dir)
                if not base_dir.is_absolute():
                    base_dir = (self.project_root / base_dir).resolve()
            else:
                base_dir = default_history_base_dir()

        file_pattern = config_section.get("file_pattern", "{language}_translations.jsonl")

        return TranslationLogger(
            language_code=self.language_code,
            base_dir=base_dir,
            enabled=enabled,
            file_pattern=file_pattern,
            on_error=self._history_log_error,
        )

    def _history_log_error(self, message: str) -> None:
        try:
            self.ui.warning(message)
        except (RuntimeError, OSError, AttributeError) as e:
            # Fallback: print to stderr if UI fails
            print(f"WARNING: {message}", file=sys.stderr)
            print(f"(UI error: {e})", file=sys.stderr)
