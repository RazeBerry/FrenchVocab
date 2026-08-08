from __future__ import annotations

from rich.console import Console

from vocab_builder.core.vocab_repository import VocabRepository
from vocab_builder.languages import get_language_config
from vocab_builder.ui_helper import UIHelper


def _repo(path):
    language = get_language_config("fr")
    return VocabRepository(
        latex_file=path,
        entry_command=language.vocab.entry_command,
        language_config=language,
        ui=UIHelper(Console()),
        vocab_template=language.vocab,
    )


def test_repository_refreshes_after_another_process_writes(tmp_path):
    path = tmp_path / "FrenchVocab.tex"
    first = _repo(path)
    first.create_initial_tex_file()
    second = _repo(path)
    first.ensure_entries_loaded()
    second.ensure_entries_loaded()

    block = second.format_latex_entry(
        "éphémère",
        "adjective",
        ["Lasting for a very short time."],
        [("Une joie éphémère.", "A fleeting joy.")],
        entry_command=second.entry_command,
    )
    assert second.insert_entry_alphabetically(block, "éphémère")
    second.add_word_to_entries(
        "éphémère",
        "adjective",
        ["Lasting for a very short time."],
        [("Une joie éphémère.", "A fleeting joy.")],
    )

    assert first.check_duplicate("ephemere") == "éphémère"


def test_own_insert_does_not_mask_an_entry_from_another_process(tmp_path):
    path = tmp_path / "FrenchVocab.tex"
    first = _repo(path)
    first.create_initial_tex_file()
    second = _repo(path)
    first.ensure_entries_loaded()
    second.ensure_entries_loaded()

    for repo, word in ((second, "éphémère"), (first, "durable")):
        block = repo.format_latex_entry(
            word,
            "adjective",
            [f"Definition of {word}."],
            [],
            entry_command=repo.entry_command,
        )
        assert repo.insert_entry_alphabetically(block, word)
        repo.add_word_to_entries(word, "adjective", [f"Definition of {word}."], [])

    assert first.check_duplicate("ephemere") == "éphémère"
    assert first.check_duplicate("durable") == "durable"
