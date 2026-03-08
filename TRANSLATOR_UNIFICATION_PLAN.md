# Translator Unification & Direction-Agnostic Workflow (VocabBuilder)

## 1. Objectives
- Provide a single “intelligent translator” entry point that automatically detects whether the user input is in English or the target language, then produces the translation in the opposite direction.
- Preserve existing UX affordances (Rich UI, confirmations, history logging, LaTeX persistence) while minimizing disruption for current Eng→Target / Target→Eng flows.
- Maintain deterministic storage: Eng→Target pairs remain in `EnglishTo<Lang>.tex`, Target→Eng pairs stay in `<Lang>ToEnglish.tex`, even though the translator entry point is unified.
- Keep backwards compatibility so the legacy two-button menu can be retained or hidden via a feature flag during rollout.

## 2. Current Architecture Snapshot
1. `TranslatorCLI` (`vocab_builder/core/translator.py`) already encapsulates prompting, UI, LaTeX persistence, duplicate detection, and logging for a single direction.
2. `VocabBuilder` (`vocab_builder/core/vocab.py`, formerly `FrenchVocabBuilder`) instantiates two TranslatorCLI objects using `LanguageConfig.eng_to_target` and `.target_to_eng` (`vocab_builder/languages/<lang>.py`) and exposes them via the menu (`vocab_builder/cli/menu.py`).
3. Prompt templates are hard-coded per direction via `TranslatorConfig.prompt_template` with placeholders `{english_text}` vs `{french_text}`.
4. History logging keys off `direction` to distinguish `eng_to_target` vs `target_to_eng`.

## 3. High-Level Strategy
1. Introduce a hybrid translator facade (`AutoTranslator`) that wraps both existing TranslatorCLI instances, handling language detection, prompt selection, and LaTeX routing.
2. Design a new auto-detect prompt template per language that accepts `{source_text}` and instructs the model to:
   - Detect whether the text is in English or the target language.
   - Emit a structured header (e.g., `Direction: english_to_french`).
   - Provide only the translated text (and optional notes).
3. Update builder/menu to expose a new “Intelligent Translator” option (while optionally retaining the classic two-item submenu behind a flag or until confidence is high).
4. Extend storage/logging utilities so they can accept the resolved direction at runtime.

## 4. Detailed Implementation Plan

### Phase A – Prompt & Contract Design
1. Draft language-specific auto-detect prompt templates (`vocab_builder/languages/french.py`, `vocab_builder/languages/german.py`) with:
   - Explicit instruction to output `Direction:` line (`english_to_french` or `french_to_english`).
   - `Translation:` block (the translated text).
   - Optional `Notes:` block.
2. Create parser helpers in `vocab_builder/core/translator_auto.py` (new module) to validate and extract `direction`, `translation`, and `notes`. Include pytest coverage for malformed responses.
3. Document the format in AGENTS/README style notes to guide future languages.

### Phase B – AutoTranslator Wrapper
1. New class `AutoTranslator`:
   - Holds references to `eng_to_target_translator` and `target_to_eng_translator`.
   - Accepts a dedicated `TranslatorConfig` for the auto-detect prompt (or reuses a lightweight config with the hybrid template).
   - Implements `run()` similar to TranslatorCLI but:
     1. Collects source text once.
     2. Calls `client.stream` with the hybrid prompt.
     3. Parses direction + translation result.
     4. Dispatches to the correct underlying translator (`translate_and_save`) using the original source text but bypassing another AI call by supplying the already generated translation (requires a minor extension to TranslatorCLI to accept “provided translation”).
2. Extend `TranslatorCLI.translate_and_save()` with optional `provided_translation` to skip re-querying when the AutoTranslator already holds the target text.
3. Ensure duplicate detection uses the appropriate translator’s normalization tables: AutoTranslator should call `target_translator.check_duplicate()` before writing.

### Phase C – Builder Integration
1. Add feature flag (`VOCABBUILDER_AUTO_TRANSLATOR=1`, legacy: `FRENCH_VOCAB_AUTO_TRANSLATOR`) to toggle the new flow.
2. Modify `VocabBuilder._init_translators()` to instantiate AutoTranslator when the flag is enabled and store it as `self.auto_translator`.
3. Update `vocab_builder/cli/menu.py`:
   - When auto translator is available, show a new menu entry “Intelligent Translator (auto direction)”.
   - Optionally keep the legacy Eng→Target and Target→Eng entries (either hidden when auto mode is active or kept for advanced users).
4. Update `ensure_llm_ready()` and degraded-mode logic so AutoTranslator presence mirrors the availability of the underlying translators.

### Phase D – Persistence & Logging
1. Extend `TranslationLogger.log_translator_entry` payload with `auto_detected_direction` to record how the hybrid translator resolved each request.
2. When AutoTranslator hands off to a TranslatorCLI, ensure `_log_saved_translation` receives the resolved direction and the provider label from the hybrid prompt call (avoid double logging).
3. Update history tests (`tests/test_history_logger.py`) to include auto-direction entries.

### Phase E – Testing & Tooling
1. Unit tests:
   - `tests/test_auto_translator.py` covering parsing, duplicate handling, fallback to manual translators on parse failure, and ensuring no extra AI call occurs.
   - Extend `tests/test_sentence_flow.py` to confirm sentence routing still works when the auto translator is enabled (should reuse the same internal translator for target→Eng).
   - Add regression tests ensuring legacy translators remain unaffected when the feature flag is off.
2. Manual validation:
   - Run `vocabbuilder --language fr --provider gemini` (formerly `python FrenchVocab.py`) with flag on/off, translate sample English and French sentences, verify LaTeX files updated correctly.
   - Inspect `data/history/fr_translations.jsonl` for new `auto_detected_direction` field.

## 5. Rollout Considerations
1. Start with feature flag defaulting to off; document env var in README.
2. Provide CLI setting (under Settings menu) to toggle auto translator at runtime (persistent via `vocabbuilder_config.json` if available).
3. Monitor auto-detect accuracy by comparing the stored direction with a heuristic detector; log mismatches for debugging (optional).

## 6. Risks & Mitigations
| Risk | Impact | Mitigation |
| --- | --- | --- |
| LLM mis-detects direction | Translation ends up in wrong file | Add lightweight language ID heuristic as a sanity check; prompt instructs model to be explicit; allow user to override before saving. |
| Duplicate detection misses entries across files | Users may create conflicting pairs | Ensure AutoTranslator queries both translators’ `pairs` dicts before saving. |
| UX confusion | Users unsure which menu option to use | Keep legacy translators visible initially; add help text describing auto mode. |
| Logging double-counts | Token stats inflated | Record usage only once per request (from the auto prompt) and pass metrics into downstream translator steps. |

## 7. Open Questions
1. Should the auto prompt support multi-language detection when more than one target language is registered?
2. Do we need to support batch translations or remain single-entry to keep UX simple?
3. How should notes from the auto prompt be surfaced in the UI (panel vs inline log)?

Answering these before implementation will prevent scope creep and clarify UX expectations.

