# Bloat Reduction Refactor Plan

A staged approach to deflating the CLI codebase while preserving behavior across French and German workflows.

---

## Stage 1 — CLI Decomposition
- **Goal**: Reduce `FrenchVocab.py` to a slim entry point by splitting concerns into focused modules.
- **Actions**
  - Move environment/bootstrap logic (arg parsing, provider selection, keyring) into `cli/bootstrap.py`.
  - Extract Rich menu display and command routing into `cli/menu.py`.
  - Shift vocabulary operations (load/save, duplicates, alphabetizing) into `core/vocab.py`.
  - Leave `FrenchVocab.py` orchestrating: parse args → bootstrap → menu loop.
- **Regression Guards**
  - Extend `tests/test_language_configs.py` to instantiate the builder for both `fr` and `de` via the new entry.
  - Add a smoke test ensuring default (French) and explicit German initializations still load templates and exported word tracking paths.

---

## Stage 2 — Translator Unification
- **Goal**: Eliminate duplicated translator classes (`eng_to_fr_translator.py`, `fr_to_eng_translator.py`) in favor of a single configurable pipeline.
- **Actions**
  - Introduce `core/translator.py` with a `TranslatorCLI` class handling multiline input, duplicate checks, confirmations, and LaTeX persistence.
  - Feed the shared class with `TranslatorConfig` metadata from each language; wrappers (if any) simply pass the right config.
  - Remove legacy copy-pasted logic once tests are green.
- **Regression Guards**
  - Port existing translator-focused tests (e.g., `tests/test_yes_no_prompts.py`) to exercise the unified class.
  - Add direction-specific tests for English→German and German→English to ensure prompt placeholders map correctly and saved entries use the right macros.

---

## Stage 3 — Language-Specific Artifacts
- **Goal**: Ensure German exports look German and stop relying on French templates.
- **Actions**
  - Create dedicated German LaTeX scaffolding (`languages/german_tex.py`) with accurate document titles, commands (e.g., `\engde`, `\deeng`), and labels.
  - Audit prompt templates to replace residual `{french_text}` placeholders with neutral names.
  - Move or remove tracked `.tex/.pdf/.apkg` artifacts that should be generated output; keep fixtures under `tests/data/` instead.
- **Regression Guards**
  - Expand `tests/test_language_configs.py` to check translator filenames, command names, and headers per language.
  - Add fixture-based assertions that English→German exports render “German” labels (no lingering “French” text).

---

## Stage 4 — UI Helper Consolidation
- **Goal**: Trim unused Rich helpers and enforce a single UI surface.
- **Actions**
  - Remove dead methods in `UIHelper` (`multi_panel`, `progress_context`, `with_progress`) or move them behind optional mixins.
  - Route all prompt interactions through `UIHelper` to avoid duplicated prompt logic scattered across modules.
- **Regression Guards**
  - Update `tests/_stubs.py` to match the slimmer helper API.
  - Extend `tests/test_query_ai_errors.py` (and similar) to confirm they still stub the helper successfully.

---

## Stage 5 — Integration and Documentation
- **Goal**: Lock in behavior post-refactor and document the new architecture.
- **Actions**
  - Add `tests/test_integration_cli.py` to simulate a menu session for both languages using stubbed LLM clients.
  - Refresh `README.md` with the new module layout and instructions on adding languages under the refactored structure.
  - Optionally introduce lint/static checks (`ruff`, `mypy`) as part of the test command once the tree stabilizes.
- **Regression Guards**
  - Ensure `pytest -q` runs as part of the release checklist after each stage.
  - Manual smoke test (French and German) after Stage 5 before tagging.

---

## Risk & Mitigation Summary
- **Risk**: Hidden dependencies inside `FrenchVocab.py`.
  - **Mitigation**: Refactor incrementally per stage; run full tests and perform manual CLI smoke tests after each commit.
- **Risk**: Translator regression when unifying logic.
  - **Mitigation**: Keep wrappers during the transition and expand automated coverage before deleting old classes.
- **Risk**: Generated files reappearing in git due to user workflows.
  - **Mitigation**: Update `.gitignore`, add CI guard checking for tracked build artifacts.

---

## Completion Definition
1. `FrenchVocab.py` under 400 lines, delegating to modular packages.
2. Single translator implementation serving both languages with green tests.
3. German exports and prompts free of French-specific text.
4. `UIHelper` API surface documented and exercised by tests.
5. Updated README plus passing integration tests confirming French and German CLI parity.

