import vocab_builder.ai_response_parser as arp


def test_parse_ai_response_text_normalizes_payload():
    response = (
        "Word Type: verb\n"
        "Definitions:\n"
        "a. to eat\n"
        "b. to consume\n"
        "Examples:\n"
        "1. Je mange une pomme.\n( I eat an apple. )\n"
        "2. Nous mangeons ensemble.\n( We dine together. )\n"
    )

    parsed = arp.parse_ai_response_text(response)

    assert parsed.word_type == ['verb']
    assert parsed.definitions == ['to eat', 'to consume']
    assert parsed.examples[0][0] == 'Je mange une pomme.'
    assert 'I eat an apple' in parsed.examples[0][1]


def test_parse_ai_response_text_handles_missing_sections():
    response = "Just some free-form answer without markers."

    parsed = arp.parse_ai_response_text(response)

    assert parsed.word_type == ['Unknown']
    assert parsed.definitions == []
    assert parsed.examples == []


def test_parse_ai_response_accepts_aligned_flexible_cardinality_and_usage_note():
    response = """Word Type: noun
Definitions:
a. Bulky household waste collected separately by a municipality.
b. Usage note: Usually used in the plural for discarded furniture and appliances.
Examples:
1. La mairie ramasse les encombrants mardi.
(The council collects bulky waste on Tuesday.)
2. Ce vieux canapé partira avec les encombrants.
(This old sofa will go out with the bulky-waste collection.)
"""

    parsed = arp.parse_ai_response_text(response)

    assert len(parsed.definitions) == 2
    assert parsed.definitions[1].startswith("Usage note:")
    assert len(parsed.examples) == 2
    assert parsed.contract_issues == []
    assert parsed.parsing_warnings == []


def test_parse_ai_response_reports_misalignment_without_truncating_content():
    response = """Word Type: verb
Definitions:
a. to help someone out of a practical difficulty
b. to repair a vehicle temporarily
Examples:
1. Tu peux me dépanner ce soir ?
(Can you help me out tonight?)
"""

    parsed = arp.parse_ai_response_text(response)

    assert parsed.definitions == [
        "to help someone out of a practical difficulty",
        "to repair a vehicle temporarily",
    ]
    assert parsed.examples == [
        ("Tu peux me dépanner ce soir ?", "Can you help me out tonight?")
    ]
    assert len(parsed.contract_issues) == 1
    assert "one example per definition" in parsed.contract_issues[0]
    assert parsed.contract_issues[0] in parsed.parsing_warnings


def test_parse_ai_response_reports_more_than_three_items_without_truncating():
    definitions = "\n".join(f"{label}. sense {index}" for index, label in enumerate("abcd", 1))
    examples = "\n".join(
        f"{index}. Exemple {index}.\n(Example {index}.)"
        for index in range(1, 5)
    )

    parsed = arp.parse_ai_response_text(
        f"Word Type: noun\nDefinitions:\n{definitions}\nExamples:\n{examples}\n"
    )

    assert len(parsed.definitions) == 4
    assert len(parsed.examples) == 4
    assert len(parsed.contract_issues) == 2
    assert any("at most 3 definition" in issue for issue in parsed.contract_issues)
    assert any("at most 3 examples" in issue for issue in parsed.contract_issues)
