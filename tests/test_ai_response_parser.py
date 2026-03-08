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
