"""Parser for sectioned composition-grader responses."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from vocab_builder.core.composition_scheduler import VALID_VERDICTS


@dataclass(frozen=True)
class CompositionCorrection:
    original: str
    replacement: str
    why: str = ""
    alternative: str = ""


@dataclass(frozen=True)
class UnknownWordCandidate:
    word: str
    gloss: str = ""


@dataclass(frozen=True)
class ParsedCompositionResponse:
    corrected_text: str
    corrections: list[CompositionCorrection]
    word_verdicts: dict[str, str]
    unknown_candidates: list[UnknownWordCandidate]
    register: str
    parsing_warnings: list[str]
    english_gloss: Optional[str] = None


_HEADER_PATTERN = re.compile(
    r"(?im)^\s*(Corrected Text|English Gloss|Corrections|Word Verdicts|Unknown Word Candidates|Register)\s*:\s*"
)


def parse_composition_response(text: str) -> ParsedCompositionResponse:
    """Parse a plain-text grader response without raising on malformed sections."""
    warnings: list[str] = []
    sections = _extract_sections(text or "")

    corrected_text = sections.get("corrected text", "").strip()
    if not corrected_text:
        warnings.append("Could not parse corrected text from grader response")
    english_gloss = _first_meaningful_line(sections.get("english gloss", "")) or None

    corrections = _parse_corrections(sections.get("corrections", ""), warnings)
    verdicts = _parse_word_verdicts(sections.get("word verdicts", ""), warnings)
    unknown = _parse_unknown_candidates(sections.get("unknown word candidates", ""), warnings)

    register = _first_meaningful_line(sections.get("register", ""))
    if not register:
        warnings.append("Could not parse register assessment from grader response")

    return ParsedCompositionResponse(
        corrected_text=corrected_text,
        corrections=corrections,
        word_verdicts=verdicts,
        unknown_candidates=unknown,
        register=register,
        parsing_warnings=warnings,
        english_gloss=english_gloss,
    )


def _extract_sections(text: str) -> dict[str, str]:
    matches = list(_HEADER_PATTERN.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1).strip().lower()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[name] = text[start:end].strip()
    return sections


def _parse_corrections(section: str, warnings: list[str]) -> list[CompositionCorrection]:
    if not section:
        warnings.append("Could not parse corrections from grader response")
        return []
    if _is_none(section):
        return []

    corrections: list[CompositionCorrection] = []
    current: dict[str, str] | None = None
    unparsed: list[str] = []

    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        replacement = _parse_replacement_line(line)
        if replacement is not None:
            if current is not None:
                corrections.append(_correction_from_parts(current))
            original, corrected = replacement
            current = {"from": original, "to": corrected, "why": "", "alternative": ""}
            continue
        if current is None:
            unparsed.append(line)
            continue
        label, value = _parse_label_line(line)
        if label == "why":
            current["why"] = value
        elif label == "alternative":
            current["alternative"] = value
        else:
            unparsed.append(line)

    if current is not None:
        corrections.append(_correction_from_parts(current))

    if not corrections:
        warnings.append("Could not parse corrections from grader response")
    if unparsed:
        warnings.append(f"Skipped {len(unparsed)} unrecognized correction line(s)")
    return corrections


def _parse_replacement_line(line: str) -> Optional[tuple[str, str]]:
    line = re.sub(r"^\s*(?:[-*]\s*|\d+\.\s*)", "", line).strip()
    match = re.match(r"(.+?)\s*(?:->|→)\s*(.+)$", line)
    if not match:
        return None
    original = _strip_wrapping_quotes(match.group(1).strip())
    corrected = _strip_wrapping_quotes(match.group(2).strip())
    if not original and not corrected:
        return None
    return original, corrected


def _parse_label_line(line: str) -> tuple[str, str]:
    match = re.match(r"([A-Za-z ]+)\s*:\s*(.*)$", line)
    if not match:
        return "", line
    label = match.group(1).strip().lower().replace(" ", "_")
    return label, match.group(2).strip()


def _correction_from_parts(parts: dict[str, str]) -> CompositionCorrection:
    return CompositionCorrection(
        original=parts.get("from", ""),
        replacement=parts.get("to", ""),
        why=parts.get("why", ""),
        alternative=parts.get("alternative", ""),
    )


def _parse_word_verdicts(section: str, warnings: list[str]) -> dict[str, str]:
    if not section:
        warnings.append("Could not parse word verdicts from grader response")
        return {}

    verdicts: dict[str, str] = {}
    invalid_count = 0
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^\s*(?:[-*]\s*|\d+\.\s*)", "", line).strip()
        match = re.match(r"(.+?)\s*[:=-]\s*(.+)$", line)
        if not match:
            invalid_count += 1
            continue
        word = _strip_wrapping_quotes(match.group(1).strip())
        verdict = _normalize_verdict(match.group(2))
        if not word or verdict is None:
            invalid_count += 1
            continue
        verdicts[word] = verdict

    if not verdicts:
        warnings.append("Could not parse word verdicts from grader response")
    if invalid_count:
        warnings.append(f"Skipped {invalid_count} invalid word verdict line(s)")
    return verdicts


def _parse_unknown_candidates(section: str, warnings: list[str]) -> list[UnknownWordCandidate]:
    if not section:
        warnings.append("Could not parse unknown word candidates from grader response")
        return []
    if _is_none(section):
        return []

    candidates: list[UnknownWordCandidate] = []
    invalid_count = 0
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^\s*(?:[-*]\s*|\d+\.\s*)", "", line).strip()
        if _is_none(line):
            continue
        if ":" in line:
            word, gloss = line.split(":", 1)
        else:
            word, gloss = line, ""
        word = _strip_wrapping_quotes(word.strip())
        gloss = gloss.strip()
        if not word:
            invalid_count += 1
            continue
        candidates.append(UnknownWordCandidate(word=word, gloss=gloss))

    if invalid_count:
        warnings.append(f"Skipped {invalid_count} invalid unknown-word candidate line(s)")
    return candidates


def _normalize_verdict(value: object) -> Optional[str]:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in VALID_VERDICTS else None


def _strip_wrapping_quotes(text: str) -> str:
    text = text.strip()
    quote_pairs = (('"', '"'), ("'", "'"), ("“", "”"), ("«", "»"), ("„", "“"))
    for left, right in quote_pairs:
        if text.startswith(left) and text.endswith(right) and len(text) >= 2:
            return text[1:-1].strip()
    return text


def _first_meaningful_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _is_none(text: str) -> bool:
    normalized = text.strip().lower()
    return normalized in {"none", "no", "n/a", "na", "nothing", "- none"}


__all__ = [
    "CompositionCorrection",
    "ParsedCompositionResponse",
    "UnknownWordCandidate",
    "parse_composition_response",
]
