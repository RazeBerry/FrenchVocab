"""Utilities for parsing structured AI responses into vocabulary components."""

from dataclasses import dataclass
from typing import List, Optional, Tuple
import re


@dataclass
class ParsedAIResponse:
    """Normalized representation of an AI-generated vocabulary payload."""

    word_type: List[str]
    definitions: List[str]
    examples: List[Tuple[str, str]]
    parsing_warnings: List[str]  # Tracks what couldn't be parsed


# Known section headers for robust extraction
_KNOWN_HEADERS = ["Word Type:", "Definitions:", "Examples:", "Spelling Check:", "Correctly Spelt Word:"]


def _extract_section(text: str, header: str, next_headers: Optional[List[str]] = None) -> str:
    """Extract section content, stopping at any next header or end of text.

    This decouples section extraction so each section can be parsed independently.
    """
    header_lower = header.lower()
    text_lower = text.lower()
    start_idx = text_lower.find(header_lower)
    if start_idx == -1:
        return ""

    # Move past the header
    content_start = start_idx + len(header)

    # Find where the section ends (next header or end of text)
    end_idx = len(text)
    if next_headers is None:
        next_headers = _KNOWN_HEADERS

    for next_header in next_headers:
        next_lower = next_header.lower()
        if next_lower == header_lower:
            continue
        idx = text_lower.find(next_lower, content_start)
        if idx != -1 and idx < end_idx:
            end_idx = idx

    return text[content_start:end_idx].strip()


def _parse_word_type(response: str) -> List[str]:
    """Extract word type from response."""
    section = _extract_section(response, "Word Type:")
    if section:
        # Take just the first line (word type should be single line)
        first_line = section.split('\n')[0].strip()
        if first_line:
            return [first_line]
    return ["Unknown"]


def _parse_definitions(response: str) -> List[str]:
    """Extract definitions with fallback for multiple formats."""
    section = _extract_section(response, "Definitions:")
    if not section:
        return []

    definitions: List[str] = []

    # Try format 1: a. b. c. (lowercase letter + period)
    letter_pattern = re.compile(r"[a-z]\.\s*(.+?)(?=\n[a-z]\.|$)", re.DOTALL)
    matches = letter_pattern.findall(section)
    if matches:
        definitions = [d.strip() for d in matches if d.strip()]
        if definitions:
            return definitions

    # Try format 2: 1. 2. 3. (number + period)
    number_pattern = re.compile(r"\d+\.\s*(.+?)(?=\n\d+\.|$)", re.DOTALL)
    matches = number_pattern.findall(section)
    if matches:
        definitions = [d.strip() for d in matches if d.strip()]
        if definitions:
            return definitions

    # Try format 3: - bullet points
    bullet_pattern = re.compile(r"[-•]\s*(.+?)(?=\n[-•]|$)", re.DOTALL)
    matches = bullet_pattern.findall(section)
    if matches:
        definitions = [d.strip() for d in matches if d.strip()]
        if definitions:
            return definitions

    # Fallback: treat each non-empty line as a definition
    lines = [line.strip() for line in section.split('\n') if line.strip()]
    if lines:
        return lines

    return []


def _parse_examples(response: str) -> List[Tuple[str, str]]:
    """Extract examples with fallback for multiple formats."""
    section = _extract_section(response, "Examples:")
    if not section:
        return []

    examples: List[Tuple[str, str]] = []

    # Try format 1: numbered with newline between source and translation
    # e.g., "1. French sentence\n   [English translation]"
    numbered_pattern = re.compile(r"\d+\.\s*(.*?)\n\s*(.*?)(?=\n\d+\.|\Z)", re.DOTALL)
    matches = numbered_pattern.findall(section)
    if matches:
        for source, translation in matches:
            source = source.strip()
            translation = translation.strip().strip("[]()").strip()
            if source:
                examples.append((source, translation))
        if examples:
            return examples

    # Try format 2: each example on one line with parenthesized translation
    # e.g., "- French sentence (English translation)"
    paren_pattern = re.compile(r"(?:[-•\d]+\.?\s*)?(.*?)\s*\(([^)]+)\)")
    for line in section.split('\n'):
        line = line.strip()
        if not line:
            continue
        match = paren_pattern.search(line)
        if match:
            source = match.group(1).strip()
            translation = match.group(2).strip()
            if source:
                examples.append((source, translation))

    if examples:
        return examples

    # Try format 3: each example on one line with bracketed translation
    # e.g., "- French sentence [English translation]"
    bracket_pattern = re.compile(r"(?:[-•\d]+\.?\s*)?(.*?)\s*\[([^\]]+)\]")
    for line in section.split('\n'):
        line = line.strip()
        if not line:
            continue
        match = bracket_pattern.search(line)
        if match:
            source = match.group(1).strip()
            translation = match.group(2).strip()
            if source:
                examples.append((source, translation))

    return examples


def parse_ai_response_text(response: str) -> ParsedAIResponse:
    """Parse the raw AI response into discrete vocabulary components.

    Uses robust section extraction that doesn't require all sections to be present.
    Includes fallback parsing for alternative formats (numbered, bulleted, etc.).
    """
    parsing_warnings: List[str] = []

    word_type = _parse_word_type(response)
    if word_type == ["Unknown"]:
        parsing_warnings.append("Could not parse word type; defaulting to 'Unknown'")

    definitions = _parse_definitions(response)
    if not definitions:
        parsing_warnings.append("Could not parse any definitions from AI response")

    examples = _parse_examples(response)
    if not examples:
        parsing_warnings.append("Could not parse any examples from AI response")

    return ParsedAIResponse(
        word_type=word_type,
        definitions=definitions,
        examples=examples,
        parsing_warnings=parsing_warnings,
    )
