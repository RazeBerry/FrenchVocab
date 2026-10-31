# Private mobile interface: front end

Contract: invariants only. Routed from `docs/mobile_map.md`; dated evidence lives
in `reports/` and is linked from the rule it supports.

## Shell and views
- Plain HTML/CSS/JS with no build step and no external requests (Tailscale-only hosts may have no public egress).
- The five implemented views are Capture, Translate, Library, Practice, and Tools. The production navigation exposes Capture, Translate, and the glossary-backed Library; Practice and Tools remain marked `hidden` until their presentation is ready. English is monolingual, so capability data from `/api/status` removes Translate and leaves Capture and Library. Hiding a view must not remove its tested backend capability or durable state.
- `app.js` is only the shell and view dispatcher. `api.js`, `ui.js`, `entry-list.js`, and the `*-view.js` modules own transport, shared presentation, and one workflow each. Keep server rules on the server and keep view-local DOM/state out of the shell.
- A view counts as loaded only when its data arrived. `LibraryView.activate` and `TranslationView.activate` set `loaded` from the result of the load. Setting it unconditionally left the glossary empty after an offline launch, reading "No entries match that search", and hid every word saved from the Mac until a save on the phone.
- A language switch never waits on the network to show the collection it switched to. The phone keeps each collection's last `/api/status`, its last ledger, and its last glossary index and census in memory (display only; no decision is made from them), fetches the other collections' status and ledger once in the background after boot, and paints from memory on the tap while the fresh answers are one round trip away. The current view activates beside the status request rather than after it; only the translator waits, because status may close it. The tap first lets the pressed collection paint, then renders; a second tap before that frame supersedes the first. Over the relayed tailnet a round trip measured 125-196 ms, and a return to the glossary showed its rows after about 435 ms; it now takes about 140 ms at a 4x CPU slowdown. A fresh index that matches the rows already painted is not rendered again, because 573 identical rows are a second long task.
- `/api/status` carries `collection_version`, the loaded collection file's (device, inode, mtime_ns, size). When the app returns to the foreground the glossary re-reads only if that version changed, so a word saved from the Mac appears without paying about 94 kB per foreground. The translator keeps its pre-existing behavior of reading only on activation.
- Every mutating flow is preview/confirm or an explicit tool action. Disable repeated submissions while a request is active, use idempotency tokens supplied by the server, and ignore stale responses after a language or view change.
- `/`, `/manifest.webmanifest`, `/service-worker.js` and everything under `/static` must send `Cache-Control: no-cache`. Unversioned resources otherwise fall back to heuristic freshness that grows with file age, so an installed home-screen app can serve a stale shell for days after a deploy. Keep assets unversioned and let ETags make revalidation cheap.
- Static assets carry **no version query**. `RevalidatingStaticFiles` sends `Cache-Control: no-cache` on everything under `/static`, so a changed file is picked up on the next load without any manual bump; the network-first service worker already makes that request, and the ETag answers 304 with no body. Do not reintroduce `?v=N`: a stale one is worse than none, because it silently pins the old asset.
- The service worker caches only `response.ok` responses. Caching everything let a 502 during a restart, or a 403, replace the good shell that the offline fallback serves.
- `SHELL_CACHE` is a stable name. The activate handler purges every cache except the current name, and network-first overwrites entries in place, so it never needs versioning either.

## Capture
- In the capture actions the solid button **always commits the previewed entry**, the ghost always leaves without writing (Discard or Cancel), and a different way to commit -- "Translate instead", "Keep "flaner" as typed", "Keep a separate variant instead" -- sits in the tertiary `#alternative-button` link, whose action each state sets explicitly. The ghost once saved the typed spelling or left for the translator, which gave a corrected preview no exit that did not write; before that, routing sat in the solid slot while the ghost wrote to disk.
- Capture dispatches on an explicit mode (`capture` / `looking` / `collected` / `preview`),
  never on whether `this.preview` happens to be truthy. Inferring the state that
  way left the solid button reading "Look it up" and still enabled while a
  duplicate was on screen, so tapping it re-sent the request that had just been
  rejected. In the collected state the solid button commits the decision to
  change nothing ("Keep what I have") and the ghost carries the alternative that
  costs a provider call.
