# Repository Guidelines

## Sync Requirement
- `AGENTS.md` and `CLAUDE.md` must stay byte-for-byte identical.
- Update both files in the same change.
- Run `pytest tests/test_agent_docs_sync.py` to validate alignment.

## Project Overview
VocabBuilder is an AI-assisted CLI for building bilingual vocabulary lists, generating LaTeX documents, and exporting Anki decks. The current app supports French (`fr`) and German (`de`), has Rich-based keyboard navigation, and integrates with Google Gemini or Anthropic Claude. Install with `pip install vocab-builder` and run `vocabbuilder`.

## Project Structure and Module Organization
- All source code lives under the `vocab_builder/` package.
- `vocab_builder/cli/main.py` is the primary CLI entry point.
- `vocab_builder/cli/` contains bootstrap flow, interactive menu/navigation helpers, and compatibility shims.
- `vocab_builder/core/` contains application workflows (vocab ingestion, translators, auto translator, Anki export, LLM/provider lifecycle, history logging, menu/session UI helpers).
- `vocab_builder/core/providers/manager.py` encapsulates provider selection, credential validation, and secure storage.
- `vocab_builder/languages/` contains language registry, validators, prompts, and LaTeX/Anki configuration (`french.py`, `german.py`, `german_tex.py`).
- `vocab_builder/` root modules (`models.py`, `anki_exporter.py`, `latex_repository.py`, `llm_client.py`, `ui_helper.py`) provide shared infrastructure.
- `vocab_builder/compat.py` provides backward-compatible helpers for env vars, config paths, and keyring migration.
- `vocab_builder/diagnostics/` contains ESC latency tracing tools.
- `FrenchVocab.py` is a deprecated shim that delegates to `vocab_builder.cli.main`.
- `scripts/` contains utility and demo scripts, including `scripts/bulk_add.py` for operator-reviewed structured JSON vocabulary batches.
- `tests/` is a pytest suite (`test_*.py`) for architecture boundaries, onboarding, translators, language config, exporters, and UI behavior.

## Build, Test, and Development Commands
```bash
# Install (editable / development)
pip install -e .

# Run the CLI
vocabbuilder --help
vocabbuilder --language fr
vocabbuilder --language de
vocabbuilder --language fr --provider gemini
vocabbuilder --language fr --provider claude
vocabbuilder --language fr --latex-file ./FrenchVocab.custom.tex
vocabbuilder --language fr --eager-llm
python -m vocab_builder --help

# Diagnostics and demos
vocabbuilder --esc-debug
vocabbuilder --esc-debug --esc-debug-log /tmp/esc_latency.log
python scripts/demo_guided_onboarding.py

# Operator bulk-add workflow
python scripts/bulk_add.py --language fr --file entries.json --dry-run
python scripts/bulk_add.py --language fr --file entries.json --json

# Tests
pytest
pytest tests/test_sentence_flow.py
pytest tests/test_agent_docs_sync.py
pytest -k "anki"
```

## Architecture

### Entry Point and Bootstrap
- `vocab_builder/cli/main.py` parses CLI args (`--language`, `--provider`, `--latex-file`, `--verbose`, `--esc-debug`, `--esc-debug-log`, `--eager-llm`).
- `vocab_builder/cli/bootstrap.py` builds language-specific `VocabBuilder` instances and language selection flow.
- `vocab_builder/core/menu_loop.py` drives menu orchestration; `vocab_builder/cli/menu.py` remains a compatibility shim.
- `pyproject.toml` defines the `vocabbuilder` console script entry point.

### Core Application (`vocab_builder/core/`)
- `vocab.py` contains `VocabBuilder`, the main controller.
- `vocab_repository.py` handles LaTeX parsing, persistence, entry indexing, and counts.
- `word_entry_workflow.py` orchestrates end-to-end word capture and save behavior, including explicit saved/routed/skipped outcomes so failed routing or merge paths never masquerade as successful saves.
- `translator.py` and `auto_translator.py` handle directional and intelligent translation flows.
- `text_utils.py` centralizes text normalization and input-type detection.
- `session_ui.py` builds menu/welcome/status screen content.
- `anki_manager.py` coordinates export state and Anki generation.
- `llm_coordinator.py` manages provider initialization lifecycle, degraded mode, and usage metrics, and uses generation-guarded background init so stale workers cannot overwrite newer provider changes.
- `history_logger.py` writes append-only JSONL history.
- `file_safety.py` provides atomic file operations and backup/restore support.
- `protocols.py` defines structural typing contracts used by menu/workflow modules.

### Provider and Credential System
- `vocab_builder/core/providers/manager.py` owns provider metadata, setup wizard flows, and storage destinations.
- Credential resolution is: environment variable first (including values loaded from `.env`), then keyring fallback, then interactive setup.
- `.env` path resolution order is: `VOCABBUILDER_CONFIG_DIR/.env`, then writable project `.env`, then `~/.vocabbuilder/.env` (falls back to `~/.frenchvocab/.env` for legacy installs).
- Plaintext `.env` fallback writes are atomic, best-effort permission-hardened, and do not retain a stale backup after a successful key rotation.
- Keyring service name is `vocab_builder` (silently migrates from legacy `french_vocab_builder`).

### Language System (`vocab_builder/languages/`)
- `base.py` defines `LanguageConfig`, `TranslatorConfig`, `VocabTemplate`, and `AnkiConfig`.
- `__init__.py` lazily registers/loads language configs and resolves aliases with `get_language_config(code)`.
- `french.py` and `german.py` define prompts, validators, translator configs, and Anki metadata.
- `german_tex.py` contains dedicated German LaTeX templates.
- `latex_templates.py`, `anki_shared_styles.py`, and `anki_themes.py` provide shared assets.

