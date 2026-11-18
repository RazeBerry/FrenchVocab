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

## Headword key
- Each language owns its headword key: `LanguageConfig.headword_key` is a
  required field with no default. Every identity, order and rail-letter use
  calls the config's key (usually through the repository's or builder's
  `normalize_word`), never `models.normalize_word_key`. Two headwords are the same
  entry exactly when their keys are equal; key order is the collection's
  alphabetical order (insertion, `alphabetize_entries`, the glossary index);
  the key's first character is the glossary rail letter. The key is opaque: it
  is never displayed or parsed. French, German and English use
  `normalize_word_key` (lowercase, expand ß, umlauts, æ and œ, strip accents).
  Polish uses `polish_headword_key`: it composes (NFC), strips and lowercases,
  then writes each character as base-and-rank pairs. A Polish letter is one
  pair, its base letter and rank 1 (ą ć ę ł ń ó ś ź) or 2 (ż); any other
  character is folded as `normalize_word_key` folds it, and each resulting
  character is a pair with rank 0. Because bases and ranks alternate, the key
  decodes uniquely, so no literal input (`Sa{d`) can imitate a Polish letter
  (`Sąd`) and diacritics carry identity (`sąd` and `sad` are two entries).
  Keys compare letter by letter, the base first and the rank breaking a tie:
  `kawa` before `kąt`, `los` before `łoś`, `zupa` before `źle` before `żaba`,
  and `A‑klasa` (non-breaking hyphen) before `Ącki`. `Ł`, `Ś` and `Ż` take
  the L, S and Z rail letters.
- Merge text equality, the translation-pair key and the Anki tracker key
  (lowercased headword) are separate rules and do not use the headword key.

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
  A corrected headword may not land on another live entry under the
  language's headword key, because the app finds duplicates by that key; such
  a case is a merge and must name the other entry in `retire`.
- Correction history uses action `correct`. It records provenance but is not
  an acquisition or save: Anki order reconstruction and recent-save ledgers
  filter it out. The phone ledger includes only `new`, `force`, and `merge`.

## Languages
- English is monolingual: it omits translation workflows and uses plain-English example paraphrases as active-recall cues.
- Polish serves a beginner (A1-A2); French and German serve advanced learners.
  A Polish entry's type is one of a closed list: masculine, feminine, neuter or
  plural noun (plural only for a noun with no singular); imperfective,
  perfective or biaspectual verb; adjective, adverb, pronoun, numeral,
  preposition, conjunction, particle, interjection, expression. A verb is one
  entry per lemma and keeps the input's aspect (`napisałem` gives `napisać`);
  its sense a ends with `Perfective: <infinitive>.` or
  `Imperfective: <infinitive>.`, a later sense names a partner only when it
  differs, and a verb with no partner names none. `się` belongs to the
  headword when the verb needs it (`bać się`), never to the type. Register
  labels are Polish (`potoczny`, `książkowy`, `oficjalny`, `przestarzały`,
  `wulgarny`), quotation marks are „…”, and the LaTeX examples heading is
  `Przykłady`. The prompt rules behind these are in `docs/prompts.md`.

## Adding a new language
Every per-language difference is data in one `LanguageConfig`; shared code
never branches on a language code.
1. Create `vocab_builder/languages/<lang>.py` with a `LanguageConfig` (copy
   `polish.py` for a bilingual language, `english.py` for a monolingual one)
   and add it to the loop in `vocab_builder/languages/__init__.py`. Choices,
   corrections and registry-driven tests then include it.
2. Supply `headword_key`: `normalize_word_key` when folding accents is right
   for the language, otherwise a key of its own (see Headword key).
3. Ship the vocabulary prompt in `ai_prompts.py`, generated from
   `scripts/prompt_panel/candidate_prompts.py` after the panel measured it
   (`docs/prompts.md`), and add the language's rows to `panel.json`.
4. Build the vocab and translator documents with
   `vocab_document(<babel>, <examples heading>)` and
   `translation_document(<macro>, <first label>, <second label>)` from
   `latex_templates.py`; they are written once, when a file is created, and
   never rewrite an existing file. A monolingual language sets the translator
   configs and filenames to `None`.
5. A bilingual language writes its directional and auto-translate prompts on
   the fidelity floor in `docs/prompts.md` and names its direction tokens
   (`english_to_<language>`, `<language>_to_english`).
6. A bilingual language builds its Anki card with
   `bilingual_card_templates(<headword field>)` from `anki_shared_styles.py`.
   The export tracker records the card's template hash,
   `AnkiConfig.version_id`, which the config derives from its card templates
   and CSS; changing an existing language's card or CSS makes its next export
   include every note.
7. A bilingual language takes composition grading from
   `composition_config(<display name>, <learner>, <alternative>)` in
   `base.py`: `<learner>` states the level the coach grades for and
   `<alternative>` qualifies the phrasing offered beside each correction.
   French and German grade at C2 with a "stronger" alternative; Polish grades
   at A2 with a "simple" one.
8. Supply `ui_strings` only for a label the fallbacks cannot build from
   `display_name` and the translator labels.
9. The phone serves only the codes in `vocabbuilder-mobile --languages` and
   needs a hue and type badges (`docs/mobile_map.md`).
