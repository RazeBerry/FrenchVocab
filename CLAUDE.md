# Repository Guidelines

## Repository Knowledge Contract
- `AGENTS.md` is the canonical repository guide. `CLAUDE.md` is its generated,
  byte-for-byte mirror so every coding agent receives the same architecture,
  workflow, deployment, security, and design knowledge.
- Edit `AGENTS.md` only; never maintain `CLAUDE.md` independently. After any
  guide change, run `python scripts/sync_agent_docs.py --write`, and commit both
  files in the same change.
- Treat durable changes to behavior, architecture, ownership boundaries,
  persistence, concurrency, deployment, security, configuration, testing, or
  product design as incomplete until the canonical guide reflects them.
- Run `python scripts/sync_agent_docs.py --check` for the fast byte-level check
  and `pytest tests/test_agent_docs_sync.py` for regression coverage. Dedicated
  CI also rejects a divergent mirror.
- Byte equality proves shared text, not complete knowledge. During review,
  explicitly verify that a change did not leave either guide semantically stale.

## Project Overview
VocabBuilder is an AI-assisted CLI for building bilingual or monolingual vocabulary lists, generating LaTeX documents, and exporting Anki decks. The current app supports English (`en`), French (`fr`), and German (`de`), has Rich-based keyboard navigation, and integrates with Google Gemini or Anthropic Claude. Install with `pip install vocab-builder` and run `vocabbuilder`.

An optional private web interface (`vocabbuilder-mobile`, extras `[mobile]`) serves the same collections to a phone or browser over Tailscale. See `docs/MOBILE.md` for the deployment topology.

## Project Structure and Module Organization
- All source code lives under the `vocab_builder/` package.
- `vocab_builder/cli/main.py` is the primary CLI entry point.
- `vocab_builder/cli/` contains bootstrap flow, interactive menu/navigation helpers, and compatibility shims.
- `vocab_builder/core/` contains application workflows (vocab ingestion, translators, auto translator, Anki export, LLM/provider lifecycle, history logging, menu/session UI helpers).
- `vocab_builder/core/providers/manager.py` encapsulates provider selection, credential validation, and secure storage.
- `vocab_builder/languages/` contains language registry, validators, prompts, and LaTeX/Anki configuration (`english.py`, `english_tex.py`, `french.py`, `german.py`, `german_tex.py`).
- `vocab_builder/` root modules (`models.py`, `anki_exporter.py`, `latex_repository.py`, `llm_client.py`, `ui_helper.py`) provide shared infrastructure.
- `vocab_builder/compat.py` provides backward-compatible helpers for env vars, config paths, and keyring migration.
- `vocab_builder/diagnostics/` contains ESC latency tracing tools.
- `vocab_builder/mobile/` contains the optional FastAPI web interface, headless mobile use-case adapters, durable request state, and its no-build static front end.
- `FrenchVocab.py` is a deprecated shim that delegates to `vocab_builder.cli.main`.
- `scripts/` contains utility and demo scripts, including `scripts/bulk_add.py` for operator-reviewed structured JSON vocabulary batches.
- `scripts/deploy/` holds VM provisioning and backup scripts; `scripts/macos/vocab` is the Mac launcher for the remote CLI.
- `deploy/` holds the systemd unit and timer files for the mobile server and its daily backup.
- `tests/` is a pytest suite (`test_*.py`) for architecture boundaries, onboarding, translators, language config, exporters, and UI behavior.

## Build, Test, and Development Commands
```bash
# Install (editable / development)
pip install -e .

# Run the CLI
vocabbuilder --help
vocabbuilder --language fr
vocabbuilder --language de
vocabbuilder --language en
vocabbuilder --language fr --provider gemini
vocabbuilder --language fr --provider claude
vocabbuilder --language fr --latex-file ./FrenchVocab.custom.tex
vocabbuilder --language fr --eager-llm
python -m vocab_builder --help

# Diagnostics and demos
vocabbuilder --esc-debug
vocabbuilder --esc-debug --esc-debug-log /tmp/esc_latency.log
python scripts/demo_guided_onboarding.py

# Operator bulk-add workflow
python scripts/bulk_add.py --language fr --file entries.json --dry-run
python scripts/bulk_add.py --language fr --file entries.json --json

# Private mobile/web interface (requires the [mobile] extra)
pip install -e ".[mobile]"
vocabbuilder-mobile --help
vocabbuilder-mobile --languages fr,de,en --default-language fr
vocabbuilder-mobile --languages fr,de,en --allowed-tailscale-user you@example.com
vocabbuilder-mobile --language fr --latex-file ./FrenchVocab.tex

# Repository knowledge synchronization
python scripts/sync_agent_docs.py --write
python scripts/sync_agent_docs.py --check

# Tests
pytest
pytest tests/test_sentence_flow.py
pytest tests/test_agent_docs_sync.py
pytest -k "anki"
```

