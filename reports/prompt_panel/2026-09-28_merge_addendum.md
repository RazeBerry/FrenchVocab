# Merge look-ups ask only for missing senses

Evidence, 2026-09-28. Never edited after landing; a correction is a new dated
report that links this one. Moved verbatim from `AGENTS.md` by the 2026-10-31
knowledge sweep.

A merge look-up sends the held entry. `vocabulary_prompt` is the one place a look-up prompt is built (CLI workflow, `VocabBuilder.query_ai`, mobile service); given the held repository record it appends `MERGE_ADDENDUM`, which lists the held senses and asks only for senses they lack, with empty Definitions and Examples sections meaning nothing is missing. Before 2026-09-28 a merge regenerated the whole entry and the exact-text diff offered every rewording as new: on the merge panel that behavior scored 1 of 18 and offered 44 senses to entries that needed 7, while the addendum scored 18 and 17 on two runs with no restatement (`results/merge-fresh-2026-09-28.json`, `merge-candidate-2026-09-28-v1.json`, `merge-shipped-2026-09-28.json`). The v1 score was 15 until three cases the panel had marked complete were found in Larousse, Duden and Wiktionary to lack an attested sense, and were re-marked as optional after the run; the 17 is the run that followed. Its miss was "gratter" losing "itch" again. The CLI's stage-two duplicate asks again with the held entry when the user chooses merge, since the response in hand is a fresh entry.
