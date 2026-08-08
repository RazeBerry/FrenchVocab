from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

import pytest
from rich.console import Console

from vocab_builder.core.anki_manager import AnkiExportManager
from vocab_builder.core.translator import TranslatorCLI
from vocab_builder.core.vocab_repository import VocabRepository
from vocab_builder.languages import get_language_config


pytestmark = pytest.mark.skipif(
    "fork" not in mp.get_all_start_methods(),
    reason="These regressions exercise POSIX process and flock semantics.",
)


class _QuietUI:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


class _RepoStub:
    word_entries: dict = {}

    def ensure_entries_loaded(self) -> None:
        return None

    @staticmethod
    def normalize_word(word: str) -> str:
        return word.casefold()

    def get_all_latex_entries(self) -> set[str]:
        return set()


def _repo(path: Path) -> VocabRepository:
    language = get_language_config("fr")
    return VocabRepository(
        latex_file=path,
        entry_command=language.vocab.entry_command,
        language_config=language,
        ui=_QuietUI(),
        vocab_template=language.vocab,
    )


def _insert_worker(
    path_text: str,
    lock_tmp_text: str,
    word: str,
    start,
    result,
) -> None:
    import vocab_builder.core.file_safety as file_safety

    Path(lock_tmp_text).mkdir(parents=True, exist_ok=True)
    file_safety.tempfile.tempdir = lock_tmp_text
    repo = _repo(Path(path_text))
    block = repo.format_latex_entry(
        word,
        "noun",
        [f"Definition {word}"],
        [],
        entry_command=repo.entry_command,
    )
    start.wait()
    result.put(repo.insert_entry_alphabetically(block, word))


def _merge_worker(path_text: str, definition: str, start, result) -> None:
    repo = _repo(Path(path_text))
    repo.ensure_entries_loaded()
    start.wait()
    result.put(
        repo.merge_into_existing(
            "concurrence",
            "noun",
            [definition],
            [],
        )
    )


def _anki_worker(state_text: str, word: str, ready, start, result) -> None:
    state_path = Path(state_text)
    manager = AnkiExportManager(
        _QuietUI(),
        get_language_config("fr"),
        _RepoStub(),  # type: ignore[arg-type]
        state_path,
        state_path.parent,
    )
    manager.exported_words = {word}
    ready.put(word)
    start.wait()
    result.put(manager.save_exported_words())


def _anki_mutation_worker(
    state_text: str,
    operation: str,
    word: str,
    ready,
    start,
    result,
) -> None:
    state_path = Path(state_text)
    manager = AnkiExportManager(
        _QuietUI(),
        get_language_config("fr"),
        _RepoStub(),  # type: ignore[arg-type]
        state_path,
        state_path.parent,
    )
    if operation == "add":
        manager.exported_words.add(word)
    else:
        manager.exported_words.discard(word)
    ready.put(operation)
    start.wait()
    result.put(manager.save_exported_words())


def _translator_worker(path_text: str, target: str, ready, start, result) -> None:
    config = get_language_config("fr").eng_to_target
    assert config is not None
    translator = TranslatorCLI(
        Console(),
        None,
        config,
        latex_file_path=Path(path_text),
    )
    translator.ui = _QuietUI()
    translator.confirm_translation = lambda *_args, **_kwargs: True  # type: ignore[method-assign]
    ready.put(target)
    start.wait()
    result.put(
        translator.translate_and_save(
            "the same source sentence",
            provided_translation=target,
        )
    )


def _context():
    return mp.get_context("fork")


def _join(processes) -> None:
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0