### Shared Modules (`vocab_builder/`)
- `models.py` defines `WordEntry` and normalization helpers.
- `anki_exporter.py` contains Anki deck export utilities.
- `latex_repository.py` contains low-level LaTeX entry parsing helpers.
- `llm_client.py` defines provider clients and provider factory.
- `ai_prompts.py` and `ai_response_parser.py` contain prompt/response parsing logic.
- `ui_helper.py` centralizes Rich panels, prompts, status messages, and interactive wrappers.
- `compat.py` handles backward-compatible env var, config dir, and keyring service name migration.
- Keep UI messaging declarative via `UIHelper` methods and avoid bare `print()` in new code.

## Coding Style and Naming Conventions
- Follow PEP 8 with 4-space indentation.
- Use `snake_case` for functions/variables and `PascalCase` for classes.
- Prefer dataclasses for config-style objects and use type hints throughout.
- Use ASCII by default; introduce Unicode only when lexically required (for example language samples and LaTeX templates).

## Key Patterns

### Adding a New Language
1. Create `vocab_builder/languages/<lang>.py` with a `LanguageConfig` (copy `french.py` or `german.py`).
2. Register it through `vocab_builder/languages/__init__.py`.
3. Add language-specific vocab and translator templates (new `*_tex.py` module if needed).
4. Provide Anki config/templates and optional auto-translator prompt tokens.

### UI Messaging
Route status messaging through `UIHelper` methods:
```python
self.ui.success("Entry saved!")
self.ui.error("Failed", with_panel=True)
self.ui.warning("Duplicate detected")
self.ui.info("Processing...", accent="dim")
self.ui.panel(content, title="Title", border_style="dark_orange")
```

### Interactive Menus
```python
choice = self.ui.interactive_menu(
    "Menu Title",
    [("key1", "Label 1"), ("key2", "Label 2")],
    "Helper text for navigation",
)
```

### Provider Credential Flow
1. Load `.env` from the resolved config path when available.
2. Resolve credentials from environment variables before keyring.
3. Fall back to keyring lookup when env credentials are missing/invalid.
4. Launch guided/advanced interactive setup when credentials are still unavailable.

## Environment Variables
All variables use the `VOCABBUILDER_*` prefix. Legacy `FRENCHVOCAB_*` and `FRENCH_VOCAB_*` names are still recognized via `vocab_builder/compat.py` with deprecation warnings.

- `GEMINI_API_KEY` / `ANTHROPIC_API_KEY`: Provider API credentials.
- `VOCABBUILDER_CLAUDE_MODEL`: Override Claude model ID (default `claude-sonnet-4-6`).
- `VOCABBUILDER_GEMINI_MODEL`: Override Gemini model ID (default `gemini-3-flash-preview`).
- `VOCABBUILDER_CONFIG_DIR`: Override directory used for `.env` storage/loading.
- `VOCABBUILDER_SKIP_KEYRING=1`: Disable keyring lookups/storage.
- `VOCABBUILDER_FORCE_SYNC_LOAD=1`: Force synchronous loading (useful in tests).
- `VOCABBUILDER_ESC_SEQUENCE_TIMEOUT`: ESC key sequence timeout in seconds (default `0.03`).
- `VOCABBUILDER_ESC_DEBUG=1`: Enable ESC latency tracing.
- `VOCABBUILDER_ESC_DEBUG_LOG`: Custom log path for ESC latency tracing.
- `VOCABBUILDER_DEBUG_EXPORT=1`: Print export debug details during Anki generation.
- `VOCABBUILDER_AUTO_TRANSLATOR`: Enable/disable intelligent translator option.
- `VOCABBUILDER_MAX_BACKUPS`: Maximum timestamped backup snapshots to retain per file (default `10`; `0` disables pruning).
- `VOCABBUILDER_MAX_CHARS`: Override maximum input length.
- `VOCABBUILDER_MAX_WORDS`: Override max words allowed per input.
- `VOCABBUILDER_SENTENCE_MODE` / `VOCABBUILDER_ALLOW_PUNCT`: Toggle punctuation/sentence acceptance.
- `VOCABBUILDER_ROUTE_SENTENCES`: Toggle sentence routing behavior.
- `VOCABBUILDER_SENTENCE_EXAMPLES`: Toggle sentence examples in vocab entries.
- `VOCABBUILDER_HISTORY_DISABLED` / `VOCABBUILDER_HISTORY_ENABLED`: Disable/enable translation history logging.
- `VOCABBUILDER_HISTORY_DIR`: Override history log directory (default `~/.vocabbuilder/history`).
- Boolean flags accept typical truthy values such as `1`, `true`, `yes`, `y`, and `on`.

## Testing Guidelines
- Keep tests mirrored to modules (for example `vocab_builder/core/vocab.py` -> `tests/test_sentence_flow.py`).
- Name new files `test_<feature>.py` and test functions `test_<behavior>`.
- Use stubs/fixtures (`tests/_stubs.py`) to avoid real API calls.
- Run `pytest` before opening a pull request.
- When changing agent docs, run `pytest tests/test_agent_docs_sync.py`.

## Commit and Pull Request Guidelines
- Write imperative, present-tense commit subjects near 60 characters.
- Keep unrelated edits out of the same commit.
- Ensure each commit passes relevant tests.
- Pull requests should summarize behavior changes, include test evidence, and link related issues.
- Include terminal captures only for user-facing UX changes.

## Git Safety Rules
- NEVER use `git checkout <file>` or restore files without explicit approval.

## Security and Configuration Tips
- Store provider keys in keyring or environment variables; never commit secrets.
- Avoid checking in generated LaTeX, PDF, or Anki artifacts.
- Extend `.gitignore` when adding new generated outputs.
