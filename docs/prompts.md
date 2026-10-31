# Vocabulary and translation prompts

Contract: invariants only. Routed from `docs/llm_map.md`; dated evidence lives
in `reports/` and is linked from the rule it supports.

## Prompt panel
- `scripts/prompt_panel/` is the yardstick for the vocabulary generation
  prompts: `panel.json` names fifty words with the sense count, first sense,
  word type or lemma a careful reader expects and the reason for each, `run_panel.py`
  sends them through the same template, provider call and parser the app
  uses and scores the result, and `results/` keeps every run, rejected
  candidates included. `candidate_prompts.py` holds the prompt under trial.
  `merge_panel.json` and `run_merge_panel.py` measure merge look-ups the same
  way: eighteen held entries, most complete, seven lacking one regularly met
  sense, scored through the app's own merge diff.
- A vocabulary prompt is edited against the panel in `scripts/prompt_panel/`,
  never by taste: run the shipped prompt and the candidate, compare the saved
  results, and keep the rejected candidate's file. The panel does not check
  example grammar or definition-example agreement, so read the raw responses
  too. A prompt cannot supply attestation the model lacks; only a dictionary
  check could. Stored German entries that predate the contract carry three
  senses and forced future-tense examples from the old three-slot prompt.
  History: `reports/prompt_panel/2026-09-03_one_sense_contract.md` and
  `reports/prompt_panel/2026-09-24_audit_panel50.md`.

## Generation contract
- French and German word and expression generation share one measured
  contract: one lexical identity and part of speech, one sense by default,
  a further sense only when a reader of contemporary press, literary prose
  and everyday conversation meets it regularly and an unforced example can be
  written for it, senses ordered by how often that reader meets them, no
  hedged definitions ("can also", "sometimes", "metaphorically" are banned),
  at most one usage note on its own labelled line, the English equivalent
  before any paraphrase, exactly one example per entry, and no forced tense.
  A form no serious dictionary lists is not defined. Established figurative
  and conversational senses are kept, but no meaning is imported from a
  related word, a compound, another word's idiom, or an English look-alike.
  A reflexive construction the input supplies is kept, and a bare verb gains
  its pronoun only when the lemma requires it. Types include pronoun,
  determiner, preposition, conjunction and interjection (German adds
  reflexive verb, particle and numeral). Only sentence analysis
  retains its explicit three-part structure. Both templates are literals in
  `ai_prompts.py` generated from `scripts/prompt_panel/candidate_prompts.py`
  after the panel measured them.
- A merge look-up sends the held entry. `vocabulary_prompt` is the one place a
  look-up prompt is built (CLI workflow, `VocabBuilder.query_ai`, mobile
  service); given the held repository record it appends `MERGE_ADDENDUM`, which
  lists the held senses and asks only for senses they lack, with empty
  Definitions and Examples sections meaning nothing is missing. Regenerating the
  whole entry instead made the exact-text diff offer every rewording as new
  (`reports/prompt_panel/2026-09-28_merge_addendum.md`). The CLI's stage-two
  duplicate asks again with the held entry when the user chooses merge, since
  the response in hand is a fresh entry.

## Translation
- French and German directional translation prompts share the same fidelity
  floor while retaining language-specific idiom guidance: preserve agency,
  logical relations, quantifiers, modality, historical distance, structural
  labels, and specialist terminology; never modernize period prose, broadly
  domesticate cultural references, or silently alter names and facts. These
  prompts return translation text only. Do not add a Notes field unless the
  directional translation data model and UI are changed to retain and display
  it instead of stripping it before persistence.
- Auto translation may return an explicit `ambiguous` direction for words,
  names, abbreviations, and fragments whose language cannot be established.
  Ambiguity is a successful detection outcome, not a parse failure: the CLI and
  mobile adapters must stop before routing or saving and ask the user to choose
  a direction. Orthographic hints such as German noun capitalization are
  evidence, never a mandatory fallback guess.

## Parsing
- `ParsedAIResponse.contract_issues` reports definition/example count drift
  without truncating the parsed lists. Flexible aligned payloads flow unchanged
  through preview, LaTeX, merge, and Anki consumers; the headless mobile service
  rejects misaligned payloads before they can be saved silently.
