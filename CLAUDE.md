# Repository Guidelines

## Repository Knowledge Contract
- `AGENTS.md` is the canonical repository guide. `CLAUDE.md` is its generated,
  byte-for-byte mirror so every coding agent receives the same architecture,
  workflow, deployment, security, and design knowledge.
- Edit `AGENTS.md` only; never maintain `CLAUDE.md` independently. After any
  guide change, run `python scripts/sync_agent_docs.py --write`, and commit both
  files in the same change.
- Treat durable changes to behavior, architecture, ownership boundaries,
  persistence, concurrency, deployment, security, configuration, testing, or
  product design as incomplete until the canonical guide reflects them.
- Run `python scripts/sync_agent_docs.py --check` for the fast byte-level check
  and `pytest tests/test_agent_docs_sync.py` for regression coverage. Dedicated
  CI also rejects a divergent mirror.
- Byte equality proves shared text, not complete knowledge. During review,
  explicitly verify that a change did not leave either guide semantically stale.

## Project Overview
VocabBuilder is an AI-assisted CLI for building bilingual or monolingual vocabulary lists, generating LaTeX documents, and exporting Anki decks. The current app supports English (`en`), French (`fr`), and German (`de`), has Rich-based keyboard navigation, and integrates with Google Gemini or Anthropic Claude. Install with `pip install vocab-builder` and run `vocabbuilder`.

An optional private web interface (`vocabbuilder-mobile`, extras `[mobile]`) serves the same collections to a phone or browser over Tailscale. See `docs/MOBILE.md` for the deployment topology.

## Project Structure and Module Organization
- All source code lives under the `vocab_builder/` package.
- `vocab_builder/cli/main.py` is the primary CLI entry point.
- `vocab_builder/cli/` contains bootstrap flow, interactive menu/navigation helpers, and compatibility shims.
- `vocab_builder/core/` contains application workflows (vocab ingestion, translators, auto translator, Anki export, LLM/provider lifecycle, history logging, menu/session UI helpers).
- `vocab_builder/core/providers/manager.py` encapsulates provider selection, credential validation, and secure storage.
- `vocab_builder/languages/` contains language registry, validators, prompts, and LaTeX/Anki configuration (`english.py`, `english_tex.py`, `french.py`, `german.py`, `german_tex.py`).
- `vocab_builder/` root modules (`models.py`, `anki_exporter.py`, `latex_repository.py`, `llm_client.py`, `ui_helper.py`) provide shared infrastructure.
- `vocab_builder/compat.py` provides backward-compatible helpers for env vars, config paths, and keyring migration.
- `vocab_builder/diagnostics/` contains ESC latency tracing tools.
- `vocab_builder/mobile/` contains the optional FastAPI web interface and its static front end (`static/index.html`, `styles.css`, `app.js`, `service-worker.js`).
- `FrenchVocab.py` is a deprecated shim that delegates to `vocab_builder.cli.main`.
- `scripts/` contains utility and demo scripts, including `scripts/bulk_add.py` for operator-reviewed structured JSON vocabulary batches.
- `scripts/deploy/` holds VM provisioning and backup scripts; `scripts/macos/vocab` is the Mac launcher for the remote CLI.
- `deploy/` holds the systemd unit and timer files for the mobile server and its daily backup.
- `tests/` is a pytest suite (`test_*.py`) for architecture boundaries, onboarding, translators, language config, exporters, and UI behavior.

