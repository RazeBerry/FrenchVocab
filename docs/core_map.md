# Core: CLI, vocabulary, Anki, persistence

Router: routes an intent to the document or code that owns it. It carries no
invariants; if a rule is written here, move it to its owner.

## Routes

| To | Read |
|---|---|
| Change the terminal client, menus, key handling or UI messaging | `docs/cli.md` |
| Change how headwords and text are stored, the capture workflow, corrections, or add a language | `docs/vocabulary.md` |
| Change Anki export, GUIDs or the export tracker | `docs/anki.md` |
| Write any persisted file, take a lock, or touch the save journal | `docs/persistence.md` |
| Change prompts, providers or the thinking level | `docs/llm_map.md` |

## Where the code lives
- `vocab_builder/cli/main.py` is the primary CLI entry point.
- `vocab_builder/cli/` contains bootstrap flow, interactive menu/navigation helpers, the local private-API terminal adapter, and compatibility shims.
- `vocab_builder/core/` contains application workflows (vocab ingestion, translators, auto translator, Anki export, LLM/provider lifecycle, history logging, menu/session UI helpers).
- `vocab_builder/languages/` contains language registry, validators, prompts, and LaTeX/Anki configuration (`english.py`, `english_tex.py`, `french.py`, `german.py`, `german_tex.py`).
- `vocab_builder/` root modules (`models.py`, `anki_exporter.py`, `latex_repository.py`, `llm_client.py`, `ui_helper.py`) provide shared infrastructure.
- `vocab_builder/compat.py` provides backward-compatible helpers for env vars, config paths, and keyring migration.
- `vocab_builder/diagnostics/` contains ESC latency tracing tools.
- `FrenchVocab.py` is a deprecated shim that delegates to `vocab_builder.cli.main`.
- `scripts/` contains utility and demo scripts, including `scripts/bulk_add.py` for operator-reviewed structured JSON vocabulary batches.
- `vocab_builder/cli/main.py` parses CLI args (`--language`, `--provider`, `--latex-file`, `--verbose`, `--esc-debug`, `--esc-debug-log`, `--eager-llm`).
- `vocab_builder/cli/bootstrap.py` builds language-specific `VocabBuilder` instances and language selection flow.
- `vocab_builder/core/menu_loop.py` drives menu orchestration; `vocab_builder/cli/menu.py` remains a compatibility shim.
- `pyproject.toml` defines the `vocabbuilder` console script entry point.
- `vocab.py` contains `VocabBuilder`, the main controller.
- `vocab_repository.py` handles LaTeX parsing, persistence, entry indexing, and counts.
- `translator.py` and `auto_translator.py` handle directional and intelligent translation flows.
- `text_utils.py` centralizes text normalization and input-type detection.
- `session_ui.py` builds menu/welcome/status screen content.
- `history_logger.py` writes append-only JSONL history.
- `startup_warmup.py` schedules the background LaTeX parse and owns the synchronous-load escape hatch.
- `protocols.py` defines structural typing contracts used by menu/workflow modules.
- `base.py` defines `LanguageConfig`, `TranslatorConfig`, `VocabTemplate`, and `AnkiConfig`.
- `__init__.py` lazily registers/loads language configs and resolves aliases with `get_language_config(code)`.
- `english.py`, `french.py`, and `german.py` define prompts, validators, learning-mode behavior, and Anki metadata.
- `english_tex.py` and `german_tex.py` contain dedicated language-specific LaTeX templates.
- `latex_templates.py`, `anki_shared_styles.py`, and `anki_themes.py` provide shared assets.
- `models.py` defines `WordEntry` and normalization helpers.
- `anki_exporter.py` contains Anki deck export utilities.
- `latex_repository.py` contains low-level LaTeX entry parsing helpers.
- `llm_client.py` defines provider clients and provider factory.
- `ai_prompts.py` and `ai_response_parser.py` contain prompt/response parsing logic.
- `ui_helper.py` centralizes Rich panels, prompts, status messages, and interactive wrappers.
- `compat.py` handles backward-compatible env var, config dir, and keyring service name migration.