- A look-up in progress is the `looking` state of the same slip: the typed word
  takes the headword's place, `.pos` reads "French · looking it up", three
  decorative bars stand where the meaning will be (they breathe only without
  reduced motion), and a line names the provider with an elapsed-seconds
  counter that is hidden from assistive technology so it is not announced
  every second. The field is hidden, which also locks it: typing during a
  look-up used to re-enable the button and start a second paid request. The
  ghost button is Cancel, the one control enabled while busy; it aborts the
  `capture-ai` request in the browser and returns to the typed word, or to the
  collected entry a merge look-up started from. The server still finishes the
  generation behind the per-language AI lock, so the next look-up can wait for
  it; nothing is saved.
- Merge copy counts both kinds of addition wherever it appears: the button
  ("Add 2 senses, 1 example"), the ribbon ("+2 senses, +1 example") and the
  receipt ("gained 2 senses and 1 example"). Counting only senses undersold a
  write the ledger then reported in full. The solid capture button takes a
  1.5 share of the row because it carries that count.
- The capture draft key is chosen after the first status arrives. The view used
  to start as `fr`, so French was the one language whose draft never came back.
- Held/new marking on senses and examples is rendered as real elements, never as
  CSS `content:`, which is not reliably announced by a screen reader.
- There is one busy idiom app-wide: the label states what is happening ("Looking it up…", "Saving…", "Translating…"). The spinner this replaced was hidden under `prefers-reduced-motion`, which left capture with no visible feedback across a request that can run two minutes.
- `.message` defaults to the failure colour. Anything that is neither a failure nor a confirmation — a spelling correction, say — must pass `{ note: true }` rather than shipping as red; `{ ok: true }` stays for confirmations.
- The studied language keeps the display face wherever it appears, including the saved-pairs list. Styling by column position instead demoted it to dim sans whenever the direction ran target -> English.
- Capture drafts persist locally per language. Provider keys never enter local or session storage; they are submitted directly to the private settings endpoint and the server response never echoes them.
- The interface is a single "specimen slip": one card carries capture and preview. `.slip.is-capturing` is the blank state (the `textarea` is the headword), and the same slip fills in with the preview rather than swapping to another component.
- The whole capturing slip is the writing surface: a click anywhere on it focuses the headword. Without that, only the `textarea`'s own line box accepts a tap — a 39px target inside a card several times its height.
- A text field **always** matches `:focus-visible` while focused, so a blanket `textarea:focus-visible` outline boxes the headword on every tap, inside the slip's own dashed outline. The generic ring excludes `.hw` and `.slip.is-capturing:focus-within` carries the focus treatment instead; the caret remains the in-field indicator.
- `.hw` transitions `font-size` between steps, so a `scrollHeight` read on the same input event still belongs to the previous, larger step. Typing hides this because the next keystroke re-measures at the settled size; a paste delivers one event and left the field pinned at 141px for 22px of content. `autoGrow` must therefore also run on the `font-size` `transitionend`.
- The capture placeholder is language-neutral ("Type a word") because `.pos` already names the collection directly beneath it and the language switch carries it a third time. A language-specific placeholder cannot wrap, and at `--hw--s1` it clipped mid-word for German and English on every phone width tested.
- `.stage` reserves no viewport height. The slip hangs from the top and grows downward as it fills, with the capture actions right under it; a 54vh stage that centred the blank slip left about 140px of empty paper above it and 170px below, while the Recently kept ledger showed one row. The stage's top padding is the room the deck's back cards need.
- Every `vh`/`dvh` length here measures the layout viewport, and iOS does not shrink that when the software keyboard opens — only the visual viewport shrinks. `.stage` therefore went on reserving 54vh, 460px of an iPhone 14 Pro's 852px, while just 516px stayed visible, leaving the capture actions 145px below the fold on the one screen the app opens to. `ui.js` publishes the covered height as `--kb` from `visualViewport` and stamps `.is-keyboard` on `<html>`; the rules under it re-fit the capture column to what is actually on screen and drop the furniture the keyboard already covers. Safari ignores the `interactive-widget` viewport key, so there is no declarative fix. Measure the inset as `innerHeight - visualViewport.height` and nothing else: `offsetTop` says where the visual viewport sits, not how tall it is, so subtracting it under-reports whenever iOS scrolls to keep the caret visible, and far enough would drop the inset back under the threshold mid-keystroke and flicker the whole column.
- A shrunken visual viewport is not sufficient evidence of a keyboard: desktop
  zoom can create the same geometry and used to hide the tab bar, recent list,
  and footer. Apply `.is-keyboard` only when the inset clears the threshold, the
  device reports touch capability, and an editable field is focused. Keep the
  inset calculation itself as `innerHeight - visualViewport.height`.
