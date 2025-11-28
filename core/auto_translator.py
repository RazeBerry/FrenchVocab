"""Auto-detecting translator that wraps directional TranslatorCLI flows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

from rich.console import Console
from rich import box

from languages import LanguageConfig
from llm_client import LLMClient
from ui_helper import UIHelper, read_line
from .translator import TranslatorCLI


UsageCallback = Optional[Callable[[Dict[str, int]], None]]


@dataclass
class AutoTranslationResult:
    direction: str
    translation: str
    notes: Optional[str] = None


class AutoTranslator:
    """Orchestrates an intelligent translation flow that auto-detects direction."""

    GENERIC_ENG_TO_TARGET = {"english_to_target"}
    GENERIC_TARGET_TO_ENG = {"target_to_english"}

    def __init__(
        self,
        *,
        console: Console,
        client: Optional[LLMClient],
        language_config: LanguageConfig,
        eng_to_target: Optional[TranslatorCLI],
        target_to_eng: Optional[TranslatorCLI],
        prompt_template: Optional[str],
        prompt_variable: str = "source_text",
        usage_callback: UsageCallback = None,
    ) -> None:
        self.console = console
        self.ui = UIHelper(console)
        self.client = client
        self.language_config = language_config
        self.eng_to_target = eng_to_target
        self.target_to_eng = target_to_eng
        self.prompt_template = prompt_template
        self.prompt_variable = prompt_variable or "source_text"
        self.usage_callback = usage_callback

        lang_code = (language_config.code or "").lower()
        configured_tokens = language_config.auto_direction_tokens
        if configured_tokens and len(configured_tokens) == 2:
            eng_tok, target_tok = configured_tokens
        else:
            eng_tok = f"english_to_{lang_code}" if lang_code else "english_to_target"
            target_tok = f"{lang_code}_to_english" if lang_code else "target_to_english"

        self.eng_direction_tokens = {eng_tok.lower()} | self.GENERIC_ENG_TO_TARGET
        self.target_direction_tokens = {target_tok.lower()} | self.GENERIC_TARGET_TO_ENG

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def run(self) -> None:
        """Entry point invoked from the CLI."""
        if not self._ready():
            return

        source_text = self._collect_multiline_input()
        if not source_text:
            return

        response = self._query_auto_translation(source_text)
        if response is None:
            return

        result = self._parse_response(response)
        if result is None:
            self.ui.error("Unable to parse auto-translation response. Please retry or use manual direction.")
            return

        translator = self._translator_for_direction(result.direction)
        if translator is None:
            self.ui.error("Detected translation direction is unavailable. Check AI provider setup.")
            return

        self._announce_detection(result)
        ok = translator.translate_and_save(source_text, provided_translation=result.translation)
        if not ok:
            self.ui.warning("Auto-translation cancelled or failed.")

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _ready(self) -> bool:
        if not self.client:
            self.ui.error("AI client is not available. Configure a provider to use the auto translator.")
            return False
        if not self.prompt_template:
            self.ui.error("Auto translator prompt template is missing.")
            return False
        if not (self.eng_to_target and self.target_to_eng):
            self.ui.error("Both directional translators must be initialized to use auto mode.")
            return False
        return True

    def _collect_multiline_input(self) -> Optional[str]:
        instructions = (
            "[#E67E50]Enter text to translate.[/#E67E50]\n"
            "[dim]- Type or paste your text, then press Enter.\n"
            "- Press Esc to cancel.[/dim]"
        )
        self.ui.panel(
            instructions,
            border_style="dark_orange",
            expand=False,
            box_style=box.ROUNDED,
        )

        try:
            line = read_line("Text (Esc to cancel): ")
        except EOFError:
            self.ui.warning("Translation cancelled.")
            return None
        except KeyboardInterrupt:
            self.ui.warning("Translation cancelled.")
            return None

        if line and "\x1b" in line:
            self.ui.warning("Auto translation cancelled via Esc.")
            return None

        text = line.strip()
        if not text:
            self.ui.warning("Translation cancelled.")
            return None
        return text

    def _query_auto_translation(self, source_text: str) -> Optional[str]:
        prompt_variable = self.prompt_variable
        try:
            prompt = self.prompt_template.format(**{prompt_variable: source_text})
        except KeyError as exc:
            self.ui.error(f"Auto translator prompt missing placeholder for '{exc.args[0]}'.")
            return None

        metrics: Dict[str, Dict[str, int]] | Dict[str, int] | Dict = {}
        try:
            with self.console.status("[cyan]Detecting translation direction..."):
                chunks: list[str] = []
                stream = self.client.stream(prompt)
                while True:
                    try:
                        chunk = next(stream)
                        chunks.append(chunk)
                    except StopIteration as stop:
                        metrics = stop.value if stop.value else {}
                        break
            response = "".join(chunks).strip()
            if not response:
                self.ui.error("Auto translator received an empty response.")
                return None
            return response
        except Exception as exc:  # pragma: no cover - defensive path
            self.ui.error(f"An error occurred during auto translation: {exc}")
            return None
        finally:
            usage = metrics.get("usage") if isinstance(metrics, dict) else None
            self._emit_usage(usage if isinstance(usage, dict) else None)

    def _parse_response(self, text: str) -> Optional[AutoTranslationResult]:
        direction_match = re.search(r"^\s*Direction:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
        translation_header = re.search(r"Translation:\s*", text, re.IGNORECASE)

        if not direction_match or not translation_header:
            return None

        direction = direction_match.group(1).strip().lower()
        translation_start = translation_header.end()
        notes_header_pattern = re.compile(r"^\s*Notes:\s*", re.IGNORECASE | re.MULTILINE)
        notes_header = notes_header_pattern.search(text, translation_start)

        translation_end = notes_header.start() if notes_header else len(text)
        translation = text[translation_start:translation_end].strip()

        notes = None
        if notes_header:
            notes = text[notes_header.end():].strip() or None

        if not translation:
            return None

        return AutoTranslationResult(direction=direction, translation=translation, notes=notes)

    def _translator_for_direction(self, direction: str) -> Optional[TranslatorCLI]:
        normalized = direction.strip().lower()
        if normalized in self.eng_direction_tokens:
            return self.eng_to_target

        lang_token = f"english_to_{self.language_config.code}".lower()
        if normalized == lang_token:
            return self.eng_to_target

        if normalized in self.target_direction_tokens:
            return self.target_to_eng

        reverse_lang = f"{self.language_config.code}_to_english".lower()
        if normalized == reverse_lang:
            return self.target_to_eng

        return None

    def _announce_detection(self, result: AutoTranslationResult) -> None:
        direction_display = result.direction.replace("_", " ").title()
        message = f"[bold #E67E50]Detected direction:[/bold #E67E50] {direction_display}"
        self.ui.panel(
            message,
            title="Auto Translator",
            border_style="dark_orange",
            expand=False,
            box_style=box.ROUNDED,
        )

        if result.notes and result.notes.strip().lower() != "none":
            self.ui.panel(
                f"[bold]Notes:[/bold]\n{result.notes.strip()}",
                border_style="dim cyan",
                expand=False,
                box_style=box.ROUNDED,
            )

    def _emit_usage(self, usage: Optional[Dict[str, int]]) -> None:
        if self.usage_callback and usage:
            self.usage_callback(usage)
