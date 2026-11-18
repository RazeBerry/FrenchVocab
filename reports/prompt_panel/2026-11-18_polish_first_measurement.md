# The Polish beginner candidate's first measurement

Evidence, 2026-11-18. Never edited after landing; a correction is a new dated
report that links this one.

## What was measured

The Polish candidate in `scripts/prompt_panel/candidate_prompts.py` is the
French template with Polish values and three fields that French and German
leave empty:

- `reader_rule` redefines "that reader" as an A1-A2 beginner who meets Polish
  in everyday life, a coursebook or simple texts;
- `sense_rule` caps the senses at two plus one usage note, asks for plain
  English, closes sense a with `Perfective: <infinitive>.` or
  `Imperfective: <infinitive>.`, and points the usage note at the most useful
  beginner fact (an irregular form, the case the word takes, a common phrase);
- `example_rule` asks for short everyday examples, mostly present tense,
  moves a perfective verb to the past or simple future, and repeats the case,
  negation-genitive, agreement and aspect checks.

The headword rule keeps the input's aspect and restores Polish letters only
when the bare spelling is not a Polish word. The prompt is 1,377 words against
the French prompt's 1,044.

Ten Polish rows were added to `panel.json`, the brief's ten words with a
first-sense keyword each. Each run sent only those ten through the
candidate, on `gemini-4-hydrogen` at the shipped `low` thinking level, with
the app's parser.

## Pass counts

| Run | Prompt | Passed | Senses | Usage notes | Hedges | Overlaps |
|---|---|---|---|---|---|---|
| 1 | v1 | 10 of 10 | 10 | 9 | 0 | 0 |
| 2 | v1, unchanged, repeated | 10 of 10 | 10 | 9 | 0 | 0 |

No revision was made. Both runs passed every check, and nothing I found in
the raw responses was systematic enough to justify a prompt change (see the
defects below). The second run checks that the first was not luck. Run 2 is
saved as `scripts/prompt_panel/results/candidate-2026-11-18-polish-low.json`.
Run 1 was kept only in the session scratchpad. Twenty panel calls and nine
probe calls were made in total.

## Per word, both runs

| Input | Headword, type | Findings |
|---|---|---|
| zolw | żółw, masculine noun | All three diacritics restored. "Turtle or tortoise." Notes: the plural `żółwie` (run 1) and the animate accusative `żółwia` (run 2), both correct. Examples are correct. |
| sad | sad, masculine noun | Kept as orchard. `sąd` was not restored and no English "sad" leaked in. One sense, no note in either run. "W naszym sadzie rosną jabłonie." and "Dziadek ma duży sad za domem." are both correct. Neither run warned against `sąd`, which would have been the most useful note. |
| mężczyzną | mężczyzna, masculine noun | Lemma and gender right. The note explains that the noun is masculine despite its -a ending. The instrumental examples are correct ("Rozmawiam z wysokim mężczyzną.", "jest moim bratem"). |
| mieście | miasto, neuter noun | The note teaches the locative `w mieście`. "Warszawa to duże miasto." and "Mieszkam w mieście." are correct in both runs. |
| ręce | ręka, feminine noun | Run 1 gave "Hand." only; run 2 gave "Hand or arm.". The note gives the irregular plural `ręce` (run 2 adds the genitive `rąk`). "Podaj mi rękę.", "Mam zimne ręce.", "Boli mnie prawa ręka." and "Umyj ręce przed obiadem." are all correct. |
| poszedł | pójść, perfective verb | Aspect kept; `Imperfective: iść.` closes sense a. The note gives the irregular past forms `poszedł/poszła/poszli`. The examples use the past tense and are correct. Run 1's sense a stacks three glosses ("To go on foot, to set off, or to head somewhere"). |
| pisać | pisać, imperfective verb | `Perfective: napisać.` is present. The note gives the stem `pisz-` with correct forms. "Piszę list do babci." and "Ona często pisze wiadomości do mamy." are correct. |
| wziąć | wziąć, perfective verb | `Imperfective: brać.` is present. The notes give the irregular future `wezmę, weźmiesz` and the past `wziąłem, wzięła, wzięli`, all correct. The examples use the future or past, never the present: "Wezmę parasol, bo pada.", "Wzięła książkę ze stołu.", "Muszę wziąć parasol.". |
| bać | bać się, imperfective verb | `się` is in the headword, not in the type, and no aspect partner is named. The note: the genitive of the thing feared, or an infinitive. "Boję się ciemności." and "Dziecko boi się dużego psa." are correct. The Spelling Check still says "OK" for the bare input. |
| myć | myć, imperfective verb | Not turned reflexive; `Perfective: umyć.` is present. The note points to `myć się` (run 2 adds `prać` for clothes, a good beginner contrast). "Myję ręce przed obiadem." and "Rano myję się ciepłą wodą." are correct. |

