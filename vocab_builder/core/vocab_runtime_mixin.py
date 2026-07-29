"""Runtime flag and history logger helpers for VocabBuilder."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from vocab_builder.compat import config_homes_for_read, config_home, get_env

from .composition_scheduler import (
    composition_feature_enabled,
    composition_set_size,
    composition_words_per_attempt,
)
from .history_logger import CompositionLogger, TranslationLogger, default_history_base_dir
from .word_entry_workflow import WordEntryWorkflow, WorkflowCallbacks, WorkflowOptions


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
        candidate_paths = []
        project_root = getattr(self, "project_root", None)
        if project_root is not None:
            candidate_paths.append(Path(project_root) / str(self.config_file))
        else:
            candidate_paths.append(config_home(warn_on_legacy=False) / str(self.config_file))
        for config_dir in config_homes_for_read():
            candidate_paths.append(config_dir / str(self.config_file))

        data: Dict[str, Any] | None = None
        for cfg_path in dict.fromkeys(candidate_paths):
            try:
                if not cfg_path.exists():
                    continue
                with cfg_path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                if self.verbose:
                    self.ui.debug(f"Skipping config load from {cfg_path}: {exc}")
                continue
            if isinstance(loaded, dict):
                data = loaded
            else:
                data = {}
            break

        if data is None:
            return

        self._config_data = data

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

    def _should_enable_composition(self) -> bool:
        return composition_feature_enabled(default=True)

    def _create_composition_logger(self) -> CompositionLogger:
        history_logger = getattr(self, "history_logger", None)
        if history_logger is not None:
            return CompositionLogger(
                language_code=self.language_code,
                base_dir=history_logger.base_dir,
                enabled=history_logger.enabled,
                fallback_base_dirs=history_logger.fallback_base_dirs,
                on_error=self._history_log_error,
            )
        return CompositionLogger(
            language_code=self.language_code,
            base_dir=default_history_base_dir(),
            on_error=self._history_log_error,
        )

    def _read_vocab_history_for_anki_order(self) -> list[Dict[str, Any]]:
        logger = getattr(self, "history_logger", None)
        if logger is None:
            return []
        return logger.read_recent_vocab_entries(
            limit=None,
            actions=("new", "force"),
        )

    def _ensure_composition_coach(self):
        coach = getattr(self, "_composition_coach", None)
        if coach is not None:
            return coach
        from .composition import CompositionCoach

        coach = CompositionCoach(
            console=self.console,
            llm=self._llm,
            language_config=self.language_config,
            vocab_repo=self._vocab_repo,
            logger=self._create_composition_logger(),
            set_size=composition_set_size(),
            words_per_attempt=composition_words_per_attempt(),
            provider_label_fn=self._provider_label,
            on_settings=self.show_settings_screen,
            on_query_exception=self._handle_ai_exception,
            run_word_entry=self._run_seeded_word_entry,
        )
        self._composition_coach = coach
        return coach

    def _build_word_entry_workflow(self, get_word_input_fn=None) -> WordEntryWorkflow:
        """Construct a WordEntryWorkflow wired to this app's callbacks.

        ``get_word_input_fn`` overrides the interactive word prompt so callers
        (composition capture) can pre-seed the word being added.
        """
        options = WorkflowOptions(
            max_word_length=self.max_word_length,
            max_words=self.max_words,
            allow_sentence_punctuation=self.allow_sentence_punctuation,
            route_sentences=self.route_sentences,
            sentence_examples_in_vocab=self.sentence_examples_in_vocab,
            entry_command=self.entry_command,
        )
        callbacks = WorkflowCallbacks(
            provider_label_fn=self._provider_label,
            on_settings=self.show_settings_screen,
            on_entry_saved=self._ensure_anki_manager().register_entry_order,
            on_post_translation_menu=self._show_post_translation_menu,
            get_word_input_fn=get_word_input_fn or self.get_word_input,
            query_ai_fn=self.query_ai,
            check_spelling_fn=self.check_spelling,
            parse_ai_response_fn=self.parse_ai_response,
            check_duplicate_fn=self.check_duplicate,
            display_parsed_info_fn=self.display_parsed_info,
            display_latex_entry_fn=self.display_latex_entry,
            is_valid_latex_entry_fn=self.is_valid_latex_entry,
            insert_entry_alphabetically_fn=self.insert_entry_alphabetically,
            add_word_to_entries_fn=self.add_word_to_entries,
        )
        return WordEntryWorkflow(
            vocab_repo=self._vocab_repo,
            llm=self._llm,
            ui=self.ui,
            language_config=self.language_config,
            history_logger=self.history_logger,
            spelling_checker=self._spelling_checker,
            target_to_eng_translator=self.target_to_eng_translator,
            options=options,
            callbacks=callbacks,
        )

    def _run_seeded_word_entry(self, word: str) -> None:
        """Run one word-entry pass with the word pre-seeded (no retyping)."""
        workflow = self._build_word_entry_workflow(get_word_input_fn=lambda: word)
        workflow.run(self.ensure_llm_ready)
        self.duplicate_resolution = workflow.duplicate_resolution

    def composition_debt_count(self) -> Optional[int]:
        if not getattr(self, "enable_composition", True):
            return None
        return self._ensure_composition_coach().scheduler.debt_count()

    def handle_composition(self) -> None:
        if not getattr(self, "enable_composition", True):
            self.ui.warning("Composition practice is disabled by VOCABBUILDER_COMPOSITION.")
            return
        if not self.ensure_llm_ready():
            return
        self._ensure_composition_coach().run()

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

        fallback_history_dirs: tuple[Path, ...] = ()
        if not base_dir_override and not configured_dir:
            primary_base_dir = config_home(create=True) / "history"
            fallback_history_dirs = tuple(
                candidate / "history"
                for candidate in config_homes_for_read()
                if candidate / "history" != primary_base_dir
            )
            base_dir = primary_base_dir

        file_pattern = config_section.get("file_pattern", "{language}_translations.jsonl")

        return TranslationLogger(
            language_code=self.language_code,
            base_dir=base_dir,
            enabled=enabled,
            file_pattern=file_pattern,
            fallback_base_dirs=fallback_history_dirs,
            on_error=self._history_log_error,
        )

    def _history_log_error(self, message: str) -> None:
        try:
            self.ui.warning(message)
        except (RuntimeError, OSError, AttributeError) as e:
            # Fallback: print to stderr if UI fails
            print(f"WARNING: {message}", file=sys.stderr)
            print(f"(UI error: {e})", file=sys.stderr)