## Architecture

### Entry Point and Bootstrap
- `vocab_builder/cli/main.py` parses CLI args (`--language`, `--provider`, `--latex-file`, `--verbose`, `--esc-debug`, `--esc-debug-log`, `--eager-llm`).
- `vocab_builder/cli/bootstrap.py` builds language-specific `VocabBuilder` instances and language selection flow.
- `vocab_builder/core/menu_loop.py` drives menu orchestration; `vocab_builder/cli/menu.py` remains a compatibility shim.
- `pyproject.toml` defines the `vocabbuilder` console script entry point.

#### Remote interaction cost
- The CLI is routinely driven over SSH through `scripts/macos/vocab`, so treat
  keystrokes and redraws as billed at network latency, not as free local work.
- `vocab_builder/cli/navigation.py` renders menus with `Live(auto_refresh=False)`
  and repaints only when the selection moves. Re-enabling Rich's refresh thread
  restreams the whole panel about 24 times a second for as long as a menu is
  open, which is invisible locally and continuous traffic remotely.
- `_read_escape_remainder` stops as soon as the buffered bytes form a complete
  CSI or SS3 sequence. Without that early exit, every arrow key waits out a full
  `VOCABBUILDER_ESC_SEQUENCE_TIMEOUT` for a continuation byte that never comes,
  and that wait lands on top of the round trip.
- `startup_warmup.start_entry_warmup` runs before provider initialization
  because the first menu refresh blocks on an authoritative entry count.
  Scheduling the parse later leaves nothing for it to overlap with and puts it
  in front of the welcome screen.
- Menus of nine options or fewer print an ordinal in place of the bullet, and a
  digit selects that option outright. Cutting the cost of one arrow press does
  not help if reaching option six still takes five of them, each a round trip
  and a repaint. Above nine the ordinal would need two keystrokes, so those
  menus stay arrow-only and `_numbered_choice` refuses the digit — the affordance
  and the behaviour are derived from the same threshold so they cannot drift.

### Core Application (`vocab_builder/core/`)
- `vocab.py` contains `VocabBuilder`, the main controller.
- `vocab_repository.py` handles LaTeX parsing, persistence, entry indexing, and counts.
- `word_entry_workflow.py` orchestrates end-to-end word capture and save behavior, including explicit saved/routed/skipped outcomes so failed routing or merge paths never masquerade as successful saves.
- `translator.py` and `auto_translator.py` handle directional and intelligent translation flows.
- `text_utils.py` centralizes text normalization and input-type detection.
- `session_ui.py` builds menu/welcome/status screen content.
- `anki_manager.py` coordinates export state and Anki generation, including persistent acquisition order so decks do not inherit LaTeX alphabetization.
- `llm_coordinator.py` manages provider initialization lifecycle, degraded mode, and usage metrics, and uses generation-guarded background init so stale workers cannot overwrite newer provider changes.
- `history_logger.py` writes append-only JSONL history.
- `file_safety.py` provides atomic file operations and backup/restore support.
- `startup_warmup.py` schedules the background LaTeX parse and owns the synchronous-load escape hatch.
- `protocols.py` defines structural typing contracts used by menu/workflow modules.

### Provider and Credential System
- `vocab_builder/core/providers/manager.py` owns provider metadata, setup wizard flows, and storage destinations.
- Gemini defaults to the stable `gemini-3.7-flash` model. Its generation config
  uses thinking levels and omits deprecated sampling parameters (`temperature`,
  `top_p`, and `top_k`) that current Gemini models no longer support.
- `provider_settings()` reports `label` (provider and model on one line, for terse
  surfaces) and `model` (the bare identifier) separately, because the phone names
  the provider in a heading and the model beneath it. Splitting a combined label
  with string surgery in the browser would put a server rule in the client.
- Credential resolution is: environment variable first (including values loaded from `.env`), then keyring fallback, then interactive setup.
- `.env` path resolution order is: `VOCABBUILDER_CONFIG_DIR/.env`, then writable project `.env`, then `~/.vocabbuilder/.env` (falls back to `~/.frenchvocab/.env` for legacy installs).
- Plaintext `.env` fallback writes are atomic, best-effort permission-hardened, and do not retain a stale backup after a successful key rotation.
- Keyring service name is `vocab_builder` (silently migrates from legacy `french_vocab_builder`).

