# Private mobile interface: server and product

Contract: invariants only. Routed from `docs/mobile_map.md`; dated evidence lives
in `reports/` and is linked from the rule it supports.

## Commands
```bash
# Private mobile/web interface (requires the [mobile] extra)
pip install -e ".[mobile]"
vocabbuilder-mobile --help
vocabbuilder-mobile --languages fr,de,en --default-language fr
vocabbuilder-mobile --languages fr,de,en --allowed-tailscale-user you@example.com
vocabbuilder-mobile --language fr --latex-file ./FrenchVocab.tex
```

## Server
- `cli.py` is the `vocabbuilder-mobile` entry point; it binds `127.0.0.1:8080` by default and never opens a public port.
- `app.py` is an HTTP composition root: it validates private identity, maps requests to one language service, translates domain errors to JSON, and serves the static shell. Keep workflows out of route handlers.
- `service.py` owns vocabulary capture and the durable transaction journal. `library.py`, `translations.py`, `practice.py`, `anki.py`, `settings.py`, and `storage.py` own the other phone workflows; do not grow another all-purpose mobile controller.
- `state_store.py` atomically persists short-lived previews, idempotent receipts, practice attempts, and repairable auxiliary transactions. The LaTeX collections remain authoritative; mobile state is a recovery journal, not another vocabulary database.
- `catalog.py` registers those per-language services and resolves the `?language=` parameter; `factory.py` constructs them.
- `MobileLibrary.index()` returns the whole collection as `{word, word_type,
  gloss, added}` finder rows plus a `letters` census, because a letter rail has
  to know where each letter begins and the paged endpoint cannot say. Slim rows
  keep French near 60 KB against several hundred for full entries; the detail a
  row omits is loaded from `/api/library/entry` when the row opens.
- A letter bucket is taken from the same normalized key that orders the index,
  never from a separate diacritic pass. The key expands ligatures, so `Œuvre`
  sorts among the O's; a bucket from bare NFD would have counted it under `#`
  and contradicted the order the rows arrive in.
- Acquisition order comes from `AnkiExportManager.acquisition_positions()`, so
  the glossary and the deck agree on what "newest" means. Do not re-derive an
  order from history in a read model. Each row carries its rank as `added`
  (`null` when the order has never seen the entry, which then follows the
  ordered words alphabetically) so the browser can switch A-Z and Added without
  another round trip across the VM link.
- `/api/library/index` takes no sort parameter. Rows arrive alphabetical and
  the browser reorders them from the rank each row carries, so a server-side
  `sort=added` was a mode only the tests ever sent; it was removed rather than
  kept warm.
- `/api/library/search` searches rich content but answers with the same finder
  rows the index ships. Search is an input hot path, and returning every
  matching definition and example moved the cold detail payload for up to 200
  entries in order to render a word, a type, and one gloss. That gloss is the
  definition that matched when one did, chosen in `search_index` because only
  the server knows which field matched; a match found only in the headword,
  the type, or an example keeps the first definition. The browser marks the
  typed fragment inside whichever gloss it is given.
- A word not in the collection is `EntryNotFoundError` (404, `entry_not_found`),
  not the `workflow_not_found` path: nothing expired, the word was never held.
- The mobile surface constructs every builder with `interactive=False`; no code reachable from a request may prompt. `UIHelper` raises `NonInteractiveError` as a backstop if a future request path accidentally attempts console input.
- Blocking provider and repository work is exposed through synchronous FastAPI handlers so Starlette runs it in worker threads; do not call those workflows directly from an `async def` route.
- Tailscale Serve supplies private HTTPS and identity; provider credentials stay server-side and are never sent to the browser.
- Run exactly one `vocabbuilder-mobile` process worker. The local terminal client uses that worker's API; filesystem locks still protect data-file writes from the legacy separately launched SSH CLI. The mobile request journal is an intentionally single-worker state machine.

## Product philosophy
- The phone and local Mac terminal client are two interfaces to the same application and
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
  a word already held, raises the ordinary duplicate with `corrected_from`, and
  the phone lands on the held entry saying it was corrected (the Mac client
  prints the same). It used to return a merge preview so the paid generation was
  not wasted, but a fresh generation rewords the held senses, so that preview
  offered "ronger" three paraphrases of its own senses as new. "Look up new
  senses" from there is a merge look-up for the held headword.
- Destructive vocabulary editing, deletion, and backup restoration are not CLI
  workflows and are intentionally absent from the phone; restoration is the
  operator script above. Recovery artifacts are
  allowlisted, read-only downloads. This is parity with the product's behavior,
  not unrestricted file-system parity.
- Privacy, connectivity, and installability should be legible but quiet:
  Tailscale remains the access boundary, secrets remain server-side, and the
  no-build shell remains usable as an iPhone home-screen app.