## Build, Test, and Development Commands
```bash
# Install (editable / development)
pip install -e .

# Run the CLI
vocabbuilder --help
vocabbuilder --language fr
vocabbuilder --language de
vocabbuilder --language en
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

# Private mobile/web interface (requires the [mobile] extra)
pip install -e ".[mobile]"
vocabbuilder-mobile --help
vocabbuilder-mobile --languages fr,de,en --default-language fr
vocabbuilder-mobile --languages fr,de,en --allowed-tailscale-user you@example.com
vocabbuilder-mobile --language fr --latex-file ./FrenchVocab.tex

# Repository knowledge synchronization
python scripts/sync_agent_docs.py --write
python scripts/sync_agent_docs.py --check

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
- `anki_manager.py` coordinates export state and Anki generation, including persistent acquisition order so decks do not inherit LaTeX alphabetization.
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
- `english.py`, `french.py`, and `german.py` define prompts, validators, learning-mode behavior, and Anki metadata.
- English is monolingual: it omits translation workflows and uses plain-English example paraphrases as active-recall cues.
- `english_tex.py` and `german_tex.py` contain dedicated language-specific LaTeX templates.
- `latex_templates.py`, `anki_shared_styles.py`, and `anki_themes.py` provide shared assets.

### Private Mobile Interface (`vocab_builder/mobile/`)
- `cli.py` is the `vocabbuilder-mobile` entry point; it binds `127.0.0.1:8080` by default and never opens a public port.
- `app.py` builds the FastAPI app and owns the JSON API (`/api/collections`, `/api/status`, `/api/preview`, `/api/save`, `/api/recent`, `/api/search`) plus the static shell.
- `service.py` wraps one `VocabBuilder` per language with its own in-process lock, preview tokens, idempotent save receipts, and history.
- `catalog.py` registers those per-language services and resolves the `?language=` parameter; `factory.py` constructs them.
- The mobile surface constructs every builder with `interactive=False`; no code reachable from a request may prompt. `UIHelper` raises `NonInteractiveError` as a backstop if a future request path accidentally attempts console input.
- Blocking provider and repository work is exposed through synchronous FastAPI handlers so Starlette runs it in worker threads; do not call those workflows directly from an `async def` route.
- Tailscale Serve supplies private HTTPS and identity; provider credentials stay server-side and are never sent to the browser.

#### Mobile product philosophy
- The phone is a private capture surface for the authoritative VM collection,
  not a second application or database. Optimize for the moment a reader meets
  a word: open, type, review, keep, and return to the book.
- Preserve one dominant path: capture -> preview -> save. The preview is the
  editorial checkpoint, not a separate destination, and secondary collection
  browsing must not compete with capture above the fold.
- Keep the interface calm and object-centered. Capture and preview inhabit the
  same specimen slip so state changes feel continuous instead of navigating a
  dashboard or multiplying cards, dialogs, and modes.
- Language changes should preserve the same mental model. Express identity
  through the collection hue and grammatical copy rather than separate layouts.
- Progressive disclosure may hide detail, never discard it. The compact phone
  view can defer senses and examples, but save behavior must retain the complete
  structured result used by LaTeX and Anki.
- Privacy, connectivity, and installability should be legible but quiet:
  Tailscale remains the access boundary, secrets remain server-side, and the
  no-build shell remains usable as an iPhone home-screen app.

#### Mobile front end (`vocab_builder/mobile/static/`)
- Plain HTML/CSS/JS with no build step and no external requests (Tailscale-only hosts may have no public egress).
- All colors are CSS custom properties on `:root`, re-declared in one `:root[data-theme="dark"]` rule. Style components through the tokens; never hardcode a color inside the dark rule, or it will not apply in light mode.
- Theme is an explicit choice, not an ambient one. An inline script in `index.html` stamps `data-theme` on `<html>` before first paint (seeded from `prefers-color-scheme` only on a first visit, then from `localStorage`); the toggle writes that key. Keep the stamping inline and before the stylesheet, or the page flashes the wrong theme, and keep `THEME_BACKGROUND` in `app.js` matching `--bg` so the iOS status bar follows.
- `/`, `/manifest.webmanifest` and `/service-worker.js` must send `Cache-Control: no-cache`. Unversioned documents otherwise fall back to heuristic freshness that grows with file age, so an installed home-screen app can serve a stale shell for days after a deploy. Assets under `/static` carry `?v=N` instead and may cache normally.
- The interface is a single "specimen slip": one card carries capture and preview. `.slip.is-capturing` is the blank state (the `textarea` is the headword), and the same slip fills in with the preview rather than swapping to another component.
- Each collection owns a hue, selected by `data-language` on `<html>` and read through `--hue`/`--on-hue`. Any new accent must come from those tokens so a new language only adds a hue.
- Headword sizing steps through `.hw--s1/2/3` at 14 and 28 characters. The breakpoints come from the stored collections (87% of French headwords are <= 14 characters, 2% are long expressions); re-measure before changing them.
- Long AI responses are deferred, never dropped: the collapsed slip shows the first sense plus one example, and `#more-button` expands the rest, pinning the headword and scrolling `.slip-body`. `/api/save` still commits every definition and example.
- The collection is an index, not a feed: one row per word (headword, abbreviated part of speech, truncated first sense), and tapping opens the full entry **in place** so the scroll position never moves. Only one row is open at a time.
- Letter dividers are rendered only for alphabetical results. `/api/search` returns sorted matches, `/api/recent` returns history order; grouping the latter would print dividers that contradict the order, so `renderEntries` takes an explicit `grouped` flag.
- Group headings normalise diacritics, so `Étourdissant` files under `E` and `Ôter` under `O`, but the letter is taken from the word **as stored** to stay consistent with the server's sort.
- `TYPE_ABBREVIATIONS` is matched longest-first so `separable verb` does not collapse to `v.` and `adjective/noun` does not collapse to `n.`. Collections currently hold 18 distinct type strings; unrecognised values fall back to a truncation rather than being dropped.
- When changing `styles.css` or `app.js`, bump the `?v=N` query in `index.html` **and** the matching `SHELL_CACHE`/`SHELL_FILES` entries in `service-worker.js`, or installed home-screen apps keep serving the old assets.
- User-visible copy is generated in `app.js` (article agreement, singular/plural); keep it grammatical for every registered language name.