Every verb with a partner closed sense a with it. The verb without one
(`bać się`) named none. No example put a perfective verb in the present.

## Out-of-panel probes

Nine further inputs went through the same prompt once each. They were not
scored and their raw responses are not kept in the repository, so the
findings that matter are quoted here.

- `dziekuje` became `dziękować`, imperfective verb, `Perfective:
  podziękować.`. The note gives the dative for the person thanked and
  `za` plus the accusative for the reason. Correct.
- `ładny` became an adjective with the comparative `ładniejszy`. `spodnie`
  became a plural noun, with a note that it is always plural. `zrobić` became
  a perfective verb, `Imperfective: robić.`. `aresztować` became a
  biaspectual verb with no partner named. `na pewno` became an expression,
  with a note that it is never written `napewno`. All their examples are
  correct.
- The sentence `Wczoraj nie widziałem brata.` was translated correctly. Its
  note names the genitive after negation and the male speaker that
  `widziałem` implies.
- `kat` stayed `kat` (executioner), with a note warning against `kąt`.

## Grammar and translation defects

None of the twenty panel responses had a grammar defect I could find. The
defects are all in the probes or are matters of style:

1. **Mistranslation, `przez`:** "Idziemy przez starą ulicę." was translated
   as "We are walking along an old street". `przez ulicę` means across the
   street; "along" would need `ulicą` or `wzdłuż ulicy`. The Polish is
   grammatical, but the English teaches the wrong meaning.
2. **Uncertain, possessive:** "Wczoraj nie widziałem mojego brata." Normative
   grammar prefers the reflexive `swojego` when the possessor is the subject.
   With a first-person subject, `mojego` is common and widely accepted in
   speech. I flag this rather than call it an error.
3. **Example without the headword:** for `kat`, the second example illustrates
   the usage note with `kąt` ("Usiadł w kącie pokoju."), not the headword.
   The shared rule that each example shows "its sense or usage note" allows
   this. It is inherited from the French template, not caused by the Polish
   fields.
4. **Glosses stacked with "or":** "To go on foot, to set off, or to head
   somewhere" and "Pretty, nice, or good-looking". The inherited rule bans only
   slash stacks. For a beginner a short list of glosses is arguably a help.
5. **Spelling Check for `bać`:** it says "OK" although the headword gains
   `się`. Phase D should check whether the app displays or stores this
   section before treating it as a defect.
6. **"obiad" rendered as "dinner":** acceptable, but the midday main meal is
   often rendered "lunch". This is a matter of style.

Usage notes appeared in nine of ten entries in each run, although the prompt
makes them optional. Every note carried a real beginner fact: an irregular
form, the case a word takes, or a confusable word. So for this learner the
near-default note is a feature, not padding.

My review is an informed reading, not a native speaker's judgment or a
dictionary check. Item 2 especially should be confirmed by a native speaker.

## Latency

| Set | Median | Mean | Range |
|---|---|---|---|
| Polish run 1 | 4.6 s | 4.8 s | 3.8-6.6 s |
| Polish run 2 | 5.2 s | 5.5 s | 3.6-9.8 s |
| Polish probes | 4.4 s | 4.6 s | 3.1-6.7 s |
| French and German shipped prompt, same day (`results/shipped-2026-11-18-hydrogen-low-subset10.json`) | 4.2 s | 4.6 s | |

The Polish prompt is about 30% longer than the French one. On these samples
it costs well under a second per call. The 9.8 s outlier (`mężczyzną`, run 2)
did not recur in run 1 (5.5 s).

## Scorer change

`content_words` used `[a-zà-ÿ]+`, which split `napisać` into `napisa`. It
now uses `[^\W\d_]+`. `perfective` and `imperfective` joined the stop words,
so two senses that both end with a partner label are not counted as
restatements. To check that French and German scores did not move, I took
copies of all eighteen saved vocabulary results. I re-scored each copy twice,
once with the scorer and panel at `7d91cc9` and once with the changed ones.
All 482 scored responses produced identical score dictionaries and
identical summaries. The committed result files were not touched.

## Verdict

The v1 candidate is fit to ship as the Polish prompt in Phase D. Across two
runs it passed 20 of 20 panel words, with no hedge, no restatement, no
invented sense and no grammar defect in the panel responses. It kept aspect
and `się` correctly, named every aspect partner, and kept the minimal pair
`sad`/`sąd` apart. Its notes were the kind of fact a beginner needs.

The limits are these. There were ten words and one model at one thinking
level. The probes showed one mistranslated example (`przez`). The reviewer
was not a native speaker. Watch for these after shipping: example
translations of spatial prepositions, the possessive `swój`/`mój`, and
whether the usage note keeps carrying a real fact.
