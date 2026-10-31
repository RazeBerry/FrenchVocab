# Repository Guidelines

## Repository Knowledge Contract
- `AGENTS.md` is the canonical instruction file. `CLAUDE.md` is its generated,
  byte-for-byte mirror so every coding agent receives the same routes and rules.
  Edit `AGENTS.md` only; after any change run
  `python scripts/sync_agent_docs.py --write` and commit both files together.
- This file holds only the rules below, which bind every task, and the routes to
  four domain routers. Knowledge has one home per type:
  - Routers (`docs/*_map.md`) route an intent to its owner and carry no rules.
  - Contracts (`docs/*.md`) hold invariants only: no run narratives, result
    tables or dated measurements.
  - Evidence (`reports/<kind>/YYYY-MM-DD_*.md`) is never edited after it lands.
    A correction is a new dated report that links the old one, and a contract
    rule links the report that justifies it.
  - Proposals (`docs/proposals/*.md`) carry `owner:` and `sunset:` front matter
    and are promoted into a contract or deleted when the sunset passes.
- Treat durable changes to behavior, architecture, ownership boundaries,
  persistence, concurrency, deployment, security, configuration, testing, or
  product design as incomplete until the owning contract reflects them. Put a
  new rule in its owner, never here, and put its measurements in a report.
- `python scripts/knowledge_ratchet.py --check` enforces this file's size, that
  every document is reachable, that every linked path exists, and that
  proposals are owned and unexpired; `pytest` runs it. Lower the baseline with
  `--print-baseline` after a cleanup; never raise it to make room.
- Run `python scripts/sync_agent_docs.py --check` and
  `pytest tests/test_agent_docs_sync.py` after editing this file. Byte equality
  proves shared text, not complete knowledge: in review, check that no owning
  contract was left semantically stale.

## Project Overview
VocabBuilder is an AI-assisted CLI for building bilingual or monolingual vocabulary lists, generating LaTeX documents, and exporting Anki decks. The current app supports English (`en`), French (`fr`), and German (`de`), has Rich-based keyboard navigation, and integrates with Google Gemini or Anthropic Claude. Install with `pip install vocab-builder` and run `vocabbuilder`.

An optional private web interface (`vocabbuilder-mobile`, extras `[mobile]`) serves the same collections to a phone or browser over Tailscale. See `docs/MOBILE.md` for the deployment topology.

- All source code lives under the `vocab_builder/` package.

## Routes
| To work on | Start at |
|---|---|
| CLI, terminal client, vocabulary storage, languages, Anki, persistence and locks | `docs/core_map.md` |
| Providers, credentials, thinking level, prompts and the prompt panel | `docs/llm_map.md` |
| The private phone and web interface: server, product rules, front end, glossary | `docs/mobile_map.md` |
| Deploy, backup and restore, security, environment variables, tests and CI | `docs/operations_map.md` |

## Commands
```bash
# Install (editable / development)
pip install -e .

# Repository knowledge synchronization
python scripts/sync_agent_docs.py --write
python scripts/sync_agent_docs.py --check
python scripts/knowledge_ratchet.py --check

# Tests
ruff check .
pytest
pytest tests/test_sentence_flow.py
pytest tests/test_agent_docs_sync.py
pytest -k "anki"
```

## Rules for every task

### Code
- Follow PEP 8 with 4-space indentation.
- Use `snake_case` for functions/variables and `PascalCase` for classes.
- Prefer dataclasses for config-style objects and use type hints throughout.
- Use ASCII by default; introduce Unicode only when lexically required (for example language samples and LaTeX templates).
- Keep UI messaging declarative via `UIHelper` methods and avoid bare `print()` in new code.
- `build/` is a stale, git-ignored copy of the package: never read or edit it.
- The `*.tex`, `*.bak`, `*.json` and `*.pdf` files in the repository root are
  the user's migration snapshots, not a database: never modify or delete them.

### Commits and pull requests
- Run `ruff check .` before opening a pull request.
- Run `pytest` before opening a pull request.
- Write imperative, present-tense commit subjects near 60 characters.
- Keep unrelated edits out of the same commit.
- Ensure each commit passes relevant tests.
- Pull requests should summarize behavior changes, include test evidence, and link related issues.
- Include terminal captures only for user-facing UX changes.
- NEVER use `git checkout <file>` or restore files without explicit approval.

### Security
- Store provider keys in keyring or environment variables; never commit secrets.
- This is a public repository. Before pushing, scan the entire unpushed commit range (not only the final worktree) for real API keys, `.env` content, private keys, tailnet FQDNs, account emails, cloud project/instance IDs, private IPs, personal VM logins, and vocabulary/history/Anki data.
- Avoid checking in generated LaTeX, PDF, or Anki artifacts.
- Extend `.gitignore` when adding new generated outputs.
