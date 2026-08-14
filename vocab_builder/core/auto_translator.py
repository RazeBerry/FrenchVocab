"""Auto-detecting translator that wraps directional TranslatorCLI flows."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from rich.console import Console
from rich import box

from vocab_builder.languages import LanguageConfig
from vocab_builder.llm_client import LLMClient
from vocab_builder.ui_helper import UIHelper, read_line
from .input_config import input_cancel_label
from .translator import TranslatorCLI


UsageCallback = Optional[Callable[[Dict[str, int]], None]]
AMBIGUOUS_DIRECTION_TOKENS = frozenset({"ambiguous", "uncertain", "undetermined"})


def normalize_direction(direction: str) -> str:
    """Normalize model-produced direction labels for safe routing."""
    normalized = re.sub(r"[\s\-]+", "_", direction.strip().lower())
    normalized = re.sub(r"[→>]+", "_to_", normalized)
    return re.sub(r"_+", "_", normalized).strip("_")


def is_ambiguous_direction(direction: str) -> bool:
    """Return whether the model explicitly declined to guess a direction."""
    return normalize_direction(direction) in AMBIGUOUS_DIRECTION_TOKENS


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
        on_query_exception: Optional[Callable[[Exception, str], bool]] = None,
        verbose: bool = False,
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
        self.on_query_exception = on_query_exception
        self.verbose = verbose

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

        result = self.preview_translation(source_text)
        if result is None:
            self.ui.error("Unable to parse auto-translation response. Please retry or use manual direction.")
            return

        if self.direction_is_ambiguous(result.direction):
            self._announce_ambiguity(result)
            return

        if self.verbose:
            trunc = result.translation[:120] + ("..." if len(result.translation) > 120 else "")
            self.ui.info(f"[dim]Parsed direction={result.direction!r}  translation={trunc!r}[/dim]")

        if not self._sanity_check(source_text, result.translation):
            return

        translator = self.translator_for_direction(result.direction)
        if translator is None:
            self.ui.error("Detected translation direction is unavailable. Check AI provider setup.")
            return

        self._announce_detection(result)
        ok = translator.translate_and_save(source_text, provided_translation=result.translation)
        if not ok:
            self.ui.warning("Auto-translation cancelled or failed.")

    def preview_translation(self, source_text: str) -> Optional[AutoTranslationResult]:
        """Detect direction and generate a translation without saving it."""
        if not self._ready() or not source_text.strip():
            return None
        response = self._query_auto_translation(source_text.strip())
        return self._parse_response(response) if response is not None else None

    def translator_for_direction(self, direction: str) -> Optional[TranslatorCLI]:
        """Resolve a detected direction to the configured directional writer."""
        return self._translator_for_direction(direction)

    @staticmethod
    def direction_is_ambiguous(direction: str) -> bool:
        """Expose the shared ambiguity rule to headless adapters."""
        return is_ambiguous_direction(direction)

    @staticmethod
    def translation_is_suspicious(source_text: str, translation: str) -> bool:
        """Return whether source and translation are implausibly similar."""
        src = source_text.strip().casefold()
        tgt = translation.strip().casefold()
        if src in tgt or tgt in src:
            return True
        src_words = src.split()
        tgt_words = tgt.split()
        return (
            len(src_words) > 3
            and len(tgt_words) > 3
            and difflib.SequenceMatcher(None, src_words, tgt_words).ratio() > 0.7
        )

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
        cancel_label = input_cancel_label()
        instructions = (
            "[#E67E50]Enter text to translate.[/#E67E50]\n"
            "[dim]- Type or paste your text, then press Enter.\n"
            f"- Press {cancel_label} to cancel.[/dim]"
        )
        self.ui.panel(
            instructions,
            border_style="dark_orange",
            box_style=box.ROUNDED,
        )

        try:
            line = read_line(f"Text ({cancel_label} to cancel): ")
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
                stream = self.client.stream(prompt, thinking_level="medium")
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
            if self.verbose:
                self.ui.info(f"[dim]Raw auto-translator response:[/dim]\n{response}")
            return response
        except Exception as exc:  # pragma: no cover - defensive path
            handled = False
            if self.on_query_exception and self.client is not None:
                provider_label = self.client.__class__.__name__
                model_label = getattr(self.client, "model_label", None)
                if callable(model_label):
                    try:
                        provider_label = model_label()
                    except Exception:
                        provider_label = self.client.__class__.__name__
                handled = self.on_query_exception(exc, provider_label)
            if not handled:
                self.ui.error(f"An error occurred during auto translation: {exc}")
            return None
        finally:
            usage = metrics.get("usage") if isinstance(metrics, dict) else None
            self._emit_usage(usage if isinstance(usage, dict) else None)

    def _parse_response(self, text: str) -> Optional[AutoTranslationResult]:
        direction_matches = list(
            re.finditer(r"^\s*Direction:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
        )
        if not direction_matches:
            return None
        direction_match = direction_matches[-1]

        search_after = direction_match.end()
        translation_header = re.search(r"Translation:\s*", text[search_after:], re.IGNORECASE)

        if not translation_header:
            return None

        direction = direction_match.group(1).strip().lower()
        translation_start = search_after + translation_header.end()
        notes_header_pattern = re.compile(r"^\s*Notes:\s*", re.IGNORECASE | re.MULTILINE)
        notes_header = notes_header_pattern.search(text, translation_start)

        translation_end = notes_header.start() if notes_header else len(text)
        translation = text[translation_start:translation_end].strip()

        notes = None
        if notes_header:
            notes = text[notes_header.end():].strip() or None

        if is_ambiguous_direction(direction):
            translation = ""
        elif not translation:
            return None

        return AutoTranslationResult(direction=direction, translation=translation, notes=notes)

    def _translator_for_direction(self, direction: str) -> Optional[TranslatorCLI]:
        normalized = normalize_direction(direction)

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
            box_style=box.ROUNDED,
        )

        if result.notes and result.notes.strip().lower() != "none":
            self.ui.panel(
                f"[bold]Notes:[/bold]\n{result.notes.strip()}",
                border_style="dim cyan",
                box_style=box.ROUNDED,
            )

    def _announce_ambiguity(self, result: AutoTranslationResult) -> None:
        self.ui.warning(
            "The source language is ambiguous. Choose English → target language "
            "or target language → English explicitly; no translation was saved."
        )
        if result.notes and result.notes.strip().lower() != "none":
            self.ui.info(result.notes.strip())

    def _sanity_check(self, source_text: str, translation: str) -> bool:
        """Return True if the translation looks like a different language from the input."""
        if not self.translation_is_suspicious(source_text, translation):
            return True

        self.ui.warning(
            "The translation looks very similar to the input — "
            "the AI may have detected the wrong language direction."
        )
        try:
            answer = read_line("Accept this translation anyway? (y/N): ")
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer.strip().lower() in ("y", "yes"):
            return True

        self.ui.info("Translation rejected. Try using a manual direction instead.")
        return False

    def _emit_usage(self, usage: Optional[Dict[str, int]]) -> None:
        if self.usage_callback and usage:
            self.usage_callback(usage)