- Headword sizing steps through `.hw--s1/2/3` at 14 and 28 characters. The breakpoints come from the stored collections (87% of French headwords are <= 14 characters, 2% are long expressions); re-measure before changing them.
- Long AI responses are deferred, never dropped: the collapsed slip shows the first sense plus one example, and `#more-button` expands the rest, pinning the headword and scrolling `.slip-body`. `/api/save` still commits every definition and example.
- The Recently kept strip is a ledger, not a fixed eight rows: it requests
  `/api/recent?limit=30` and shows every record from today plus enough earlier
  ones to reach eight. Eight alone silently dropped the morning's words on a
  heavy study day.
- The merge mark ("merged · +2 senses, +1 example") is built only from the
  counts the write recorded — `added: {definitions, examples}` on the record —
  never recomputed in the browser. It is absent when the field is missing or
  both counts are zero. Counts take `--pending`, the rest `--dim`; zero clauses
  are omitted and copy inflects at 1 and n.
- The just-saved row is matched by the word the save receipt returned, not by
  position, because the list is re-fetched after the save and another session
  can have written above it. It is cleared on the next look-up or language
  change, and wears the open row's hue rule and `--hue-wash`, declared before
  the open-row rule so opening it still takes the card ground.
- The just-saved slide is `.is-landing`, granted by the capture view to the one
  render that follows the receipt and withdrawn immediately after. The static
  highlight `.is-just-saved` persists until the next look-up. Keeping the
  animation on the persistent class replayed it on every refresh that rebuilt
  the list while the word was still remembered.
- The capture slip's expander animates the same way, with one extra constraint: once `.slip.is-expanded` applies, `.slip-body` becomes `flex: 1 1 0%`, so flex layout owns its main size and the `height` property is ignored. The tween therefore adds `.is-animating`, which opts the body out of flex growth for the duration; it animates to the flex-resolved height, so handing it back changes nothing. Always release that class on a timeout as well as `transitionend` — a zero-duration tween under reduced motion or a second tap mid-flight can swallow the event and leave the body pinned at a stale height.

## Theme, tokens and scales
- All colors are CSS custom properties on `:root`, re-declared in one `:root[data-theme="dark"]` rule. Style components through the tokens; never hardcode a color inside the dark rule, or it will not apply in light mode.
- The grey ramp is tuned against the surface each step actually sits on, not by eye: `--dim` clears 4.5:1 on `--bg`, `--placeholder` clears it on `--card`, and `--ghost` is a large-text-only whisper at 3.4:1. `--ghost` therefore carries the headword placeholder and nothing else; the small blank-state lines use `--placeholder`. Check both themes when retuning — the light theme is the one that fails first.
- Every sheet is the same paper. `--card` is the warm `#faf8f5` step, and
  there is no second card token: a pure white card on the rice ground did not
  brighten the paper, it left it, about 7 L* lighter and 4 C* less saturated
  in one step, so the open glossary panel read as a different material while
  a 44px white button had passed as a control. Collapsing `--card-blank` into
  `--card` fixed the whole surface family with one value and retuned nothing,
  because `--placeholder` had been measured against that step already.
- A segmented control selects the way the chips select, with the collection
  hue on `--on-hue` text, and its track is `--card` with the `--line` border.
  The raised white tab it replaced was a second answer to "which is selected"
  on the same row, on a translucent track that resolved to a grey the palette
  never declared.
