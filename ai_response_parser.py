"""Utilities for parsing structured AI responses into vocabulary components."""

from dataclasses import dataclass
from typing import List, Tuple
import re


@dataclass
class ParsedAIResponse:
    """Normalized representation of an AI-generated vocabulary payload."""

    word_type: List[str]
    definitions: List[str]
    examples: List[Tuple[str, str]]


_WORD_TYPE_PATTERN = re.compile(r"Word Type:\s*(.*?)\nDefinitions:", re.DOTALL)
_DEFINITIONS_SECTION_PATTERN = re.compile(r"Definitions:(.*?)Examples:", re.DOTALL)
_DEFINITION_ITEM_PATTERN = re.compile(r"[a-z]\.\s*(.*)")
_EXAMPLES_SECTION_PATTERN = re.compile(r"Examples:(.*)", re.DOTALL)
_EXAMPLE_PATTERN = re.compile(r"(\d+\.\s*(.*?)\n\s*(.*?)(?=\n\d+\.|\Z))", re.DOTALL)


def parse_ai_response_text(response: str) -> ParsedAIResponse:
    """Parse the raw AI response into discrete vocabulary components."""
    word_type_match = _WORD_TYPE_PATTERN.search(response)
    if word_type_match:
        word_type_string = word_type_match.group(1).strip()
        word_type = [word_type_string] if word_type_string else ["Unknown"]
    else:
        word_type = ["Unknown"]

    definitions: List[str] = []
    definitions_match = _DEFINITIONS_SECTION_PATTERN.search(response)
    if definitions_match:
        definitions_text = definitions_match.group(1)
        definitions = [d.strip() for d in _DEFINITION_ITEM_PATTERN.findall(definitions_text) if d.strip()]

    examples: List[Tuple[str, str]] = []
    examples_match = _EXAMPLES_SECTION_PATTERN.search(response)
    if examples_match:
        examples_text = examples_match.group(1)
        raw_examples = _EXAMPLE_PATTERN.findall(examples_text)
        examples = [
            (french.strip(), english.strip().strip("[]"))
            for _, french, english in raw_examples
        ]

    return ParsedAIResponse(word_type=word_type, definitions=definitions, examples=examples)