### Persistence and Concurrency Model
- In the deployed topology, `/var/lib/vocabbuilder` is the only writable source of truth. The phone surface and the Mac `vocab` launcher operate on that VM state; repository-local vocabulary files are migration snapshots, not a second database. Do not introduce bidirectional file sync.
- Every persisted read-modify-write must use `vocab_builder.core.file_safety.file_lock(path)`. It acquires the catalog-wide `.vocabbuilder.lock` before the artifact sidecar `.<filename>.lock`; nested acquisition in one thread is deliberately reentrant.
- Cross-process lock files must remain beside the authoritative data/config root, never in the temporary directory. The systemd service uses `PrivateTmp=true`, so `/tmp` locks would split the phone and SSH CLI into different lock domains and reintroduce silent lost updates.
- Reload authoritative disk state only after acquiring the commit lock. Duplicate checks, merge calculations, insertion decisions, and Anki state reconciliation must be recomputed inside that transaction rather than trusting pre-lock caches.
- Keep a vocabulary mutation, its history append, and its Anki acquisition-order update inside one outer catalog transaction. Continue using atomic replacement for rewritten files and `flush` + `fsync` for append-only JSONL.
- Mobile preview releases its service lock across provider recovery and generation, then re-validates duplicates after reacquiring it. Phone saves register Anki acquisition order inside the same catalog transaction as the vocabulary write and history append.
- Anki tracker writes use a three-way merge of the manager's persisted baseline, current disk state, and local changes so concurrent additions and intentional removals do not overwrite one another.
- `scripts/deploy/backup_mobile_data.sh` takes the same catalog lock with util-linux `flock` before archiving. Any new backup/export path that needs a coherent multi-file snapshot must join that lock domain.
- Repository cache invalidation uses `(device, inode, mtime_ns, size)` signatures. Do not weaken it to timestamps alone.

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
1. Create `vocab_builder/languages/<lang>.py` with a `LanguageConfig` (copy `french.py` or `german.py`); `learning_mode` selects bilingual versus monolingual behavior.
2. Register it through `vocab_builder/languages/__init__.py`.
3. Add language-specific vocab and translator templates (new `*_tex.py` module if needed); translator config and filename fields are optional (`None`) for monolingual languages.
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