- Never express a disabled or de-emphasised state as `opacity` on a control that contains its own label. Compositing fades the label and the fill together, so their contrast against each other collapses regardless of how the tokens are set; the disabled primary button reached 1.96:1 that way, in the state the app opens in on every launch. Restate the surface and keep the label at strength.
- Theme is an explicit choice, not an ambient one. An inline script in `index.html` stamps `data-theme` on `<html>` before first paint (seeded from `prefers-color-scheme` only on a first visit, then from `localStorage`); the toggle writes that key. Keep the stamping inline and before the stylesheet, or the page flashes the wrong theme, and keep `THEME_BACKGROUND` in `app.js` matching `--bg` so the iOS status bar follows.
- The collection switch shows each collection's code (FR, DE, EN) in its own hue, and the pressed one fills with that hue. Three unlabelled dots had to be tapped to learn which was German. The code is `aria-hidden` and the button's accessible name stays the language name. At 320px the bar still fits without overflow.
- Sizes are chosen from scales, never invented. `--t-3xs` through `--t-3xl` for type, `--r-xs/sm/md/pill` for radii, `--dur-fast/--dur/--dur-slow` with `--ease` for motion, and `--tap` (44px) / `--tap-lg` (48px) for tap targets — the taller step for controls that commit something or accept typing. If a value seems to need a step that does not exist, add the step deliberately rather than hardcoding a one-off; the drift this replaced had 31 distinct font sizes, seven of them within 1.3px of each other.
- The scale governs type, radii, motion and tap targets. Layout dimensions — card heights, the tab bar, the stage — are not tap targets and stay literal; forcing them onto a step would be false precision. The failure mode to watch for is the same property spelled two ways in adjacent rules (`min-height: 44px` beside `min-height: var(--tap)`), which is what `tests/test_mobile_static_contracts.py` pins.
- Each collection owns a hue, selected by `data-language` on `<html>` and read through `--hue`/`--on-hue`. Any new accent must come from those tokens so a new language only adds a hue.
- The page ground is the `--page` gradient painted `background-attachment: fixed`. Anything that has to sit on it — the sticky letter chip, pinned at `top: 0` — paints the same fixed gradient rather than a flat step. `--bg` is the gradient's *lower* stop, so a chip pinned to the viewport top against it leaves a permanently mismatched band.

## Icons and manifest
- The icon is a didone `V` on the blank-slip ground, standing on the collection
  hue's short rule: the display face is the app's identity, and a single
  letterform is the only thing that survives a 16px tab strip. Every colour in it
  must be a token that already exists in `styles.css` — the book it replaced
  shared none of its five colours with the product it opened.
- An XML comment may not contain a double hyphen, so CSS custom-property names
  cannot be written in their `--name` form inside `icon.svg`. A browser does not
  warn about this; it renders the whole icon as a broken image.
- `apple-touch-icon` must point at a PNG. Safari does not accept SVG there and
  silently substitutes a screenshot of the page, so an SVG-only shell has never
  actually had a home-screen icon.
- Plate shape follows who applies the mask. `icon-180.png` (iOS) and
  `icon-maskable-512.png` (Android) are full bleed because the OS rounds them;
  `icon.svg` and `icon-512.png` fill the `any` slot and carry their own `rx`.
  Maskable art is inset to 0.82 so its far corner clears the 80% safe circle.
- `purpose` is never `"any maskable"` on one entry — that lets a launcher
  circle-mask art drawn without a safe zone. Declare the two purposes separately.
- The manifest's `background_color`/`theme_color`, `--bg`, and
  `THEME_BACKGROUND.light` in `app.js` are one value. They disagreed by three
  units and the iOS splash was visibly lighter than the frame that replaced it.

## Copy
- User-visible copy generated in JS (singular/plural on the entry count, on pending Anki entries, on stale tracking records) must inflect correctly at 0, 1 and n. Prefer copy that does not need a language name inflected into it at all — that is why the capture placeholder no longer takes an article.
- Words waiting to be exported are the normal state of the Anki card, not a fault: the pill reads "Ready to export", and only stale tracking — records pointing at words that no longer exist — reads "Needs attention". Clauses whose count is zero are omitted rather than printed as "0 stale tracking records".
- A horizontally scrolling strip looks like a clipped one, and CSS cannot ask whether an element overflows. Views that render into `.segmented` or `.type-chips` call `markScrollable` after populating them, which toggles the mask that signals more content. It engages at 320px-class widths and stays off when everything fits.