### Language System (`vocab_builder/languages/`)
- `base.py` defines `LanguageConfig`, `TranslatorConfig`, `VocabTemplate`, and `AnkiConfig`.
- `__init__.py` lazily registers/loads language configs and resolves aliases with `get_language_config(code)`.
- `english.py`, `french.py`, and `german.py` define prompts, validators, learning-mode behavior, and Anki metadata.
- English is monolingual: it omits translation workflows and uses plain-English example paraphrases as active-recall cues.
- `english_tex.py` and `german_tex.py` contain dedicated language-specific LaTeX templates.
- `latex_templates.py`, `anki_shared_styles.py`, and `anki_themes.py` provide shared assets.

### Private Mobile Interface (`vocab_builder/mobile/`)
- `cli.py` is the `vocabbuilder-mobile` entry point; it binds `127.0.0.1:8080` by default and never opens a public port.
- `app.py` is an HTTP composition root: it validates private identity, maps requests to one language service, translates domain errors to JSON, and serves the static shell. Keep workflows out of route handlers.
- `service.py` owns vocabulary capture and the durable transaction journal. `library.py`, `translations.py`, `practice.py`, `anki.py`, `settings.py`, and `storage.py` own the other phone workflows; do not grow another all-purpose mobile controller.
- `state_store.py` atomically persists short-lived previews, idempotent receipts, practice attempts, and repairable auxiliary transactions. The LaTeX collections remain authoritative; mobile state is a recovery journal, not another vocabulary database.
- `catalog.py` registers those per-language services and resolves the `?language=` parameter; `factory.py` constructs them.
- The mobile surface constructs every builder with `interactive=False`; no code reachable from a request may prompt. `UIHelper` raises `NonInteractiveError` as a backstop if a future request path accidentally attempts console input.
- Blocking provider and repository work is exposed through synchronous FastAPI handlers so Starlette runs it in worker threads; do not call those workflows directly from an `async def` route.
- Tailscale Serve supplies private HTTPS and identity; provider credentials stay server-side and are never sent to the browser.
- Run exactly one `vocabbuilder-mobile` process worker. Data-file writes remain safe against the separately launched SSH CLI through filesystem locks, but the mobile request journal is an intentionally single-worker state machine.

#### Mobile product philosophy
- The phone and remote Mac CLI are two interfaces to the same application and
  authoritative VM collection, not separate applications or databases. The
  phone should reproduce every meaningful non-interactive CLI capability while
  adapting terminal prompts into touch-friendly preview/confirm steps.
- Preserve one dominant path: capture -> preview -> save. The preview is the
  editorial checkpoint, not a separate destination, and secondary collection
  browsing must not compete with capture above the fold.
- Keep the interface calm and object-centered. Capture and preview inhabit the
  same specimen slip so state changes feel continuous instead of navigating a
  dashboard or multiplying cards, dialogs, and modes.
- Language changes should preserve the same mental model. Express identity
  through the collection hue and grammatical copy rather than separate layouts.
- Progressive disclosure may hide detail, never discard it. The compact phone
  view can defer senses and examples, but save behavior must retain the complete
  structured result used by LaTeX and Anki.
- Mobile capture preserves the CLI's duplicate policy: reject by default, then
  let the user explicitly merge or create a labelled variant. It also preserves
  sentence routing, spelling suggestions, translation history, composition
  scoring, Anki acquisition order, and provider recovery. Do not create a
  second implementation of those rules in JavaScript or route handlers; expose
  headless methods from the shared core and adapt their typed outcomes.
- A word you already own is not an error. The phone answers with the stored
  entry in the filled slip, so the CLI's "view existing" stops being a menu item
  and becomes the state you land in, and offers merge, a labelled variant, or
  keeping what is there. The rejection payload has always carried the whole
  entry; rendering one definition of it into the still-blank capture slip
  painted real content in `--placeholder`, the exact grey of the hint text it
  replaced, and left the only explanation in the failure colour.
- Merge is approved against a diff, never blind. The preview marks which senses
  and examples are already held and which are new, and the commit button counts
  what it will add. That marking is computed on the server by the same code the
  write uses -- `VocabRepository.normalize_text_for_merge` and the
  `new_definitions_for_merge` / `new_examples_for_merge` helpers -- so the
  preview cannot disagree with what lands on disk, and the rule is not
  reimplemented in the browser.
- A duplicate found only after generation, when spelling correction resolves to
  a word already held, returns that merge preview instead of raising. The answer
  is already in memory; raising discarded it and made the user pay for the same
  provider call a second time.
- Destructive vocabulary editing, deletion, and backup restoration are not CLI
  workflows and are intentionally absent from the phone. Recovery artifacts are
  allowlisted, read-only downloads. This is parity with the product's behavior,
  not unrestricted file-system parity.
- Privacy, connectivity, and installability should be legible but quiet:
  Tailscale remains the access boundary, secrets remain server-side, and the
  no-build shell remains usable as an iPhone home-screen app.