def test_phone_and_cli_lock_identity_survives_private_tmp_namespaces(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("VOCABBUILDER_CONFIG_DIR", str(tmp_path))
    path = tmp_path / "FrenchVocab.tex"
    _repo(path).create_initial_tex_file()
    context = _context()
    start = context.Event()
    result = context.Queue()
    words = [f"mot{index:02d}" for index in range(12)]
    processes = [
        context.Process(
            target=_insert_worker,
            args=(
                str(path),
                str(tmp_path / f"private-tmp-{index}"),
                word,
                start,
                result,
            ),
        )
        for index, word in enumerate(words)
    ]
    for process in processes:
        process.start()
    start.set()
    _join(processes)

    assert all(result.get(timeout=2) for _ in processes)
    reloaded = _repo(path)
    reloaded.ensure_entries_loaded()
    present = {entry["word"].casefold() for entry in reloaded.word_entries.values()}
    assert set(words) <= present


def test_concurrent_merges_recompute_inside_the_file_transaction(tmp_path, monkeypatch):
    monkeypatch.setenv("VOCABBUILDER_CONFIG_DIR", str(tmp_path))
    path = tmp_path / "FrenchVocab.tex"
    repo = _repo(path)
    repo.create_initial_tex_file()
    base = repo.format_latex_entry(
        "concurrence",
        "noun",
        ["base"],
        [],
        entry_command=repo.entry_command,
    )
    assert repo.insert_entry_alphabetically(base, "concurrence")

    context = _context()
    start = context.Event()
    result = context.Queue()
    additions = ["definition from session a", "definition from session b"]
    processes = [
        context.Process(target=_merge_worker, args=(str(path), addition, start, result))
        for addition in additions
    ]
    for process in processes:
        process.start()
    start.set()
    _join(processes)

    assert all(result.get(timeout=2) for _ in processes)
    reloaded = _repo(path)
    reloaded.ensure_entries_loaded()
    final_definitions = reloaded.word_entries["concurrence"]["definitions_list"]
    assert final_definitions[0] == "base"
    assert set(final_definitions[1:]) == set(additions)


def test_concurrent_anki_state_additions_are_three_way_merged(tmp_path, monkeypatch):
    monkeypatch.setenv("VOCABBUILDER_CONFIG_DIR", str(tmp_path))
    state = tmp_path / "exported_words_fr.json"
    state.write_text(
        json.dumps({"words": [], "deck_version": None, "entry_order": []}),
        encoding="utf-8",
    )
    context = _context()
    ready = context.Queue()
    start = context.Event()
    result = context.Queue()
    words = ["session-a", "session-b"]
    processes = [
        context.Process(target=_anki_worker, args=(str(state), word, ready, start, result))
        for word in words
    ]
    for process in processes:
        process.start()
    for _ in processes:
        ready.get(timeout=5)
    start.set()
    _join(processes)

    assert all(result.get(timeout=2) for _ in processes)
    assert set(json.loads(state.read_text(encoding="utf-8"))["words"]) == set(words)


def test_concurrent_anki_addition_and_removal_do_not_overwrite_each_other(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("VOCABBUILDER_CONFIG_DIR", str(tmp_path))
    state = tmp_path / "exported_words_fr.json"
    state.write_text(
        json.dumps(
            {
                "words": ["keep", "remove"],
                "deck_version": None,
                "entry_order": [],
            }
        ),
        encoding="utf-8",
    )
    context = _context()
    ready = context.Queue()
    start = context.Event()
    result = context.Queue()
    processes = [
        context.Process(
            target=_anki_mutation_worker,
            args=(str(state), "add", "new", ready, start, result),
        ),
        context.Process(
            target=_anki_mutation_worker,
            args=(str(state), "remove", "remove", ready, start, result),
        ),
    ]
    for process in processes:
        process.start()
    for _ in processes:
        ready.get(timeout=5)
    start.set()
    _join(processes)

    assert all(result.get(timeout=2) for _ in processes)
    assert set(json.loads(state.read_text(encoding="utf-8"))["words"]) == {
        "keep",
        "new",
    }


def test_translator_rechecks_duplicate_after_taking_commit_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("VOCABBUILDER_CONFIG_DIR", str(tmp_path))
    path = tmp_path / "EnglishToFrench.tex"
    context = _context()
    ready = context.Queue()
    start = context.Event()
    result = context.Queue()
    processes = [
        context.Process(
            target=_translator_worker,
            args=(str(path), target, ready, start, result),
        )
        for target in ("traduction a", "traduction b")
    ]
    for process in processes:
        process.start()
    for _ in processes:
        ready.get(timeout=5)
    start.set()
    _join(processes)

    assert all(result.get(timeout=2) for _ in processes)
    config = get_language_config("fr").eng_to_target
    assert config is not None
    reloaded = TranslatorCLI(Console(), None, config, latex_file_path=path)
    assert len(reloaded.pairs) == 1


def test_backup_script_takes_catalog_lock_before_archiving():
    script = (
        Path(__file__).parents[1]
        / "scripts"
        / "deploy"
        / "backup_mobile_data.sh"
    ).read_text(encoding="utf-8")

    assert "VOCABBUILDER_DATA_DIR" in script
    assert script.index('flock -x 9') < script.index("tar \\")
