# Vocabulary entries and languages

Contract: invariants only. Routed from `docs/core_map.md`; dated evidence lives
in `reports/` and is linked from the rule it supports.

## Stored text
- A stored headword capitalizes its first character and nothing else
  (`display_headword`). `str.capitalize` lowercased every later letter and
  stored "jemanden nicht im Stich lassen" as "Jemanden nicht im stich lassen";
  German nouns inside an expression, and proper nouns inside a French one,
  cannot survive that. Sentences are stored as typed.
- Vocabulary and translation text is escaped exactly once on write and
  unescaped exactly once on read, through `escape_latex` / `unescape_latex` in
  `latex_repository.py`; every in-memory value, comparison, and API payload is
  plain text. Any code that reads a raw brace group (a headword scan, a sort
  key, `find_entry_bounds`) must unescape it before comparing. When only the
  writer escaped, every merge re-escaped stored text (`\textbackslash{}` piled
  up), "rock & roll" missed its own duplicate, and the phone showed held senses
  containing `%` or `&` as new. Example translations are always wrapped in one
  pair of parentheses and the reader removes exactly one, so "(fig.) he likes
  (it)" survives.

## Capture workflow
- `word_entry_workflow.py` orchestrates end-to-end word capture and save behavior, including explicit saved/routed/skipped outcomes so failed routing or merge paths never masquerade as successful saves.

## Reviewed corrections
- `scripts/apply_vocab_corrections.py` applies reviewed, base-hashed JSON
  patches to one language. The VM maintenance procedure is: stop
  `vocabbuilder-mobile`, run its default dry-run and review the entry, tracker,
  and identity diffs, rerun with `--apply`, restart the service, run an
  ordinary incremental export (corrected notes are pending by fingerprint;
  a selected-words export of the reported headwords does the same), then
  delete the reported retired GUIDs by hand in Anki. The tool refuses pending mobile
  transactions; repair them before the maintenance window. It takes the
  catalog lock, snapshots all four data artifacts into a correction bundle,
  and writes identity, vocabulary, tracker, and correction history in order.
  If interrupted between those writes, inspect the bundle before retrying;
  a rerun can finish missing history when all three rewritten files match its
  recorded post-write hashes. Do not run it against repository snapshots.
  A corrected headword may not land on another live entry even up to
  accents, because the app finds duplicates by the accent-free key; such a
  case is a merge and must name the other entry in `retire`.
- Correction history uses action `correct`. It records provenance but is not
  an acquisition or save: Anki order reconstruction and recent-save ledgers
  filter it out. The phone ledger includes only `new`, `force`, and `merge`.

## Languages
- English is monolingual: it omits translation workflows and uses plain-English example paraphrases as active-recall cues.

## Adding a new language
1. Create `vocab_builder/languages/<lang>.py` with a `LanguageConfig` (copy `french.py` or `german.py`); `learning_mode` selects bilingual versus monolingual behavior.
2. Register it through `vocab_builder/languages/__init__.py`.
3. Add language-specific vocab and translator templates (new `*_tex.py` module if needed); translator config and filename fields are optional (`None`) for monolingual languages.
4. Provide Anki config/templates and optional auto-translator prompt tokens.