#### Mobile front end (`vocab_builder/mobile/static/`)
- Plain HTML/CSS/JS with no build step and no external requests (Tailscale-only hosts may have no public egress).
- The five implemented views are Capture, Translate, Library, Practice, and Tools. The production navigation currently exposes only Capture and Translate; Library, Practice, Tools, and the secondary library link remain marked `hidden` until their presentation is ready. English is monolingual, so capability data from `/api/status` also removes Translate and leaves a single Capture tab. Hiding a view must not remove its tested backend capability or durable state.
- `app.js` is only the shell and view dispatcher. `api.js`, `ui.js`, `entry-list.js`, and the `*-view.js` modules own transport, shared presentation, and one workflow each. Keep server rules on the server and keep view-local DOM/state out of the shell.
- Every mutating flow is preview/confirm or an explicit tool action. Disable repeated submissions while a request is active, use idempotency tokens supplied by the server, and ignore stale responses after a language or view change.
- In the capture actions the solid button **always commits the previewed entry** and the ghost always offers the alternative to committing it. Routing a sentence to the translator sat in the solid slot while the ghost wrote to disk, which read exactly backwards.
- Capture dispatches on an explicit mode (`capture` / `collected` / `preview`),
  never on whether `this.preview` happens to be truthy. Inferring the state that
  way left the solid button reading "Look it up" and still enabled while a
  duplicate was on screen, so tapping it re-sent the request that had just been
  rejected. In the collected state the solid button commits the decision to
  change nothing ("Keep what I have") and the ghost carries the alternative that
  costs a provider call.
- Held/new marking on senses and examples is rendered as real elements, never as
  CSS `content:`, which is not reliably announced by a screen reader.
