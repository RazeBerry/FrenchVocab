# Thinking level lowered from medium to low

Evidence, 2026-10-31. Never edited after landing; a correction is a new dated
report that links this one. Moved verbatim from `AGENTS.md` by the 2026-10-31
knowledge sweep.

Vocabulary generation, directional translation, and automatic direction detection all think at `DEFAULT_THINKING_LEVEL` in `llm_client.py`, set to low on 2026-10-31 at the user's request, trading entry quality for speed. No workflow passes its own level, so that constant is the one owner. Medium (chosen 2026-09-24, when the 2026-09-24 prompt scored 39 of 43 against 37 at low and a call took about 4.4 s instead of 2.2 s) had become 10-15 s a word: on 2026-10-31 the same Gemini 3.7 request that took 3-5 s in September took 10-20 s, and 3.8 spent 800-1,500 hidden thinking tokens before its first visible one while writing the entry itself took about 1 s. Low has no thinking tokens and took a median 3.5 s. The cost is measured, not assumed: ten flaky panel words at each level on 3.8 (`results/shipped-2026-10-31-gemini38-{low,medium}-subset10.json`) scored 7 to 5 for low on the panel, but the scorer passed low's "gratter" without its itch sense and failed medium's correct "travée", and three blind Sonnet reviewers preferred medium 17 to 6 with 7 ties. Low imported "backtrack" into "rudern" from *zurückrudern* and dropped the itch sense of "gratter", the defects the 2026-09-24 audit targeted. Change the level only with a panel run saved in `scripts/prompt_panel/results/`.

## Latency, 2026-10-31

Ten panel words, shipped prompt, the app's request config, google-genai 2.25,
Mac to Google directly, 3.7 and 3.8 interleaved per word. Medians:

| model | thinking | total | first visible token | thinking tokens | visible tokens |
|---|---|---|---|---|---|
| gemini-3.7-flash | low | 3.4 s | 1.6 s | 0 | 185 |
| gemini-3.8-flash | low | 2.9 s | 1.7 s | 0 | 189 |
| gemini-3.7-flash | medium | 11.6 s | 10.5 s | 1,077 | 181 |
| gemini-3.8-flash | medium | 10.2 s | 8.9 s | 839 | 182 |

Visible text streamed at 135-180 tokens/s, about 1 s per entry; the rest of a
medium call is hidden thinking before the first visible token. The same 3.7
request on the same words took 3.0-5.3 s on 2026-09-28
(`results/shipped-2026-09-28-genai-2.25-medium.json`), and no prompt, SDK or
request change landed between the runs, so the slowdown is on the provider's
side. Those September runs did not record thinking-token counts, so slower
serving and longer thinking cannot be separated.

## Quality, 2026-10-31

The ten words whose pass/fail had varied between levels in September, one
call each on 3.8 (`results/shipped-2026-10-31-gemini38-{low,medium}-subset10.json`):
low passed 7 at a median 3.5 s, medium passed 5 at 14.2 s with a mean of
1,481 thinking tokens. Three Sonnet reviewers then judged each pair blind,
with the levels hidden and shuffled differently per reviewer, and preferred
medium 17 to 6 with 7 ties (4-3, 6-2, 7-1). All three preferred medium on
"réglisse", "travée", "gratter" and "rudern", and low on "turpitude". No
reviewer checked a dictionary online. The user chose low for speed.
