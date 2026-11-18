# Polish on the phone: the header at 320px, the hue, the badges

Evidence, 2026-11-18. Never edited after landing; a correction is a new dated
report that links this one.

## Method

The real `vocabbuilder-mobile` app (`build_mobile_catalog` with fr, de, en
and pl over a throwaway data directory, served by uvicorn) was driven with
Playwright 1.58.2 in WebKit 26.0 and Chromium 145. The entry count was set by
rewriting `/api/status` and `/api/collections` in the browser; the
three-collection rows drop Polish from `/api/collections`. Widths are CSS
pixels from `getBoundingClientRect`; "lines" counts the line boxes of the
count button. WebKit and Chromium agreed to 0.1px on every header row below.

## Header before the fix (four collections)

At 320px the bar's content box is 284px. The four language buttons take
150px. Nothing overflowed the page, but the count wrapped at every count,
and the theme toggle (declared 34px) and the connection dot (30px) were
squeezed by flex shrink:

| Count | Lines | Count px | Theme px | Dot px |
|---|---|---|---|---|
| 9 | 2 | 51.5 | 27.9 | 24.6 |
| 573 | 2 | 58.4 | 24.2 | 21.4 |
| 1,234 | 2 | 62.5 | 22.1 | 19.5 |
| 12,345 | 2 | 64.8 | 20.8 | 18.4 |

With three collections at 320px, "573 words" sat on one line (77.1px) and
"1,234 words" already wrapped. No spacing change alone puts "573 words" on one
line beside four pills: 284px minus the toggle, the dot and three gaps leaves
less than the 150px switch plus the 77.1px count.

## Header after the fix

`.bar` gap 10px to 6px, and `flex: none` on `.langs`, `.theme` and `.conn`.
The count is the only item that gives way, and it stacks its number over its
noun. Four collections:

| Width | Count | Lines | Count px | Theme px | Dot px | Bar slack px |
|---|---|---|---|---|---|---|
| 320 | 9 | 2 | 52.0 | 34 | 30 | 2 |
| 320 | 573 | 2 | 52.0 | 34 | 30 | 2 |
| 320 | 1,234 | 2 | 52.0 | 34 | 30 | 2 |
| 320 | 12,345 | 2 | 58.5 | 34 | 30 | -4.5 |
| 360 | 573 | 1 | 77.1 | 34 | 30 | 2 |
| 360 | 1,234 | 2 | 84.4 | 34 | 30 | 2 |
| 375 | 1,234 | 1 | 89.8 | 34 | 30 | 2 |
| 375 | 12,345 | 1 | 98.3 | 34 | 30 | 2 |
| 393 | 12,345 | 1 | 98.3 | 34 | 30 | 2 |

The page's `scrollWidth` equalled the viewport on every row. At 12,345 words
and 320px the dot runs 4.5px past the bar into the app's 16px gutter; the
page still does not scroll. Three collections at 320px now keep
"1,234 words" on one line.

## Hue

Petrol teal, chosen in OKLCH at hue 215, between the French blue (262) and
the `--ok` green (155). Lightness and chroma follow the other hues in each
theme.

| Theme | Hex | `--bg` | `--card` | `--on-hue` | OKLab distance to `--ok` | to French |
|---|---|---|---|---|---|---|
| light | `#115664` | 6.91:1 | 7.80:1 | 8.12:1 | 0.098 | 0.094 |
| dark | `#7ac1d2` | 9.17:1 | 8.30:1 | 9.14:1 | 0.089 | 0.089 |

The brief's starting values, `#1d5b63` and `#74c2c9`, also cleared contrast
(light 6.43:1 on `--bg`, dark 8.23:1 on `--card`). They sat 0.080 and 0.074
from `--ok`, closer than any existing pair. The nearest existing pair is
German and `--ok` in light, 0.130. Moving the hue from about 205 to 215 bought
`--ok` distance in every simulated colour-vision deficiency (Machado 2009,
full severity). The light deuteranope distance went from 0.078 to 0.098.
Under tritanopia the dark Polish and `--ok` are 0.032 apart. That is close,
but the existing French and `--ok` pair is 0.046 there. Each pill also carries
its code as text. The weakest existing hue, German in light, is 4.92:1 on
`--bg`.

## Badges

These are `.index-type` widths at `--t-3xs`, uppercase, at 320px. The
existing `V. PRON.` measured 49.6px, as `docs/mobile_glossary.md` records.

| Type | Badge | px |
|---|---|---|
| masculine noun | M. | 13.7 |
| feminine noun | F. | 9.9 |
| neuter noun | N. | 12.3 |
| plural noun | PL. | 17.9 |
| imperfective verb | V. IMPF. | 44.7 |
| perfective verb | V. PF. | 31.3 |
| biaspectual verb | V. BI. | 29.6 |

At 720px every badge sits in the 56px (3.5rem) track, and every gloss
starts at the same left edge: 240.5px in WebKit, 245.2px in Chromium.