- There is one busy idiom app-wide: the label states what is happening ("Looking it up…", "Saving…", "Translating…"). The spinner this replaced was hidden under `prefers-reduced-motion`, which left capture with no visible feedback across a request that can run two minutes.
- `.message` defaults to the failure colour. Anything that is neither a failure nor a confirmation — a spelling correction, say — must pass `{ note: true }` rather than shipping as red; `{ ok: true }` stays for confirmations.
- The studied language keeps the display face wherever it appears, including the saved-pairs list. Styling by column position instead demoted it to dim sans whenever the direction ran target -> English.
- Capture drafts persist locally per language. Provider keys never enter local or session storage; they are submitted directly to the private settings endpoint and the server response never echoes them.
- Deployed provider credentials live in `/var/lib/vocabbuilder/.env`, where the non-interactive provider manager can rotate them atomically. `/etc/vocabbuilder/mobile.env` is reserved for the allowed Tailscale identity and non-secret service settings; putting a key there would override the rotatable credential on restart.
- All colors are CSS custom properties on `:root`, re-declared in one `:root[data-theme="dark"]` rule. Style components through the tokens; never hardcode a color inside the dark rule, or it will not apply in light mode.
- The grey ramp is tuned against the surface each step actually sits on, not by eye: `--dim` clears 4.5:1 on `--bg`, `--placeholder` clears it on `--card-blank`, and `--ghost` is a large-text-only whisper at 3.4:1. `--ghost` therefore carries the headword placeholder and nothing else; the small blank-state lines use `--placeholder`. Check both themes when retuning — the light theme is the one that fails first.
- Never express a disabled or de-emphasised state as `opacity` on a control that contains its own label. Compositing fades the label and the fill together, so their contrast against each other collapses regardless of how the tokens are set; the disabled primary button reached 1.96:1 that way, in the state the app opens in on every launch. Restate the surface and keep the label at strength.
- Theme is an explicit choice, not an ambient one. An inline script in `index.html` stamps `data-theme` on `<html>` before first paint (seeded from `prefers-color-scheme` only on a first visit, then from `localStorage`); the toggle writes that key. Keep the stamping inline and before the stylesheet, or the page flashes the wrong theme, and keep `THEME_BACKGROUND` in `app.js` matching `--bg` so the iOS status bar follows.
- `/`, `/manifest.webmanifest`, `/service-worker.js` and everything under `/static` must send `Cache-Control: no-cache`. Unversioned resources otherwise fall back to heuristic freshness that grows with file age, so an installed home-screen app can serve a stale shell for days after a deploy. Keep assets unversioned and let ETags make revalidation cheap.
- The interface is a single "specimen slip": one card carries capture and preview. `.slip.is-capturing` is the blank state (the `textarea` is the headword), and the same slip fills in with the preview rather than swapping to another component.
- The whole capturing slip is the writing surface: a click anywhere on it focuses the headword. Without that, only the `textarea`'s own line box accepts a tap — a 39px target inside a card several times its height.
- A text field **always** matches `:focus-visible` while focused, so a blanket `textarea:focus-visible` outline boxes the headword on every tap, inside the slip's own dashed outline. The generic ring excludes `.hw` and `.slip.is-capturing:focus-within` carries the focus treatment instead; the caret remains the in-field indicator.
- `.hw` transitions `font-size` between steps, so a `scrollHeight` read on the same input event still belongs to the previous, larger step. Typing hides this because the next keystroke re-measures at the settled size; a paste delivers one event and left the field pinned at 141px for 22px of content. `autoGrow` must therefore also run on the `font-size` `transitionend`.
- The capture placeholder is language-neutral ("Type a word") because `.pos` already names the collection directly beneath it and the language dots carry it a third time. A language-specific placeholder cannot wrap, and at `--hw--s1` it clipped mid-word for German and English on every phone width tested.
- Every `vh`/`dvh` length here measures the layout viewport, and iOS does not shrink that when the software keyboard opens — only the visual viewport shrinks. `.stage` therefore went on reserving 54vh, 460px of an iPhone 14 Pro's 852px, while just 516px stayed visible, leaving the capture actions 145px below the fold on the one screen the app opens to. `app.js` publishes the covered height as `--kb` from `visualViewport` and stamps `.is-keyboard` on `<html>`; the rules under it re-fit the capture column to what is actually on screen and drop the furniture the keyboard already covers. Safari ignores the `interactive-widget` viewport key, so there is no declarative fix. Measure the inset as `innerHeight - visualViewport.height` and nothing else: `offsetTop` says where the visual viewport sits, not how tall it is, so subtracting it under-reports whenever iOS scrolls to keep the caret visible, and far enough would drop the inset back under the threshold mid-keystroke and flicker the whole column.
- Sizes are chosen from scales, never invented. `--t-3xs` through `--t-3xl` for type, `--r-xs/sm/md/pill` for radii, `--dur-fast/--dur/--dur-slow` with `--ease` for motion, and `--tap` (44px) / `--tap-lg` (48px) for tap targets — the taller step for controls that commit something or accept typing. If a value seems to need a step that does not exist, add the step deliberately rather than hardcoding a one-off; the drift this replaced had 31 distinct font sizes, seven of them within 1.3px of each other.
- The scale governs type, radii, motion and tap targets. Layout dimensions — card heights, the tab bar, the stage — are not tap targets and stay literal; forcing them onto a step would be false precision. The failure mode to watch for is the same property spelled two ways in adjacent rules (`min-height: 44px` beside `min-height: var(--tap)`), which is what `tests/test_mobile_static_contracts.py` pins.
- Each collection owns a hue, selected by `data-language` on `<html>` and read through `--hue`/`--on-hue`. Any new accent must come from those tokens so a new language only adds a hue.
- Headword sizing steps through `.hw--s1/2/3` at 14 and 28 characters. The breakpoints come from the stored collections (87% of French headwords are <= 14 characters, 2% are long expressions); re-measure before changing them.
- Long AI responses are deferred, never dropped: the collapsed slip shows the first sense plus one example, and `#more-button` expands the rest, pinning the headword and scrolling `.slip-body`. `/api/save` still commits every definition and example.
- The collection is an index, not a feed: one row per word (headword, abbreviated part of speech, truncated first sense), and tapping opens the full entry **in place**. Only one row is open at a time.
- "In place" is enforced, not aspirational. `scrollIntoView` aligns the whole panel and threw the page ~500px, landing the tapped word behind the sticky letter. `reveal()` scrolls **down only**, by the least that brings the panel's bottom above the tab bar, and never further than would push the tapped row out of view — so a panel that already fits produces no movement at all.
- The capture slip's expander animates the same way, with one extra constraint: once `.slip.is-expanded` applies, `.slip-body` becomes `flex: 1 1 0%`, so flex layout owns its main size and the `height` property is ignored. The tween therefore adds `.is-animating`, which opts the body out of flex growth for the duration; it animates to the flex-resolved height, so handing it back changes nothing. Always release that class on a timeout as well as `transitionend` — a zero-duration tween under reduced motion or a second tap mid-flight can swallow the event and leave the body pinned at a stale height.
- Opening a row animates an explicit pixel height measured in `app.js`, released to `auto` on `transitionend`; `height: auto` is not transitionable and a fixed `max-height` would clip long entries. The starting height is committed with a forced reflow rather than `requestAnimationFrame`, so the transition cannot be skipped by a frame that never arrives.
- Letter dividers are rendered only for alphabetical results. `/api/search` returns sorted matches, `/api/recent` returns history order; grouping the latter would print dividers that contradict the order, so `renderEntries` takes an explicit `grouped` flag.
- Group headings normalise diacritics, so `Étourdissant` files under `E` and `Ôter` under `O`, but the letter is taken from the word **as stored** to stay consistent with the server's sort.
- The page ground is the `--page` gradient painted `background-attachment: fixed`. Anything that has to sit on it — the sticky letter chip, pinned at `top: 0` — paints the same fixed gradient rather than a flat step. `--bg` is the gradient's *lower* stop, so a chip pinned to the viewport top against it leaves a permanently mismatched band.
- `TYPE_ABBREVIATIONS` is matched longest-first so `separable verb` does not collapse to `v.` and `adjective/noun` does not collapse to `n.`. The French collection alone holds 19 distinct type strings, inconsistently cased, so matching lowercases first; unrecognised values fall back to a truncation rather than being dropped.
- `Unknown` is the parser's placeholder for a missing part of speech, not a part of speech. `knownType` strips it before either the badge or the full-type heading is built, so the badge is simply absent — it used to render as `UNKN.` on real entries.
- Static assets carry **no version query**. `RevalidatingStaticFiles` sends `Cache-Control: no-cache` on everything under `/static`, so a changed file is picked up on the next load without any manual bump; the network-first service worker already makes that request, and the ETag answers 304 with no body. Do not reintroduce `?v=N`: a stale one is worse than none, because it silently pins the old asset.
- `SHELL_CACHE` is a stable name. The activate handler purges every cache except the current name, and network-first overwrites entries in place, so it never needs versioning either.
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
- User-visible copy generated in JS (singular/plural on the entry count, on pending Anki entries, on stale tracking records) must inflect correctly at 0, 1 and n. Prefer copy that does not need a language name inflected into it at all — that is why the capture placeholder no longer takes an article.
- Words waiting to be exported are the normal state of the Anki card, not a fault: the pill reads "Ready to export", and only stale tracking — records pointing at words that no longer exist — reads "Needs attention". Clauses whose count is zero are omitted rather than printed as "0 stale tracking records".
- A horizontally scrolling strip looks like a clipped one, and CSS cannot ask whether an element overflows. Views that render into `.segmented` or `.type-chips` call `markScrollable` after populating them, which toggles the mask that signals more content. It engages at 320px-class widths and stays off when everything fits.

