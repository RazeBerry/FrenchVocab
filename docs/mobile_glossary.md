# Private mobile interface: glossary

Contract: invariants only. Routed from `docs/mobile_map.md`; dated evidence lives
in `reports/` and is linked from the rule it supports.

## Glossary
- Collection stats and Random flashcard each own a separate glossary panel. Their controls coordinate which panel is disclosed and keep `aria-expanded` aligned with it; never render one action's result into the other action's container. Both buttons sit behind the `···` toggle beside the search field (`#library-tools-toggle`), and closing that row closes whichever panel was open.
- On a phone the glossary starts at its search field. Below 560px the page heading is visually hidden (still read by a screen reader), the field's placeholder names the count ("Search 573 words"), and A-Z / Added is one toggle chip at the end of the type-chip row. The heading, the subtitle, a segmented sort pair sharing the chip row and two full-width buttons had pushed the first word to about half the screen height; it now starts at about 29% on a 390 x 844 screen. The desktop frame keeps the heading.
- The collection is an index, not a feed: one row per word (headword, abbreviated part of speech, truncated first sense), and tapping opens the full entry **in place**. Only one row is open at a time. Both the initial index and search results carry only those finder fields; rich definitions and examples load only for the row that opens. Large HTTP responses are gzip-compressed because the private VM link is the dominant search cost.
- Below 560px an index row is one line — headword, badge, right-aligned gloss,
  clipped. At 560px and up the shared `.index-row` becomes a grid with a 15ch
  headword track, a fixed 3.5rem badge track, and the gloss left-aligned and
  clamped to two lines: at the desktop frame a right-aligned nowrap gloss makes
  the eye jump a different distance on every row, and clipping loses the ending
  of a quarter of French glosses and half of German ones (measured:
  first-definition median 62/90 chars fr/de, p90 121/128; headword p90 16/14).
  15ch covers the French p90 headword; re-measure before changing it. The badge
  track is fixed and the badge right-aligned inside it because an `auto` track
  let a wide badge ("V. PRON.", 49.6px at `--t-3xs`) shift that row's gloss
  about 30px off the shared left edge. The gloss is placed at `grid-column: 3`
  explicitly because an entry with no part of speech renders no badge.
- A closed row may clip its headword; an open row never does. The panel does
  not restate the headword, so the open row's `.index-word` wraps
  (`white-space: normal`, `overflow-wrap: anywhere`) inside the width it had
  when closed. Keeping the ellipsis left "C'est de bonne gu…" as the only name
  of the open entry. Wrapping in place keeps the badge where it was.
- Opening a glossary row fills its panel from `/api/library/entry` under the
  same tween, showing the app's busy idiom ("Opening…") in the panel while it
  loads and retargeting the animating height when the record lands. Fetched
  entries are cached per language and cleared on reset, so reopening a word
  costs nothing; a failed fetch closes the row and states why in
  `#library-message`, because an open panel still reading "Opening…" is a lie.
- The letter rail is shown exactly when the rows on screen are the whole
  collection in alphabetical order — not during search, not in Added order, not
  under a type chip — because that is the only state in which its census and its
  jumps are both true. A letter with no words is not a destination, said in
  `--dim` and a lighter weight rather than `opacity`, and a jump resolves the
  rendered `.index-letter` heading, so a letter a filter has emptied simply does
  nothing. The rail as a whole is the drag target: 27 letters at the 44px tap
  floor would be 1,188px of screen, so its letters are 16px marks at `--t-3xs`
  (432px, which clears the tab bar on a 667px phone) and the same jump is on the
  A-Z keys. Scrubbing shows the letter large in the display face on the
  collection hue, placed against the rail's own box because the desktop column
  is centred and a fixed offset from the window edge would strand it.
- The glossary answers the keyboard, because desktop Safari at the 720px frame
  is a first-class surface and the CLI it mirrors is arrow-driven: `/` focuses
  search, Up/Down move a highlighted row, Enter opens or closes it (the row is a
  real `<button>`, so that costs no handler), Esc closes the open row and only
  then clears the query, and a bare letter jumps to it. Focus stays on the list
  through a roving `tabindex`, so Tab never walks 573 rows to reach the footer,
  and rows keep `aria-expanded`.
- Three ways lead into the glossary and all three open the same view: the tab
  between Add and Translate, the header word count — the one place the whole
  collection is named on every screen — and the ledger's "All N words". English
  is monolingual, so removing Translate leaves Add and Glossary rather than a
  single tab.
- The glossary's only entry action is "Look up more senses", which hands the
  entry to `CaptureView.showCollected` — the state a duplicate already lands in
  — and switches views. "Practice this" and "Add to Anki selection" are deferred
  with the hidden views they would hand off to. The glossary holds no vocabulary
  rule: it never calls `/api/preview`, `/api/save`, `/api/anki` or
  `/api/practice`, and `app.js` stays the shell that wires the handoff.