### Persisting Mutable State Safely
1. Acquire `file_lock()` for the authoritative artifact (which also takes the catalog lock).
2. Reload the current file/index while holding that lock.
3. Repeat duplicate/conflict validation and compute the mutation from the refreshed state.
4. Commit the primary file atomically, then write coupled history/tracker state before releasing the outer transaction.
5. Add a multiprocessing regression test that starts stale independent instances and proves every successful mutation survives. Thread-only tests are insufficient for VM/CLI concurrency.

## Environment Variables
All variables use the `VOCABBUILDER_*` prefix. Legacy `FRENCHVOCAB_*` and `FRENCH_VOCAB_*` names are still recognized via `vocab_builder/compat.py` with deprecation warnings.

- `GEMINI_API_KEY` / `ANTHROPIC_API_KEY`: Provider API credentials.
- `VOCABBUILDER_CLAUDE_MODEL`: Override Claude model ID (default `claude-sonnet-4-6`).
- `VOCABBUILDER_GEMINI_MODEL`: Override Gemini model ID (default `gemini-3-flash-preview`).
- `VOCABBUILDER_PROVIDER_TIMEOUT`: Provider request deadline in seconds (default `120`).
- `VOCABBUILDER_PROVIDER_RETRY_COOLDOWN`: Minimum seconds between silent provider re-initialization attempts (default `30`).
- `VOCABBUILDER_ALLOWED_TAILSCALE_USER`: Tailscale login accepted by the private mobile interface; requests are not identity-checked when unset.
- `VOCABBUILDER_CONFIG_DIR`: Override directory used for `.env` storage/loading.
- `VOCABBUILDER_SKIP_KEYRING=1`: Disable keyring lookups/storage.
- `VOCABBUILDER_FORCE_SYNC_LOAD=1`: Force synchronous loading (useful in tests).
- `VOCABBUILDER_ESC_SEQUENCE_TIMEOUT`: ESC key sequence timeout in seconds (default `0.03`).
- `VOCABBUILDER_ESC_DEBUG=1`: Enable ESC latency tracing.
- `VOCABBUILDER_ESC_DEBUG_LOG`: Custom log path for ESC latency tracing.
- `VOCABBUILDER_DEBUG_EXPORT=1`: Print export debug details during Anki generation.
- `VOCABBUILDER_AUTO_TRANSLATOR`: Enable/disable intelligent translator option.
- `VOCABBUILDER_COMPOSITION`: Enable/disable composition practice (default on).
- `VOCABBUILDER_EXIT_SNAPSHOT`: Enable/disable the automatic complete Anki snapshot on clean exit (default on).
- `VOCABBUILDER_COMPOSITION_WORDS`: Target words per use-these-words attempt (default `3`, int >= 1).
- `VOCABBUILDER_COMPOSITION_SET_SIZE`: Attempts per daily composition set (default `3`, int >= 1).
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
- Concurrency changes must cover both in-process threads and POSIX processes. Keep the isolated-`tempfile.tempdir` regression in `tests/test_concurrency_transactions.py`; it models systemd `PrivateTmp` without touching production data.
- Mobile changes should exercise the ASGI surface in `tests/test_mobile_service.py`, including duplicate commits, save retries, language routing, Tailscale identity enforcement, and cross-language worker-thread behavior.
- Run `pytest` before opening a pull request.
- When changing repository knowledge, edit `AGENTS.md`, run
  `python scripts/sync_agent_docs.py --write`, then run
  `python scripts/sync_agent_docs.py --check` and
  `pytest tests/test_agent_docs_sync.py`.

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
- This is a public repository. Before pushing, scan the entire unpushed commit range (not only the final worktree) for real API keys, `.env` content, private keys, tailnet FQDNs, account emails, cloud project/instance IDs, private IPs, personal VM logins, and vocabulary/history/Anki data.
- Keep deployment identity in root-owned VM environment files or untracked local shell configuration. Tracked documentation and launcher defaults should use generic machine names and placeholders wherever practical.
- Public service topology and filesystem paths are not authentication. Preserve the actual boundary: localhost binding, Tailscale Serve identity, tailnet policy, and server-only credentials.
- Avoid checking in generated LaTeX, PDF, or Anki artifacts.
- Extend `.gitignore` when adding new generated outputs.