### Persistence and Concurrency Model
- In the deployed topology, `/var/lib/vocabbuilder` is the only writable source of truth. The phone surface and the Mac `vocab` launcher operate on that VM state; repository-local vocabulary files are migration snapshots, not a second database. Do not introduce bidirectional file sync.
- Every persisted read-modify-write must use `vocab_builder.core.file_safety.file_lock(path)`. It acquires the catalog-wide `.vocabbuilder.lock` before the artifact sidecar `.<filename>.lock`; nested acquisition in one thread is deliberately reentrant.
- Cross-process lock files must remain beside the authoritative data/config root, never in the temporary directory. The systemd service uses `PrivateTmp=true`, so `/tmp` locks would split the phone and SSH CLI into different lock domains and reintroduce silent lost updates.
- Reload authoritative disk state only after acquiring the commit lock. Duplicate checks, merge calculations, insertion decisions, and Anki state reconciliation must be recomputed inside that transaction rather than trusting pre-lock caches.
- Keep a vocabulary mutation, its history append, and its Anki acquisition-order update inside one outer catalog transaction. Continue using atomic replacement for rewritten files and `flush` + `fsync` for append-only JSONL.
- Each language service has a short-lived state lock and a dedicated AI lock. Provider calls are serialized within one language so mutable provider clients and usage counters cannot overlap; separate language services may still generate concurrently. Read-only library/status work remains responsive while capture AI is running.
- Mobile preview releases its state lock across provider recovery and generation, then re-validates duplicates after reacquiring it. Phone saves register Anki acquisition order inside the same catalog transaction as the vocabulary write and history append.
- A vocabulary or translation save is idempotent by its durable preview token. Persist the journal before the primary file mutation, record the primary commit before auxiliary work, and retain incomplete history/Anki steps for replay. A restart after the file write must reconstruct the same receipt rather than duplicate or lose the entry.
- Practice grading records its generated feedback before appending attempt history, then repairs a missing append by stable attempt ID. Auxiliary history failures may produce a visible pending state, but they must never roll back or misreport an already committed primary file.
- A merge that adds nothing must not claim it did. `save()` recomputes the diff
  from reloaded disk state inside the commit lock; an empty diff writes no
  journal entry, leaves the vocabulary file byte-identical, and returns
  `action: "unchanged"`. A non-empty diff records its counts on the transaction
  *before* the primary write, because afterwards the content is already present
  and a re-derived diff would be empty -- replay would then report "unchanged"
  for a merge that really happened. The repository rewrites a merged block and
  returns success whether or not anything changed, so this is the only layer
  that can tell the user the truth.