- Type chips are categories from `/api/library/stats`, which counts each
  distinct stored type exactly, so a chip keeps exactly the rows whose type
  equals its name (casefolded): "verb 162" shows 162 rows. The filter runs on
  the loaded index in the browser because refetching `/api/library?word_type=`
  would drop the letter census, change the row shape, and truncate silently
  at the page ceiling. The contains-match that endpoint applies is a search
  rule, not a category rule; using it here made the chip's count and its rows
  disagree.
- A glossary visit must not cost a capture draft. `showCollected` holds the
  field's text when the word it was handed differs from what the field says,
  and `dismissToBlank` restores that draft instead of blanking the field.
  A duplicate raised by the field itself holds nothing, because the text in
  the field is the word that was rejected. Blanking unconditionally was right
  for the duplicate path and silently discarded an unrelated draft after
  "Keep what I have" or a merge that began in the glossary.
- The glossary footer names the instrument the reader actually has: below 560px
  "573 words · 22 letters · tap a row, or drag the rail", and at 560px and up
  "…, or press / to search". Counts inflect at 1, and a search states how many
  of its matches are shown when the endpoint's 200-row ceiling truncated them,
  rather than dropping the rest silently.
- The searched fragment is marked with a real `<mark>` element inside the row's
  gloss, styled from `--hue-wash`/`--ink`, never CSS `content:`. The row shows
  the entry's first sense, so a match that lives only in a later sense or an
  example is found but not highlighted; the entry itself is one tap away.
- Glossary rendering builds rows in one detached `DocumentFragment` and commits it once. Roving keyboard focus updates only the previous and next rows; never rescan or rewrite the whole index for one arrow key. Clearing search restores the local index immediately rather than waiting out the network-search debounce. A-Z and Added are local views of the same loaded finder rows: the server ships each row's persisted acquisition rank once, and toggling order never refetches the index from the VM.
- "In place" is enforced, not aspirational. `scrollIntoView` aligns the whole panel and threw the page ~500px, landing the tapped word behind the sticky letter. `reveal()` scrolls **down only**, by the least that brings the panel's bottom above the tab bar, and never further than would push the tapped row out of view — so a panel that already fits produces no movement at all.
- Safari has no scroll anchoring. When a row opens while another is open
  *above* it, `toggleRow` closes that panel in one step and scrolls by its
  height in the same frame, so the row under the finger does not move; only a
  panel below is allowed to tween shut. Chrome hid this defect by anchoring
  the scroll position through the tween, and Safari is the outdoor surface.
- A record that lands in an already-open panel goes through `refit`: mid-tween
  the pinned height is retargeted and the open tween's own `transitionend`
  releases it; once settled at `auto`, the panel is pinned at its on-screen
  height, repainted, and tweened to the new measurement, released on
  `transitionend` or a timer. Replacing the "Opening…" line in a settled
  panel used to jump the page by the panel's height whenever the VM was slow.
- Opening a row animates an explicit pixel height measured in `app.js`, released to `auto` on `transitionend`; `height: auto` is not transitionable and a fixed `max-height` would clip long entries. The starting height is committed with a forced reflow rather than `requestAnimationFrame`, so the transition cannot be skipped by a frame that never arrives.
- `renderEntries` carries three mutually exclusive orders. `grouped` prints
  alphabetical headings, `groupBy: "day"` prints day headings computed in the
  browser from each record's `timestamp` (Today, Yesterday, then weekday + day +
  short month), and the default prints none. Alphabetical dividers must never
  appear over a history- or acquisition-ordered list, so the glossary's Added
  order prints no dividers at all rather than inventing timestamps the finder
  rows do not carry.
- There is one divider object. `.index-divider` carries the sticky chip (the
  `--page` gradient, `background-attachment: fixed`); `.index-day` and
  `.index-letter` add only their layout. Headings are real `<p>` elements with a
  real `.index-count` span, never CSS `content:`, and the count is of the rows
  actually rendered rather than the server's census, so a type chip cannot leave
  a heading claiming rows it filtered out.
- Each finder row carries the `letter` the server filed it under, and the
  browser prints dividers from that field without deriving a letter of its
  own. A bare NFD pass in the browser filed `Œuvre` under `#` while the server
  sorted it among the O's, which printed that divider in the middle of the O
  block and offered a rail letter the list never reached; mirroring the
  server's ligature table in JavaScript fixed the symptom by duplicating the
  rule. The static contract test now fails if `entry-list.js` normalizes a
  word to find its letter.
- `TYPE_ABBREVIATIONS` is matched longest-first so `separable verb` does not collapse to `v.` and `adjective/noun` does not collapse to `n.`. The French collection alone holds 19 distinct type strings, inconsistently cased, so matching lowercases first; unrecognised values fall back to a truncation rather than being dropped.
- The glossary abbreviates `preposition`, `numeral`, `interjection`,
  `determiner`, `particle`, and `reflexive verb` as `prep.`, `num.`,
  `interj.`, `det.`, `part.`, and `v. refl.`; keep the reflexive form ahead of
  the bare `verb` prefix.
- `Unknown` is the parser's placeholder for a missing part of speech, not a part of speech. `knownType` strips it before either the badge or the full-type heading is built, so the badge is simply absent — it used to render as `UNKN.` on real entries.
