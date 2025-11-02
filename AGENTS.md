# Repository Guidelines

- NEVER use `git checkout <file>` or restore files without explicit approval.

## Project Structure & Module Organization
- `FrenchVocab.py` bootstraps the Rich-based CLI, wiring language configs, routing, and persistence.
- `core/` houses reusable workflows (vocab ingestion, translators, Anki export, LaTeX repository helpers).
- `languages/` contains per-language validators, prompts, and LaTeX templates; register new languages via `languages/__init__.py`.
- `cli/` provides menu/navigation utilities, while `ui_helper.py` centralizes styled console interactions.
- `tests/` is a pytest suite (`test_*.py`) covering parsing, language configs, exporters, and sentence flow; use it as the template for new cases.

## Build, Test, and Development Commands
- `pip install -r requirements.txt` – install runtime and dev dependencies (Python 3.11).
- `python FrenchVocab.py --language fr --provider gemini` – launch the CLI for day-to-day vocab work; swap `de` for German.
- `pytest` – run the full automated suite; use `pytest tests/test_sentence_flow.py` for focused validation.
- `python -m cli.menu` – quick check of menu rendering during local iteration.

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation, `snake_case` for functions/variables, `PascalCase` for classes, and descriptive module names.
- Prefer dataclasses for immutable configs (see `languages/base.py`) and type hints throughout.
- Keep Rich UI messaging declarative (e.g., `self.ui.warning(...)`) and avoid bare `print()` in new code.
- Use ASCII by default; introduce Unicode only when lexically required (language samples, LaTeX templates).

## Testing Guidelines
- Tests live under `tests/` and should mirror target modules (e.g., `core/vocab.py` → `tests/test_sentence_flow.py`).
- Name new tests `test_<feature>.py` and individual cases `test_<behavior>` for clarity.
- New features must include pytest coverage and update or add fixtures where CLI interactivity is mocked via `_stubs.py`.
- Run `pytest` before opening a pull request; ensure deterministic output by avoiding real API calls (mock Gemini/Claude clients).

## Commit & Pull Request Guidelines
- Write imperative, present-tense commit subjects capped near 60 characters (examples: “Improve loader robustness”, “Revamp language selection”).
- Squash unrelated edits; each commit should compile and pass tests.
- Pull requests should summarize behavior changes, list testing evidence (`pytest`, manual CLI run), and link any tracking issues.
- Include screenshots or terminal captures only when UX changes are user-facing (menu updates, new prompts).

## Security & Configuration Tips
- Store provider keys via `keyring` or environment variables (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`); never commit secrets.
- Avoid checking in generated LaTeX/PDF/Anki exports; `.gitignore` already covers common artifacts—extend it if new outputs are introduced.
