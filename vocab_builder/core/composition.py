"""Interactive composition-practice coach."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from uuid import uuid4

from rich import box
from rich.console import Console

from vocab_builder.core.composition_parser import (
    ParsedCompositionResponse,
    parse_composition_response,
)
from vocab_builder.core.composition_scheduler import (
    CompositionScheduler,
    ScheduledWord,
    VERDICT_CORRECT,
    VERDICT_INCORRECT,
    VERDICT_NOT_USED,
)
from vocab_builder.core.history_logger import CompositionLogger
from vocab_builder.core.input_config import input_cancel_label
from vocab_builder.languages import CompositionConfig, LanguageConfig
from vocab_builder.ui_helper import UIHelper, read_line


@dataclass(frozen=True)
class CompositionAttemptResult:
    target_words: list[str]
    word_verdicts: dict[str, str]
    unknown_candidates: list[dict[str, str]]


@dataclass(frozen=True)
class CompositionPrompt:
    mode: str
    words: tuple[ScheduledWord, ...]
    source_english: Optional[str] = None
    reference_target: Optional[str] = None


@dataclass(frozen=True)
class CompositionFeedback:
    parsed: ParsedCompositionResponse
    history_saved: bool
    attempt_id: str
    history_record: dict[str, Any]


class CompositionCoach:
    """Composition-practice CLI shaped like the existing translator flows."""

    def __init__(
        self,
        *,
        console: Console,
        llm: Any,
        language_config: LanguageConfig,
        vocab_repo: Any,
        logger: CompositionLogger,
        set_size: int,
        words_per_attempt: int,
        provider_label_fn: Callable[[], str],
        on_settings: Optional[Callable[[], None]] = None,
        on_query_exception: Optional[Callable[[Exception, str], bool]] = None,
        run_word_entry: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.console = console
        self.ui = UIHelper(console)
        self.llm = llm
        self.language_config = language_config
        self.config = language_config.composition or CompositionConfig(
            grading_prompt_template=""
        )
        self.vocab_repo = vocab_repo
        self.logger = logger
        self.set_size = set_size
        self.words_per_attempt = words_per_attempt
        self.provider_label_fn = provider_label_fn
        self.on_settings = on_settings
        self.on_query_exception = on_query_exception
        self.run_word_entry = run_word_entry
        self.scheduler = CompositionScheduler(
            vocab_repo=vocab_repo,
            history_paths=logger.record_paths_for_read(),
        )

    def run(self) -> None:
        choice = self._show_mode_menu()
        if choice == "use_words":
            self.run_use_words_daily_set()
        elif choice == "reverse":
            self.run_reverse_daily_set()

    def run_use_words_daily_set(self) -> None:
        if not self.config.grading_prompt_template:
            self.ui.error("Composition grading prompt is not configured for this language.")
            return

        session_id = str(uuid4())
        debt_before = self.scheduler.debt_count()
        results: list[CompositionAttemptResult] = []
        used_keys: set[str] = set()

        self._show_header(debt_before)
        for attempt_number in range(1, self.set_size + 1):
            words = self._next_words(used_keys)
            if not words:
                self.ui.warning("No vocabulary entries are available for composition practice.")
                break

            self._show_target_words(words, attempt_number)
            user_text = self._collect_multiline_input()
            if user_text is None:
                self.ui.warning("Composition practice cancelled.")
                break
            self._warn_if_long(user_text)

            parsed = self._grade_attempt(words, user_text)
            if parsed is None:
                break

            self._render_feedback(parsed)
            record = self._build_history_record(
                session_id=session_id,
                words=words,
                user_text=user_text,
                parsed=parsed,
            )
            self.logger.log_attempt(record)
            self.scheduler.invalidate()
            used_keys.update(word.key for word in words)
            results.append(
                CompositionAttemptResult(
                    target_words=[word.word for word in words],
                    word_verdicts=dict(parsed.word_verdicts),
                    unknown_candidates=[
                        {"word": candidate.word, "gloss": candidate.gloss}
                        for candidate in parsed.unknown_candidates
                    ],
                )
            )

        if results:
            self._show_summary(results, debt_before, self.scheduler.debt_count())

    def run_reverse_daily_set(self) -> None:
        if not self.config.reverse_grading_prompt_template:
            self.ui.error("Recall-practice grading is not configured for this language.")
            return

        session_id = str(uuid4())
        debt_before = self.scheduler.debt_count()
        results: list[CompositionAttemptResult] = []
        used_keys: set[str] = set()

        self._show_header(debt_before)
        for attempt_number in range(1, self.set_size + 1):
            word = self.scheduler.sample_reverse_word(exclude_keys=used_keys)
            if word is None:
                self.ui.warning(
                    "No vocabulary entries with usable stored examples are available for recall practice."
                )
                break

            reference_target, source_english = word.examples[0]
            self._show_reverse_prompt(
                source_english,
                attempt_number,
                target_word=word.word,
            )
            user_text = self._collect_multiline_input()
            if user_text is None:
                self.ui.warning("Composition practice cancelled.")
                break
            self._warn_if_long(user_text)

            parsed = self._grade_reverse_attempt(
                word,
                source_english=source_english,
                reference_target=reference_target,
                user_text=user_text,
            )
            if parsed is None:
                break

            self._render_feedback(parsed, reference_target=reference_target)
            record = self._build_history_record(
                session_id=session_id,
                words=[word],
                user_text=user_text,
                parsed=parsed,
                mode="reverse",
                source_english=source_english,
                reference_target=reference_target,
            )
            self.logger.log_attempt(record)
            self.scheduler.invalidate()
            used_keys.add(word.key)
            results.append(
                CompositionAttemptResult(
                    target_words=[word.word],
                    word_verdicts=dict(parsed.word_verdicts),
                    unknown_candidates=[
                        {"word": candidate.word, "gloss": candidate.gloss}
                        for candidate in parsed.unknown_candidates
                    ],
                )
            )

        if results:
            self._show_summary(results, debt_before, self.scheduler.debt_count())

    def _show_mode_menu(self) -> str:
        try:
            return self.ui.interactive_menu(
                self.config.ui_title,
                [
                    ("use_words", self.config.use_words_label),
                    ("reverse", self.config.reverse_label),
                    ("back", "Back to main menu"),
                ],
                "[↑↓] Navigate • [Enter] Select • [Esc] Go back",
                show_keys=False,
            )
        except KeyboardInterrupt:
            return "back"

    def _show_header(self, debt_before: int) -> None:
        content = (
            f"[bold #E67E50]{self.config.ui_title}[/bold #E67E50]\n"
            f"Daily set: {self.set_size} attempts  |  "
            f"Target words per attempt: {self.words_per_attempt}  |  "
            f"Production debt: {debt_before}"
        )
        self.ui.panel(
            content,
            title="Composition Practice",
            border_style="dark_orange",
            box_style=box.ROUNDED,
        )

    def _next_words(self, used_keys: set[str]) -> list[ScheduledWord]:
        words = self.scheduler.sample_words(self.words_per_attempt, exclude_keys=used_keys)
        if len(words) >= self.words_per_attempt:
            return words

        seen = {word.key for word in words}
        for word in self.scheduler.sample_words(self.words_per_attempt):
            if word.key in seen:
                continue
            words.append(word)
            seen.add(word.key)
            if len(words) >= self.words_per_attempt:
                break
        return words

    def create_prompt(
        self,
        mode: str,
        *,
        exclude_keys: Optional[set[str]] = None,
    ) -> Optional[CompositionPrompt]:
        """Select the next CLI-equivalent practice prompt without rendering it."""
        excluded = set(exclude_keys or ())
        if mode == "use_words":
            words = self._next_words(excluded)
            if not words:
                return None
            return CompositionPrompt(mode=mode, words=tuple(words))
        if mode == "reverse":
            word = self.scheduler.sample_reverse_word(exclude_keys=excluded)
            if word is None:
                return None
            reference_target, source_english = word.examples[0]
            return CompositionPrompt(
                mode=mode,
                words=(word,),
                source_english=source_english,
                reference_target=reference_target,
            )
        raise ValueError("Unsupported composition practice mode.")

    def grade_prompt(
        self,
        prompt: CompositionPrompt,
        user_text: str,
        *,
        session_id: Optional[str] = None,
        record_history: bool = True,
    ) -> Optional[CompositionFeedback]:
        """Grade and record one confirmed practice response."""
        text = (user_text or "").strip()
        if not text:
            return None
        if prompt.mode == "use_words":
            parsed = self._grade_attempt(list(prompt.words), text)
        elif prompt.mode == "reverse":
            word = prompt.words[0]
            parsed = self._grade_reverse_attempt(
                word,
                source_english=prompt.source_english or "",
                reference_target=prompt.reference_target or "",
                user_text=text,
            )
        else:
            raise ValueError("Unsupported composition practice mode.")
        if parsed is None:
            return None

        resolved_session_id = session_id or str(uuid4())
        record = self._build_history_record(
            session_id=resolved_session_id,
            words=list(prompt.words),
            user_text=text,
            parsed=parsed,
            mode=prompt.mode,
            source_english=prompt.source_english,
            reference_target=prompt.reference_target,
        )
        history_saved = self.logger.log_attempt(record) if record_history else False
        self.scheduler.invalidate()
        return CompositionFeedback(
            parsed=parsed,
            history_saved=history_saved,
            attempt_id=str(record["attempt_id"]),
            history_record=record,
        )

    def _show_target_words(self, words: list[ScheduledWord], attempt_number: int) -> None:
        lines = []
        for word in words:
            description = word.first_definition or "no definition"
            word_type = word.word_type or "Unknown"
            lines.append(
                f"- [bold #E67E50]{_escape_markup(word.word)}[/bold #E67E50] "
                f"([cyan]{_escape_markup(word_type)}[/cyan]): {_escape_markup(description)}"
            )
        self.ui.panel(
            "\n".join(lines),
            title=f"Attempt {attempt_number}: Use These Words",
            border_style="dark_orange",
            box_style=box.ROUNDED,
        )

    def _show_reverse_prompt(
        self,
        source_english: str,
        attempt_number: int,
        *,
        target_word: str,
    ) -> None:
        instruction = self.config.reverse_instruction_template.format(
            language=self.language_config.display_name,
            target_word=target_word,
        )
        content = (
            f"[bold #E67E50]{_escape_markup(self.config.reverse_source_label)}[/bold #E67E50]\n"
            f"{_escape_markup(source_english)}\n\n"
            f"[dim]{_escape_markup(instruction)}[/dim]"
        )
        self.ui.panel(
            content,
            title=f"Attempt {attempt_number}: {self.config.reverse_label}",
            border_style="dark_orange",
            box_style=box.ROUNDED,
        )

    def _collect_multiline_input(self) -> Optional[str]:
        cancel_label = input_cancel_label()
        input_instruction = self.config.input_instruction_template.format(
            language=self.language_config.display_name,
        )
        instructions = (
            f"[#E67E50]{_escape_markup(input_instruction)}[/#E67E50]\n"
            "[dim]- Press Enter on an empty line to submit.\n"
            f"- Press {cancel_label} to cancel this daily set.[/dim]"
        )
        self.ui.panel(instructions, border_style="dark_orange", box_style=box.ROUNDED)

        lines: list[str] = []
        while True:
            prompt = f"Composition ({cancel_label} to cancel): " if not lines else ""
            try:
                line = read_line(prompt)
            except (EOFError, KeyboardInterrupt):
                return None
            if line and "\x1b" in line:
                return None
            if not line.strip():
                if lines:
                    return "\n".join(lines).strip()
                return None
            lines.append(line.rstrip())

    def _warn_if_long(self, text: str) -> None:
        if _sentence_count(text) > self.config.max_sentences:
            self.ui.info(
                f"Longer than {self.config.max_sentences} sentences; grading it anyway.",
                accent="dim",
            )

    def _grade_attempt(
        self,
        words: list[ScheduledWord],
        user_text: str,
    ) -> Optional[ParsedCompositionResponse]:
        prompt = self._build_grading_prompt(words, user_text)
        response, _metrics = self.llm.query(
            prompt=prompt,
            progress_label=self.provider_label_fn(),
            on_exception=self.on_query_exception,
        )
        if not response:
            self.ui.error("Composition grader returned an empty response.")
            return None
        parsed = parse_composition_response(response)
        if parsed.parsing_warnings:
            for warning in parsed.parsing_warnings:
                self.ui.warning(warning)
        return parsed

    def _grade_reverse_attempt(
        self,
        word: ScheduledWord,
        *,
        source_english: str,
        reference_target: str,
        user_text: str,
    ) -> Optional[ParsedCompositionResponse]:
        prompt = self._build_reverse_grading_prompt(
            word,
            source_english=source_english,
            reference_target=reference_target,
            user_text=user_text,
        )
        response, _metrics = self.llm.query(
            prompt=prompt,
            progress_label=self.provider_label_fn(),
            on_exception=self.on_query_exception,
        )
        if not response:
            self.ui.error("Composition grader returned an empty response.")
            return None
        parsed = parse_composition_response(response)
        if parsed.parsing_warnings:
            for warning in parsed.parsing_warnings:
                self.ui.warning(warning)
        return parsed

    def _build_grading_prompt(self, words: list[ScheduledWord], user_text: str) -> str:
        target_words = "\n".join(f"- {word.word}" for word in words)
        word_details = "\n".join(
            f"- {word.word} ({word.word_type or 'Unknown'}): {word.first_definition or 'no definition'}"
            for word in words
        )
        return self.config.grading_prompt_template.format(
            language=self.language_config.display_name,
            target_words=target_words,
            word_details=word_details,
            user_text=user_text,
        )

    def _build_reverse_grading_prompt(
        self,
        word: ScheduledWord,
        *,
        source_english: str,
        reference_target: str,
        user_text: str,
    ) -> str:
        word_details = (
            f"- {word.word} ({word.word_type or 'Unknown'}): "
            f"{word.first_definition or 'no definition'}"
        )
        return self.config.reverse_grading_prompt_template.format(
            language=self.language_config.display_name,
            target_word=word.word,
            target_words=f"- {word.word}",
            word_details=word_details,
            source_english=source_english,
            reference_target=reference_target,
            user_text=user_text,
        )

    def _render_feedback(
        self,
        parsed: ParsedCompositionResponse,
        *,
        reference_target: Optional[str] = None,
    ) -> None:
        parts = [
            "[bold #E67E50]Corrected text[/bold #E67E50]",
            _escape_markup(parsed.corrected_text or "No corrected text returned."),
        ]
        if reference_target:
            parts.extend(
                [
                    "",
                    "[bold #E67E50]Stored original[/bold #E67E50]",
                    _escape_markup(reference_target),
                ]
            )
        parts.extend(["", "[bold #E67E50]Corrections[/bold #E67E50]"])
        if parsed.corrections:
            for correction in parsed.corrections:
                parts.append(
                    f"- [strike #ff6b6b]{_escape_markup(correction.original)}[/] "
                    f"-> [#51cf66]{_escape_markup(correction.replacement)}[/]"
                )
                if correction.why:
                    parts.append(f"  Why: {_escape_markup(correction.why)}")
                if correction.alternative:
                    parts.append(f"  Alternative: {_escape_markup(correction.alternative)}")
        else:
            parts.append("- none")

        parts.extend(["", "[bold #E67E50]Word verdicts[/bold #E67E50]"])
        if parsed.word_verdicts:
            for word, verdict in parsed.word_verdicts.items():
                parts.append(f"- {_escape_markup(word)}: {_format_verdict(verdict)}")
        else:
            parts.append("- none")

        if parsed.unknown_candidates:
            parts.extend(["", "[bold #E67E50]Unknown word candidates[/bold #E67E50]"])
            for candidate in parsed.unknown_candidates:
                gloss = f": {_escape_markup(candidate.gloss)}" if candidate.gloss else ""
                parts.append(f"- {_escape_markup(candidate.word)}{gloss}")

        if parsed.register:
            parts.extend(["", f"[bold #E67E50]Register[/bold #E67E50] {parsed.register}"])

        self.ui.panel(
            "\n".join(parts),
            title="Coach Feedback",
            border_style="dark_orange",
            box_style=box.ROUNDED,
        )

    def _build_history_record(
        self,
        *,
        session_id: str,
        words: list[ScheduledWord],
        user_text: str,
        parsed: ParsedCompositionResponse,
        mode: str = "use_words",
        source_english: Optional[str] = None,
        reference_target: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "attempt_id": str(uuid4()),
            "ts": _timestamp_z(),
            "mode": mode,
            "language": self.language_config.code,
            "target_words": [word.word for word in words],
            "source_english": source_english,
            "reference_target": reference_target,
            "english_gloss": parsed.english_gloss,
            "user_text": user_text,
            "corrected_text": parsed.corrected_text,
            "corrections": [
                {
                    "from": correction.original,
                    "to": correction.replacement,
                    "why": correction.why,
                    "alternative": correction.alternative,
                }
                for correction in parsed.corrections
            ],
            "word_verdicts": dict(parsed.word_verdicts),
            "unknown_candidates": [
                {"word": candidate.word, "gloss": candidate.gloss}
                for candidate in parsed.unknown_candidates
            ],
            "provider": self.provider_label_fn(),
            "session_id": session_id,
        }

    def _show_summary(
        self,
        results: list[CompositionAttemptResult],
        debt_before: int,
        debt_after: int,
    ) -> None:
        outcomes: dict[str, str] = {}
        unknown: dict[str, str] = {}
        for result in results:
            for word in result.target_words:
                verdict = result.word_verdicts.get(word, VERDICT_NOT_USED)
                outcomes[word] = _summary_outcome(verdict)
            for candidate in result.unknown_candidates:
                unknown[candidate["word"]] = candidate.get("gloss", "")

        lines = [f"Debt: {debt_before} -> {debt_after}", ""]
        lines.append("[bold #E67E50]Words this session[/bold #E67E50]")
        for word, outcome in outcomes.items():
            lines.append(f"- {_escape_markup(word)}: {outcome}")
        if unknown:
            lines.extend(["", "[bold #E67E50]Unknown candidates[/bold #E67E50]"])
            for word, gloss in unknown.items():
                suffix = f": {_escape_markup(gloss)}" if gloss else ""
                lines.append(f"- {_escape_markup(word)}{suffix}")

        self.ui.panel(
            "\n".join(lines),
            title="Composition Summary",
            border_style="dark_orange",
            box_style=box.ROUNDED,
        )
        self._offer_unknown_capture(unknown)

    def _already_in_vocab(self, word: str) -> bool:
        check = getattr(self.vocab_repo, "check_duplicate", None)
        if check is None:
            return False
        try:
            return check(word) is not None
        except Exception:
            return False

    def _offer_unknown_capture(self, unknown: dict[str, str]) -> None:
        """Offer to add the session's unknown-word candidates to the vocab list.

        Candidates already present in the list are filtered out; confirmed
        words run through the normal word-entry pipeline with the word
        pre-seeded. Words skipped due to errors are reported, never lost
        silently.
        """
        if not unknown or self.run_word_entry is None:
            return
        fresh = [
            (word, gloss)
            for word, gloss in unknown.items()
            if not self._already_in_vocab(word)
        ]
        if not fresh:
            self.ui.info(
                "All unknown candidates are already in your vocabulary list.",
                accent="dim",
            )
            return

        self.ui.panel(
            "The coach flagged words that are not in your list yet.\n"
            "Confirm each one to run it through the normal word-entry flow.",
            title="Capture Unknown Words",
            border_style="dark_orange",
            box_style=box.ROUNDED,
        )
        skipped: list[str] = []
        for index, (word, gloss) in enumerate(fresh):
            suffix = f" ({gloss})" if gloss else ""
            try:
                wanted = self.ui.confirm(
                    f"Add '{word}'{suffix} to your vocabulary?", default=False
                )
            except KeyboardInterrupt:
                skipped.extend(candidate for candidate, _ in fresh[index:])
                break
            if not wanted:
                continue
            try:
                self.run_word_entry(word)
            except Exception as exc:
                skipped.append(word)
                self.ui.warning(f"Could not add '{word}': {exc}")
        if skipped:
            self.ui.warning(
                "Skipped candidates (add manually later): " + ", ".join(skipped)
            )


def _timestamp_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sentence_count(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    terminal_count = sum(1 for char in stripped if char in ".!?")
    return max(1, terminal_count)


def _format_verdict(verdict: str) -> str:
    if verdict == VERDICT_CORRECT:
        return "[#51cf66]used idiomatically[/#51cf66]"
    if verdict == VERDICT_INCORRECT:
        return "[#ff6b6b]used incorrectly[/#ff6b6b]"
    return "[yellow3]not used[/yellow3]"


def _summary_outcome(verdict: str) -> str:
    if verdict == VERDICT_CORRECT:
        return "produced"
    if verdict == VERDICT_INCORRECT:
        return "failed"
    return "skipped"


def _escape_markup(text: object) -> str:
    return str(text).replace("[", r"\[")


__all__ = ["CompositionAttemptResult", "CompositionCoach"]
