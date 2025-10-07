# Multi-Language Refactor Plan

## Stage 0 — Decision & Scope Lock
- Align the team on shipping a single multi-language binary rather than forking a German-only variant.
- Ratify supported launch pairs (French↔English, German↔English) and confirm feature parity expectations (LLM assistance, LaTeX export, Anki deck generation, translators).
- Capture success criteria: language toggle, zero regression for French workflows, green CI, docs updated.

## Stage 1 — Architecture & Configuration Layer
- Introduce a `LanguageConfig` contract describing localized labels, Babel packages, prompt templates, deck metadata, and validation rules.
- Refactor `FrenchVocabBuilder` init to accept a config and surface current language in UI/CLI.
- Extract language-agnostic helpers into neutral modules; isolate French defaults inside a `french.py` config implementing the contract.
- Add a feature flag / CLI option (`--language`) and ensure default behavior matches today’s French flow.

## Stage 2 — Prompt & Parser Generalization
- Duplicate the unified AI prompt template into config-specific templates (French, German) while preserving the parser contract in `ai_response_parser.py`.
- Extend translator classes to load prompts/macros from the active config (e.g., `EnglishToTargetTranslator`, `TargetToEnglishTranslator`).
- Validate the parser against German sample payloads to confirm section detection remains language-agnostic.
- [Progress] Language configs now carry per-direction prompt + LaTeX templates; translators accept injected settings, keeping the parser contract intact.

## Stage 3 — LaTeX & Storage Abstraction
- Parameterize LaTeX scaffolding: move `INITIAL_TEX_CONTENT`, sample entries, and custom commands into per-language templates with placeholders for labels (`\usepackage[german,english]{babel}`, etc.).
- Update `LatexRepository` to rely on config-provided command names (e.g., `\entry`, `\deeng`, `\engde`) instead of hard-coded French strings.
- Ensure `format_latex_entry` uses config-driven casing/labels and supports noun gender markers or pluralization if required for German.
- [Progress] Vocabulary templates now live in language configs, builder methods honor the configured entry command, and `LatexRepository`/helpers use dynamic commands instead of hard-coded `\entry`.

## Stage 4 — Anki Export & Metadata
- Generalize `AnkiExporter` to accept dynamic front/back field names, deck titles, and GUID seeds based on language.
- Allow per-language deck filenames and export summaries; maintain backward compatibility with existing French exports.
- Decide how bilingual examples display (e.g., German → English) and confirm HTML escaping still passes tests.
- [Progress] Exporter now consumes language-provided model/deck metadata, so field labels, templates, and GUID seeds adjust per language.

## Stage 5 — UX, Validation, and Routing
- Replace French-specific copy in menus, panels, and prompts with config-driven strings.
- Extend input validation rules to support German punctuation (smart quotes, ß, umlauts), ensuring French defaults remain intact.
- Revisit sentence-routing logic so each language can choose whether to divert sentences to translators or keep in vocab mode.
- [Progress] Menu/translator copy pulls from language configs, prompts accept mixed-case confirmations, and validator messages reference the active language.

## Stage 6 — Testing & Tooling
- Parameterize existing unit tests to run against both French and German fixtures (pytest parametrization).
- Add targeted German fixtures for vocabulary parsing, LaTeX formatting, and translator flows.
- Update CI to run the expanded matrix; ensure test doubles/stubs can swap configs easily.
- [Progress] Added a German config stub and new pytest coverage that instantiates the builder for both fr/de, keeping the suite green.

## Stage 7 — Documentation & Rollout
- Update `README.md` and help text to describe the language toggle, config files, and new workflows.
- Provide migration guidance for existing users (default remains French; describe how to add German vocabulary).
- Prepare release notes summarizing the architecture shift and key validation checks.

## Stage 8 — QA & Launch Checklist
- Smoke-test both languages end-to-end (CLI entry, translator, LaTeX export, Anki deck creation).
- Verify exported files create separate `.tex` and `.apkg` artifacts per language without clashes.
- Gather feedback from early adopters, address translation prompt tuning, and schedule the production release.