- Never infer transaction ownership from the presence of a duplicate alone. Recovery may treat stored content as this operation only when the durable pre-write journal and exact/contained structured payload prove it; a competing session's duplicate must remain a conflict.
- Anki tracker writes use a three-way merge of the manager's persisted baseline, current disk state, and local changes so concurrent additions and intentional removals do not overwrite one another.
- `scripts/deploy/backup_mobile_data.sh` takes the same catalog lock with util-linux `flock` before archiving. Any new backup/export path that needs a coherent multi-file snapshot must join that lock domain.
- Repository cache invalidation uses `(device, inode, mtime_ns, size)` signatures. Do not weaken it to timestamps alone.

### Shared Modules (`vocab_builder/`)
- `models.py` defines `WordEntry` and normalization helpers.
- `anki_exporter.py` contains Anki deck export utilities.
- `latex_repository.py` contains low-level LaTeX entry parsing helpers.
- `llm_client.py` defines provider clients and provider factory.
- `ai_prompts.py` and `ai_response_parser.py` contain prompt/response parsing logic.
- `ui_helper.py` centralizes Rich panels, prompts, status messages, and interactive wrappers.
- `compat.py` handles backward-compatible env var, config dir, and keyring service name migration.
- Keep UI messaging declarative via `UIHelper` methods and avoid bare `print()` in new code.

## Coding Style and Naming Conventions
- Follow PEP 8 with 4-space indentation.
- Use `snake_case` for functions/variables and `PascalCase` for classes.
- Prefer dataclasses for config-style objects and use type hints throughout.
- Use ASCII by default; introduce Unicode only when lexically required (for example language samples and LaTeX templates).

## Key Patterns

### Adding a New Language
1. Create `vocab_builder/languages/<lang>.py` with a `LanguageConfig` (copy `french.py` or `german.py`); `learning_mode` selects bilingual versus monolingual behavior.
2. Register it through `vocab_builder/languages/__init__.py`.
3. Add language-specific vocab and translator templates (new `*_tex.py` module if needed); translator config and filename fields are optional (`None`) for monolingual languages.
4. Provide Anki config/templates and optional auto-translator prompt tokens.

### UI Messaging
Route status messaging through `UIHelper` methods:
```python
self.ui.success("Entry saved!")
self.ui.error("Failed", with_panel=True)
self.ui.warning("Duplicate detected")
self.ui.info("Processing...", accent="dim")
self.ui.panel(content, title="Title", border_style="dark_orange")
```

### Interactive Menus
```python
choice = self.ui.interactive_menu(
    "Menu Title",
    [("key1", "Label 1"), ("key2", "Label 2")],
    "Helper text for navigation",
)
```

### Provider Credential Flow
1. Load `.env` from the resolved config path when available.
2. Resolve credentials from environment variables before keyring.
3. Fall back to keyring lookup when env credentials are missing/invalid.
4. Launch guided/advanced interactive setup when credentials are still unavailable.

### Persisting Mutable State Safely
1. Acquire `file_lock()` for the authoritative artifact (which also takes the catalog lock).
2. Reload the current file/index while holding that lock.
3. Repeat duplicate/conflict validation and compute the mutation from the refreshed state.
4. Commit the primary file atomically, then write coupled history/tracker state before releasing the outer transaction.
5. Add a multiprocessing regression test that starts stale independent instances and proves every successful mutation survives. Thread-only tests are insufficient for VM/CLI concurrency.

## Environment Variables
All variables use the `VOCABBUILDER_*` prefix. Legacy `FRENCHVOCAB_*` and `FRENCH_VOCAB_*` names are still recognized via `vocab_builder/compat.py` with deprecation warnings.

