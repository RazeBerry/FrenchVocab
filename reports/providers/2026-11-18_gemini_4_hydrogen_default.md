# Gemini 4 Hydrogen becomes the default

Evidence, 2026-11-18. Never edited after landing; a correction is a new dated
report that links this one. Supersedes the model choice in
`reports/providers/2026-10-29_gemini_3.8_default.md`.

## Choice

The default Gemini model moved from `gemini-3.8-flash` to `gemini-4-hydrogen`
on 2026-11-18 at the user's request for the latest Flash-tier model. Google's
model list (https://aistudio.google.com/docs/models, read 2026-11-18) lists
`gemini-4-hydrogen` as "Gemini 4 Hydrogen" with no stability badge, alongside
`gemini-4-carbon` and `gemini-4-argon`; `gemini-3.8-flash` is still listed as
stable. Third-party migration notes describe Hydrogen as the successor to 3.8
Flash and list its thinking levels as low, medium, high and xhigh, with
`thinking_budget`, `MINIMAL`, explicit `cached_content` and multi-candidate
requests rejected. The application uses none of those, so the request config
did not change. Those notes say long-output continuation needs google-genai
2.34 or later. The application does not use it, so the SDK floor stays at 2.25.

## Panel, 2026-11-18

Ten panel words, chosen for contrast: trancher, peignait, nonobstant, gratter,
multiprise, ausmachen, rudern, Forthaaren, halt and beeilen. The run used the
shipped prompt, `low` thinking, google-genai 2.25 and a direct connection from
the Mac to Google. Both models ran at the same time, one call per word:
`scripts/prompt_panel/results/shipped-2026-11-18-{hydrogen,gemini38}-low-subset10.json`.

| model | passed | median | min | max |
|---|---|---|---|---|
| gemini-4-hydrogen | 7 / 10 | 4.2 s | 2.8 s | 6.8 s |
| gemini-3.8-flash | 8 / 10 | 3.1 s | 2.2 s | 4.1 s |

The two models disagreed on four words:

- **rudern:** Hydrogen passed and 3.8 failed. 3.8 again imported "backtrack"
  from *zurückrudern*. Hydrogen gave "flail one's arms" instead, which is correct.
- **ausmachen:** Hydrogen failed and 3.8 passed. Hydrogen dropped the
  "arrange or agree on" sense.
- **gratter:** Hydrogen failed and 3.8 passed. Hydrogen dropped the itch sense,
  the same defect 3.8 showed at low on 2026-10-31. 3.8 passed only because
  sense 1 mentions relieving an itch.
- **Forthaaren:** both failed, differently. Hydrogen "corrected" the word to the
  unrelated *fortfahren*. 3.8 kept the misspelling as the headword.

Ten words with one call each cannot separate the two models on quality.
The latency gap of about 1.1 s at the median comes from one paired session and
should be measured again before thinking-level decisions rely on it.
