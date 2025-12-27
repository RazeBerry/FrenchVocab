# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FrenchVocab is an AI-assisted CLI for building bilingual vocabulary lists, producing LaTeX documents, and exporting Anki decks. It uses a terminal-based Rich UI with arrow-key navigation and supports multiple AI providers (Google Gemini, Anthropic Claude).

## Common Commands

```bash
# Install dependencies (Python 3.11 required)
pip install -r requirements.txt

# Run the CLI
python FrenchVocab.py --help                     # See all CLI options
python FrenchVocab.py --language fr              # French mode
python FrenchVocab.py --language de              # German mode
python FrenchVocab.py --language fr --provider claude  # Use Claude instead of Gemini
python FrenchVocab.py --language fr --latex-file ./FrenchVocab.custom.tex  # Custom LaTeX file
python FrenchVocab.py --language fr --eager-llm  # Initialize provider at startup

# Run tests
pytest                                           # Full test suite
pytest tests/test_sentence_flow.py              # Single test file
pytest -k "anki"                                 # Tests matching pattern

# Quick UI smoke test (menu rendering)
python -m cli.menu

# Verbose/debug modes
python FrenchVocab.py --language fr --verbose   # Timing details
python FrenchVocab.py --esc-debug               # ESC key latency tracing
python FrenchVocab.py --esc-debug --esc-debug-log /tmp/esc_latency.log
```

## Architecture

### Entry Point & Bootstrap
- `FrenchVocab.py` - CLI entry point with argument parsing; delegates to `cli/bootstrap.py`
- `cli/bootstrap.py` - Creates `FrenchVocabBuilder` instances, prompts for language selection
- `cli/menu.py` - Main menu loop orchestration
- `cli/navigation.py` - Interactive arrow-key menus using Rich Live rendering

### Shared Modules (root level)
- `models.py` - `WordEntry` dataclass with normalization utilities
- `anki_exporter.py` - Anki deck export utilities (genanki wrapper)
- `latex_repository.py` - Low-level LaTeX parsing helpers used by repositories and translators

### Core Application (`core/`)
- `vocab.py` - `FrenchVocabBuilder` class: the main application controller
- `vocab_repository.py` - LaTeX file parsing/persistence, entry management
- `word_entry_workflow.py` - `WordEntryWorkflow` class: orchestrates word entry flow from input to save
- `spelling_checker.py` - `SpellingChecker` class: extracts spelling suggestions from AI responses
- `translator.py` - `TranslatorCLI` for bidirectional translation workflows
- `auto_translator.py` - Intelligent translator with language detection
- `anki_manager.py` - Anki deck export workflows
- `llm_coordinator.py` - LLM provider lifecycle, streaming queries, usage tracking
- `file_safety.py` - Atomic file operations with backup/restore
- `history_logger.py` - Append-only JSONL translation history logging
- `protocols.py` - Protocol interfaces for structural typing
- `providers/manager.py` - `ProviderManager`: credential storage (keyring/.env), validation, setup wizard

### Language System (`languages/`)
- `base.py` - `LanguageConfig`, `TranslatorConfig`, `VocabTemplate`, `AnkiConfig` dataclasses
- `french.py`, `german.py` - Per-language configurations (prompts, validators)
- `latex_templates.py` - Consolidated LaTeX document templates (shared across languages)
- `anki_shared_styles.py`, `anki_themes.py` - Anki card styling and themes
- `__init__.py` - Language registry; use `get_language_config(code)` to resolve

### UI Layer
- `ui_helper.py` - `UIHelper` class centralizing Rich console output (panels, tables, menus, prompts)
- Design follows Anthropic-inspired palette: `#E67E50` (orange), `#ff6b6b` (error), `#51cf66` (success), `#ffd43b` (warning)

### AI Integration
- `llm_client.py` - `LLMClient` ABC, `GeminiClient` and `ClaudeClient` implementations (see `MODEL_NAME` constants)
- `ai_prompts.py` - Shared prompt templates
- `ai_response_parser.py` - Parse word type, definitions, examples from AI responses

### Data & Utilities
- `diagnostics/esc_latency.py` - ESC key latency tracing (enabled via `--esc-debug`)
- `scripts/` - Utility scripts (demo_guided_onboarding.py, merge_tex_vocab.py)
- `data/history/` - JSONL translation history logs per language (fr_translations.jsonl, de_translations.jsonl)

## Key Patterns

### Adding a New Language
1. Create `languages/<lang>.py` with `LanguageConfig` (see `french.py` as template)
2. Register in `languages/__init__.py` via the `_CONFIGS` dict
3. Add LaTeX templates and Anki card templates to the config

### UI Messaging
Route all status messages through `UIHelper` methods:
```python
self.ui.success("Entry saved!")      # Green checkmark
self.ui.error("Failed", with_panel=True)  # Red panel
self.ui.warning("Duplicate detected")     # Yellow warning
self.ui.info("Processing...", accent="dim")  # Dimmed info
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
1. Auto-load a `.env` file (project root when writable; else `~/.frenchvocab/.env`; override with `FRENCHVOCAB_CONFIG_DIR`)
2. System keyring (preferred; service: `french_vocab_builder`)
3. Environment variable (`GEMINI_API_KEY` / `ANTHROPIC_API_KEY`) including values loaded from `.env`
4. Interactive setup wizard (can persist to keyring or `.env`)

## Environment Variables

- `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` - API credentials (or use keyring/`.env`)
- `FRENCHVOCAB_FORCE_SYNC_LOAD=1` - Force synchronous loading (useful for tests)
- `FRENCHVOCAB_ESC_SEQUENCE_TIMEOUT` - ESC key sequence timeout in seconds (default: 0.03)
- `FRENCHVOCAB_ESC_DEBUG=1` - Enable ESC latency tracing (same as `--esc-debug`)
- `FRENCHVOCAB_ESC_DEBUG_LOG` - Custom log path for ESC latency tracing
- `FRENCHVOCAB_CONFIG_DIR` - Directory to store `.env` when project dir is not writable
- `FRENCHVOCAB_SKIP_KEYRING=1` - Skip system keyring usage (forces `.env`/env-only flows; useful for CI)
- `FRENCHVOCAB_DEBUG_EXPORT=1` - Print export debug info during Anki deck builds

## Testing

- Tests use stubs for external services (`tests/_stubs.py`) - no real API calls
- `conftest.py` sets up isolated temp directories for history logging
- Mock LLM clients via dependency injection in `FrenchVocabBuilder(client=...)`
- Key test files: `test_file_safety.py` (atomic writes), `test_update_api_key.py` (provider setup)

## Git Guidelines

- Never use `git checkout <file>` or restore files without explicit approval
- Imperative commit messages, ~60 char limit (e.g., "Add German language support")
- Each commit should compile and pass tests