- `GEMINI_API_KEY` / `ANTHROPIC_API_KEY`: Provider API credentials.
- `VOCABBUILDER_CLAUDE_MODEL`: Override Claude model ID (default `claude-sonnet-4-6`).
- `VOCABBUILDER_GEMINI_MODEL`: Override Gemini model ID (default `gemini-3.7-flash`).
- `VOCABBUILDER_PROVIDER_TIMEOUT`: Provider request deadline in seconds (default `120`).
- `VOCABBUILDER_PROVIDER_RETRY_COOLDOWN`: Minimum seconds between silent provider re-initialization attempts (default `30`).
- `VOCABBUILDER_ALLOWED_TAILSCALE_USER`: Tailscale login accepted by the private mobile interface; requests are not identity-checked when unset.
- `VOCABBUILDER_CONFIG_DIR`: Override directory used for `.env` storage/loading.
- `VOCABBUILDER_SKIP_KEYRING=1`: Disable keyring lookups/storage.
- `VOCABBUILDER_FORCE_SYNC_LOAD=1`: Force synchronous loading (useful in tests).
- `VOCABBUILDER_ESC_SEQUENCE_TIMEOUT`: ESC key sequence timeout in seconds (default `0.03`).
- `VOCABBUILDER_ESC_DEBUG=1`: Enable ESC latency tracing.
- `VOCABBUILDER_ESC_DEBUG_LOG`: Custom log path for ESC latency tracing.
- `VOCABBUILDER_DEBUG_EXPORT=1`: Print export debug details during Anki generation.
- `VOCABBUILDER_AUTO_TRANSLATOR`: Enable/disable intelligent translator option.
- `VOCABBUILDER_COMPOSITION`: Enable/disable composition practice (default on).
- `VOCABBUILDER_EXIT_SNAPSHOT`: Enable/disable the automatic complete Anki snapshot on clean exit (default on).
- `VOCABBUILDER_ANKI_EXPORT_DIR`: Operator-controlled root for default and unattended Anki exports. When set, clean-exit snapshots never reuse an explicit absolute destination from migrated tracker metadata; the VM sets this to `/var/lib/vocabbuilder/exports`.
- `VOCABBUILDER_COMPOSITION_WORDS`: Target words per use-these-words attempt (default `3`, int >= 1).
- `VOCABBUILDER_COMPOSITION_SET_SIZE`: Attempts per daily composition set (default `3`, int >= 1).
- `VOCABBUILDER_MAX_BACKUPS`: Maximum timestamped backup snapshots to retain per file (default `10`; `0` disables pruning).
- `VOCABBUILDER_MAX_CHARS`: Override maximum input length.
- `VOCABBUILDER_MAX_WORDS`: Override max words allowed per input.
- `VOCABBUILDER_SENTENCE_MODE` / `VOCABBUILDER_ALLOW_PUNCT`: Toggle punctuation/sentence acceptance.
- `VOCABBUILDER_ROUTE_SENTENCES`: Toggle sentence routing behavior.
- `VOCABBUILDER_SENTENCE_EXAMPLES`: Toggle sentence examples in vocab entries.
- `VOCABBUILDER_HISTORY_DISABLED` / `VOCABBUILDER_HISTORY_ENABLED`: Disable/enable translation history logging.
- `VOCABBUILDER_HISTORY_DIR`: Override history log directory (default `~/.vocabbuilder/history`).
- Boolean flags accept typical truthy values such as `1`, `true`, `yes`, `y`, and `on`.

## Testing Guidelines
- Keep tests mirrored to modules (for example `vocab_builder/core/vocab.py` -> `tests/test_sentence_flow.py`).
- Name new files `test_<feature>.py` and test functions `test_<behavior>`.
- Use stubs/fixtures (`tests/_stubs.py`) to avoid real API calls.
- Concurrency changes must cover both in-process threads and POSIX processes. Keep the isolated-`tempfile.tempdir` regression in `tests/test_concurrency_transactions.py`; it models systemd `PrivateTmp` without touching production data.
- Mobile changes should exercise the ASGI surface in `tests/test_mobile_service.py`, including duplicate commits, save retries, language routing, Tailscale identity enforcement, and cross-language worker-thread behavior.
- Run `pytest` before opening a pull request.
- When changing repository knowledge, edit `AGENTS.md`, run
  `python scripts/sync_agent_docs.py --write`, then run
  `python scripts/sync_agent_docs.py --check` and
  `pytest tests/test_agent_docs_sync.py`.

## Commit and Pull Request Guidelines
- Write imperative, present-tense commit subjects near 60 characters.
- Keep unrelated edits out of the same commit.
- Ensure each commit passes relevant tests.
- Pull requests should summarize behavior changes, include test evidence, and link related issues.
- Include terminal captures only for user-facing UX changes.

## Git Safety Rules
- NEVER use `git checkout <file>` or restore files without explicit approval.

## Security and Configuration Tips
- Store provider keys in keyring or environment variables; never commit secrets.
- This is a public repository. Before pushing, scan the entire unpushed commit range (not only the final worktree) for real API keys, `.env` content, private keys, tailnet FQDNs, account emails, cloud project/instance IDs, private IPs, personal VM logins, and vocabulary/history/Anki data.
- Keep deployment identity in root-owned VM environment files or untracked local shell configuration. Tracked documentation and launcher defaults should use generic machine names and placeholders wherever practical.
- Public service topology and filesystem paths are not authentication. Preserve the actual boundary: localhost binding, Tailscale Serve identity, tailnet policy, and server-only credentials.
- Avoid checking in generated LaTeX, PDF, or Anki artifacts.
- Extend `.gitignore` when adding new generated outputs.
