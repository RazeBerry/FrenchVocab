# Repository Guidelines

## Sync Requirement
- `AGENTS.md` and `CLAUDE.md` must stay byte-for-byte identical.
- Update both files in the same change.
- Run `pytest tests/test_agent_docs_sync.py` to validate alignment.

## Project Overview
FrenchVocab is an AI-assisted CLI for building bilingual vocabulary lists, producing LaTeX documents, and exporting Anki decks. It uses a terminal-based Rich UI with arrow-key navigation and supports multiple AI providers (Google Gemini, Anthropic Claude).

## Project Structure and Module Organization
- `FrenchVocab.py` bootstraps the CLI and delegates startup flow to `cli/bootstrap.py`.
- `cli/` contains menu orchestration, navigation helpers, and bootstrap wiring.
- `core/` contains reusable workflows (vocab ingestion, translators, Anki export, LaTeX repository helpers).
- `languages/` contains per-language validators, prompts, templates, and registry configuration.
- `ui_helper.py` centralizes styled console interactions and messaging helpers.
- `tests/` is a pytest suite (`test_*.py`) covering parsing, language configs, exporters, and sentence flow.

## Build, Test, and Development Commands
```bash
# Install dependencies (Python 3.11)
pip install -r requirements.txt

# Run the CLI
python FrenchVocab.py --help
python FrenchVocab.py --language fr
python FrenchVocab.py --language de
python FrenchVocab.py --language fr --provider claude
python FrenchVocab.py --language fr --provider gemini
python FrenchVocab.py --language fr --latex-file ./FrenchVocab.custom.tex
python FrenchVocab.py --language fr --eager-llm

# Run tests
pytest
pytest tests/test_sentence_flow.py
pytest -k "anki"

# Quick UI smoke test
python -m cli.menu

# Verbose and debug modes
python FrenchVocab.py --language fr --verbose
python FrenchVocab.py --esc-debug
python FrenchVocab.py --esc-debug --esc-debug-log /tmp/esc_latency.log
```

## Architecture

### Entry Point and Bootstrap
- `FrenchVocab.py` handles argument parsing and startup flow.
- `cli/bootstrap.py` creates `FrenchVocabBuilder` instances and language selection flow.
- `core/menu_loop.py` runs the main menu loop; `cli/menu.py` is a compatibility shim.
- `cli/navigation.py` implements interactive arrow-key menus with Rich live rendering.

### Shared Modules (root level)
- `models.py` defines the `WordEntry` dataclass and normalization helpers.
- `anki_exporter.py` contains Anki deck export utilities.
- `latex_repository.py` contains low-level LaTeX parsing helpers.

### Core Application (`core/`)
- `vocab.py` contains `FrenchVocabBuilder`, the main application controller.
- `vocab_repository.py` handles LaTeX file parsing, persistence, and entry management.
- `word_entry_workflow.py` orchestrates word entry from input to save.
- `spelling_checker.py` extracts spelling suggestions from AI responses.
- `translator.py` and `auto_translator.py` handle translation workflows.
- `anki_manager.py` coordinates Anki deck export flows.
- `llm_coordinator.py` handles provider lifecycle, streaming queries, and usage tracking.
- `file_safety.py` provides atomic file operations with backup and restore support.
- `history_logger.py` writes append-only JSONL translation history (default `~/.frenchvocab/history`).
- `protocols.py` defines protocol interfaces for structural typing.
- `core/providers/manager.py` manages credential storage, validation, and setup wizard flow.

### Language System (`languages/`)
- `base.py` defines `LanguageConfig`, `TranslatorConfig`, `VocabTemplate`, and `AnkiConfig`.
- `french.py` and `german.py` define per-language prompts and validators.
- `latex_templates.py` contains shared LaTeX templates.
- `anki_shared_styles.py` and `anki_themes.py` contain Anki card styling.
- `__init__.py` registers language configs and resolves via `get_language_config(code)`.

### UI Layer
- `ui_helper.py` contains the `UIHelper` class for Rich panels, menus, prompts, and status messages.
- Keep UI messaging declarative (for example, `self.ui.warning(...)`) and avoid bare `print()` in new code.

### AI Integration
- `llm_client.py` defines `LLMClient`, `GeminiClient`, and `ClaudeClient`.
- `ai_prompts.py` contains shared prompt templates.
- `ai_response_parser.py` parses word type, definitions, and examples from AI responses.

### Data and Utilities
- `diagnostics/esc_latency.py` contains ESC key latency tracing used by `--esc-debug`.
- `scripts/` contains utility scripts.
- Runtime history logs default to `~/.frenchvocab/history` (override with `FRENCH_VOCAB_HISTORY_DIR`).

## Coding Style and Naming Conventions
- Follow PEP 8 with 4-space indentation.
- Use `snake_case` for functions and variables, `PascalCase` for classes, and descriptive module names.
- Prefer dataclasses for config objects and use type hints throughout.
- Use ASCII by default; introduce Unicode only when lexically required (language samples, LaTeX templates).

## Key Patterns

### Adding a New Language
1. Create `languages/<lang>.py` with a `LanguageConfig` (use `french.py` as template).
2. Register the language in `languages/__init__.py`.
3. Add language-specific LaTeX and Anki templates in the language config.

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
1. Auto-load `.env` from the project root when writable, otherwise use `~/.frenchvocab/.env`.
2. Use system keyring when available (service name: `french_vocab_builder`).
3. Fall back to environment variables (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`).
4. Use interactive setup wizard when credentials are missing.

## Environment Variables
- `GEMINI_API_KEY` / `ANTHROPIC_API_KEY`: API credentials.
- `FRENCHVOCAB_FORCE_SYNC_LOAD=1`: Force synchronous loading (useful in tests).
- `FRENCHVOCAB_ESC_SEQUENCE_TIMEOUT`: ESC key sequence timeout in seconds (default: `0.03`).
- `FRENCHVOCAB_ESC_DEBUG=1`: Enable ESC latency tracing.
- `FRENCHVOCAB_ESC_DEBUG_LOG`: Custom log path for ESC latency tracing.
- `FRENCHVOCAB_CONFIG_DIR`: Directory for `.env` when project root is not writable.
- `FRENCHVOCAB_SKIP_KEYRING=1`: Disable keyring usage (useful for CI).
- `FRENCHVOCAB_DEBUG_EXPORT=1`: Print export debug details during Anki deck generation.

## Testing Guidelines
- Tests should mirror target modules (for example, `core/vocab.py` -> `tests/test_sentence_flow.py`).
- Name new files `test_<feature>.py` and individual cases `test_<behavior>`.
- Use stubs and fixtures (`tests/_stubs.py`) to avoid real API calls.
- Keep tests deterministic and run `pytest` before opening a pull request.

## Commit and Pull Request Guidelines
- Write imperative, present-tense commit subjects near 60 characters.
- Keep unrelated edits out of the same commit.
- Ensure each commit compiles and passes tests.
- Pull requests should summarize behavior changes, include test evidence, and link related issues.
- Include terminal captures only for user-facing UX changes.

## Git Safety Rules
- NEVER use `git checkout <file>` or restore files without explicit approval.

## Security and Configuration Tips
- Store provider keys in keyring or environment variables; never commit secrets.
- Avoid checking in generated LaTeX, PDF, or Anki export artifacts.
- Extend `.gitignore` when new generated outputs are introduced.
