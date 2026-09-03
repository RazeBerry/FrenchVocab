"""Design invariants of the mobile shell that nothing else can catch.

The static assets have no runtime coverage, so every defect these pin shipped
invisibly and stayed shipped: a focus ring boxing the headword, a paste leaving
the capture field stuck at a stale height, an index that threw the page half a
screen, a disabled primary button whose label sat at 2:1 against its own fill.
Each assertion below names the behavior it protects rather than the syntax it
matches, so a deliberate redesign can restate it and an accident cannot.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from xml.etree import ElementTree

import pytest

STATIC = Path(__file__).resolve().parents[1] / "vocab_builder" / "mobile" / "static"


@pytest.fixture(scope="module")
def styles() -> str:
    return (STATIC / "styles.css").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def capture_view() -> str:
    return (STATIC / "capture-view.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def entry_list() -> str:
    return (STATIC / "entry-list.js").read_text(encoding="utf-8")


def test_focus_ring_excludes_the_headword(styles):
    """A text field always matches :focus-visible, so an unscoped rule would
    box the capture headword on every tap, inside the slip's own outline."""
    assert "textarea:not(.hw):focus-visible" in styles
    assert not re.search(r"^\s*textarea:focus-visible", styles, re.MULTILINE)
    assert ".slip.is-capturing:focus-within" in styles


def test_disabled_primary_button_does_not_fade_label_and_fill_together(styles):
    """opacity composites both, collapsing their mutual contrast to ~2:1 — and
    this is the state the app opens in on every launch."""
    rule = _rule(styles, ".solid-button:disabled")
    assert "opacity" not in rule
    assert "background:" in rule and "color:" in rule


def test_headword_remeasures_after_its_size_step_lands(capture_view):
    """scrollHeight read during the font-size transition belongs to the previous
    step. Typing re-measures on the next keystroke; a paste never would."""
    assert 'event.propertyName === "font-size"' in capture_view
    assert "autoGrow" in capture_view


def test_the_whole_blank_slip_focuses_the_field(capture_view):
    """The textarea's own line box is a 39px target inside a much taller card."""
    assert "this.slip.addEventListener" in capture_view
    assert "this.input.focus()" in capture_view


def test_duplicate_content_leaves_the_blank_capture_styling(capture_view):
    """Stored definitions are content, not placeholder copy, so the duplicate
    landing state must use the filled slip before rendering the stored entry."""
    collected = capture_view.split("showCollected(existingEntry, lookupText", 1)[1].split(
        "showMergePreview(preview)", 1
    )[0]
    renderer = capture_view.split("renderEntry(entry, displayWord)", 1)[1].split(
        "setRibbon(label, note)", 1
    )[0]
    assert "this.renderEntry(existingEntry, existingEntry.word)" in collected
    assert 'this.slip.classList.remove("is-capturing"' in renderer


def test_index_opens_without_scrollintoview(entry_list):
    """scrollIntoView aligned the whole panel and moved the page ~500px, which
    contradicts the in-place contract and hid the tapped word."""
    assert ".scrollIntoView(" not in entry_list
    assert "window.scrollBy" in entry_list


def test_sticky_divider_paints_the_same_ground_as_the_page(styles):
    """--bg is the gradient's lower stop; a chip pinned at top: 0 sits against
    its upper one, so a flat token leaves a visible band. The letter chip and
    the ledger's day heading are one object, so one rule carries both."""
    assert "--page:" in styles
    divider = _rule(styles, ".index-divider")
    assert "position: sticky" in divider
    assert "var(--page)" in divider
    assert "background-attachment: fixed" in divider


def test_unknown_is_not_rendered_as_a_part_of_speech(entry_list):
    """"Unknown" is the parser's placeholder, and it reached the index as an
    "UNKN." badge on real entries."""
    assert "function knownType" in entry_list
    assert '"unknown"' in entry_list


def test_every_tappable_control_declares_at_least_the_tap_floor(styles):
    """Three controls survived the pass that was supposed to raise them all."""
    assert "--tap: 44px" in styles
    assert "--tap-lg: 48px" in styles
    for selector in (".danger-link", ".backup-drawer summary", ".install-tip button"):
        assert "var(--tap" in _rule(styles, selector), selector


def test_no_stray_pixel_sizes_remain_on_tap_targets(styles):
    """The scale exists so a value is a choice; 44px spelled two ways is drift."""
    body = styles.split("--tap-lg: 48px;", 1)[1]
    strays = re.findall(r"min-height:\s*(4[2-9]|5[01])px", body)
    assert strays == []


@pytest.fixture(scope="module")
def shell_js() -> str:
    return (STATIC / "ui.js").read_text(encoding="utf-8")


def test_capture_actions_stay_reachable_when_the_keyboard_opens(styles, shell_js):
    """iOS shrinks only the visual viewport, so every vh/dvh length keeps
    measuring the whole screen. `.stage` went on reserving 54vh — 460px of an
    iPhone 14 Pro's 852px — while only 516px stayed visible, leaving "Look it
    up" about 57px below the fold. visualViewport is the only thing that reports
    the real inset; Safari ignores the `interactive-widget` viewport key."""
    assert "window.visualViewport" in shell_js
    assert '"--kb"' in shell_js and "is-keyboard" in shell_js
    assert "min-height: 0" in _rule(styles, ":root.is-keyboard .stage")
    assert "none" in _rule(styles, ":root.is-keyboard .recent-strip")


def test_desktop_zoom_is_not_mistaken_for_a_software_keyboard(shell_js):
    """Pinch/page zoom can shrink the visual viewport by more than the keyboard
    threshold on a desktop. Keyboard layout is valid only with touch capability
    and an editable element focused."""
    assert "navigator.maxTouchPoints > 0" in shell_js
    assert "document.activeElement" in shell_js
    assert "input, textarea, [contenteditable='true']" in shell_js


def test_duplicate_markings_use_only_colour_and_type_scale_tokens(styles):
    """Duplicate affordances share the collection palette and type scale instead
    of introducing a light-only literal or a nearly-identical font size."""
    selectors = (
        ".ribbon",
        ".ribbon-note",
        ".senses li.is-held",
        ".senses li.is-new",
        ".tag",
        ".senses li.is-new .tag",
        ".tertiary",
    )
    feature_rules = "\n".join(_rule(styles, selector) for selector in selectors)
    assert not re.search(r"#[0-9a-fA-F]{3,8}|(?:rgb|hsl)a?\(", feature_rules)
    font_sizes = re.findall(r"font-size:\s*([^;]+)", feature_rules)
    assert font_sizes
    assert all(value.strip().startswith("var(--t-") for value in font_sizes)


def test_dark_theme_only_redefines_tokens(styles):
    """A colour whose only definition sits inside the dark rule never applies in
    light mode, so the page renders one theme's text on the other theme's ground.
    The dark block redefines the palette and declares nothing else — pinning that
    rule catches the mistake, where pinning today's hex values would only catch
    the next deliberate retune."""
    dark = styles.split(':root[data-theme="dark"] {', 1)[1].split("\n}", 1)[0]
    properties = [
        line.split(":", 1)[0].strip()
        for line in dark.splitlines()
        if ":" in line and not line.strip().startswith(("/*", "*"))
    ]
    assert properties, "the dark theme block was not found"
    assert [name for name in properties if not name.startswith("--")] == [
        "color-scheme"
    ]


@pytest.fixture(scope="module")
def index_html() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((STATIC / "manifest.webmanifest").read_text(encoding="utf-8"))


def test_icon_is_well_formed_xml():
    """A double hyphen inside an XML comment makes the file unparseable, and a
    browser renders the whole icon as a broken image rather than warning."""
    ElementTree.parse(STATIC / "icon.svg")


def test_icon_uses_only_colours_the_stylesheet_defines(styles):
    """The icon it replaced shared none of its five colours with the app."""
    icon = (STATIC / "icon.svg").read_text(encoding="utf-8")
    palette = {value.lower() for value in re.findall(r"#[0-9a-fA-F]{6}", icon)}
    assert palette, "icon declares no colours"
    known = {value.lower() for value in re.findall(r"#[0-9a-fA-F]{6}", styles)}
    assert palette <= known, f"off-palette colours in icon.svg: {sorted(palette - known)}"


def test_home_screen_icon_is_a_raster(index_html):
    """Safari accepts only PNG for apple-touch-icon; given an SVG it silently
    falls back to a screenshot of the page."""
    match = re.search(r'rel="apple-touch-icon"\s+href="([^"]+)"', index_html)
    assert match, "no apple-touch-icon declared"
    assert match.group(1).endswith(".png")


def test_every_declared_icon_exists(index_html, manifest):
    referenced = set(re.findall(r'href="(/static/icon[^"]*)"', index_html))
    referenced |= {icon["src"] for icon in manifest["icons"]}
    for src in referenced:
        assert (STATIC / src.removeprefix("/static/")).exists(), src


def test_manifest_ground_matches_the_app_ground(styles, manifest):
    """The splash colour and the first painted frame have to be one value."""
    background = re.search(r"^\s*--bg:\s*(#[0-9a-fA-F]{6});", styles, re.MULTILINE).group(1)
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    runtime = re.search(r'light:\s*"(#[0-9a-fA-F]{6})"', app).group(1)
    assert manifest["background_color"].lower() == background.lower()
    assert manifest["theme_color"].lower() == background.lower()
    assert runtime.lower() == background.lower()


def test_maskable_icon_is_declared_separately(manifest):
    """One icon marked "any maskable" lets a launcher circle-mask art that was
    never drawn with a safe zone."""
    purposes = [icon.get("purpose") for icon in manifest["icons"]]
    assert "maskable" in purposes
    assert not any(p and len(p.split()) > 1 for p in purposes)


def test_precached_shell_files_all_exist():
    """cache.addAll rejects wholesale on a single 404, taking offline with it."""
    worker = (STATIC / "service-worker.js").read_text(encoding="utf-8")
    for path in re.findall(r'"(/static/[^"]+)"', worker):
        assert (STATIC / path.removeprefix("/static/")).exists(), path


def test_wide_rows_stop_reading_as_a_ragged_line(styles):
    """One line per word is right on a 390px phone and wrong at the desktop
    frame: a right-aligned nowrap gloss makes the eye jump a different distance
    on every row, and clipping loses the ending of a quarter of French glosses.
    Wide, the row is a table with a fixed headword column."""
    wide = _media(styles, "(min-width: 560px)")
    # The badge track is fixed and the badge right-aligned inside it: an `auto`
    # track sized itself to the row's own badge, so a wide one ("v. pron.")
    # pushed that row's gloss about 30px past the shared left edge.
    assert "grid-template-columns: minmax(0, 15ch) 3.5rem minmax(0, 1fr)" in wide
    assert "text-align: right" in _rule(wide, ".index-type")
    assert "display: grid" in wide
    gloss = _rule(wide, ".index-gloss")
    assert "-webkit-line-clamp: 2" in gloss and "line-clamp: 2" in gloss
    assert "white-space: normal" in gloss
    assert "text-align: left" in gloss
    # An entry with no part of speech renders no badge, so auto placement would
    # slide its gloss into the badge's column.
    assert "grid-column: 3" in gloss
    # Narrow stays exactly as it shipped.
    narrow = _rule(styles, ".index-gloss")
    assert "white-space: nowrap" in narrow and "text-align: right" in narrow


def test_the_open_row_still_fades_its_gloss_in_either_layout(styles):
    """The gloss fades rather than un-displaying so opening a word never nudges
    the layout sideways; the grid must not have replaced that with a hidden
    element or moved the rule inside one layout."""
    assert '.index-row[aria-expanded="true"] .index-gloss { opacity: 0; }' in styles
    assert "opacity" not in _media(styles, "(min-width: 560px)")


def test_group_headings_are_real_elements_and_carry_their_count(entry_list, styles):
    """A screen reader does not reliably announce CSS `content:`, and a group
    whose size is invisible is just a divider. The day heading over the ledger
    and the letter heading over the collection are one object, so one builder
    makes both and the letter names itself for the rail to jump to."""
    assert "function divider(kind, label, count)" in entry_list
    assert 'element("p", `index-divider ${kind}`, label)' in entry_list
    assert '"index-count"' in entry_list
    assert 'divider("index-day"' in entry_list and 'divider("index-letter"' in entry_list
    assert "heading.dataset.letter = label" in entry_list
    dividers = (
        _rule(styles, ".index-divider")
        + _rule(styles, ".index-day")
        + _rule(styles, ".index-letter")
    )
    assert not re.search(r"(?:^|[;{])\s*content\s*:", dividers)


def test_history_order_never_prints_alphabetical_dividers(entry_list, capture_view):
    """Letter dividers over a history-ordered list would contradict the order.
    The two groupings are separate options and the day path returns first."""
    renderer = entry_list.split("export function renderEntries", 1)[1].split(
        "\nfunction appendRow", 1
    )[0]
    assert '} else if (options.grouped) {' in renderer
    assert 'groupBy: "day"' in capture_view
    assert "grouped" not in capture_view


def test_the_ledger_shows_all_of_today_before_it_fills(capture_view):
    """Eight rows was arbitrary: a heavy study day silently dropped this
    morning's words off the end of the strip."""
    assert "RECENT_LIMIT = 30" in capture_view
    assert "RECENT_ROWS = 8" in capture_view
    assert "/api/recent?limit=${RECENT_LIMIT}" in capture_view
    assert "Math.max(fromToday, RECENT_ROWS)" in capture_view


def test_merge_mark_reports_the_counts_the_save_recorded(entry_list):
    """A merge that added two senses looked exactly like a new word. The counts
    are the ones the write recorded — recomputing them from the rendered entry
    would let the ledger disagree with what landed on disk."""
    mark = entry_list.split("function mergeMark", 1)[1].split("\nfunction ", 1)[0]
    assert 'entry.action !== "merge"' in mark
    assert "entry.added?.definitions" in mark and "entry.added?.examples" in mark
    assert ".definitions.length" not in mark and ".examples.length" not in mark
    clause = entry_list.split("function addedClause", 1)[1].split("\nfunction ", 1)[0]
    # Omitted at zero, inflected at 1 and n.
    assert "if (value <= 0) return \"\";" in clause
    assert 'value === 1 ? "" : "s"' in clause


def test_just_saved_row_borrows_the_open_row_treatment(styles, capture_view):
    """The saved word arrived with no cue beyond the message line. The mark is
    the open row's own hue rule and wash, so it introduces no new colour, and it
    is matched by the word the receipt names rather than by position."""
    rule = _rule(styles, ".index-row.is-just-saved")
    assert "var(--hue)" in rule and "var(--hue-wash)" in rule
    assert not re.search(r"#[0-9a-fA-F]{3,8}|(?:rgb|hsl)a?\(", rule)
    motion = _media(styles, "(prefers-reduced-motion: no-preference)")
    assert ".index-row.is-just-saved" in motion and "animation:" in motion
    assert "var(--dur" in motion and "var(--ease)" in motion
    assert "animation" not in rule
    assert "this.justSaved = saved.word" in capture_view
    assert "justSaved: this.justSaved" in capture_view
    # Cleared by the next look-up, and by the reset a language change runs.
    look_up = capture_view.split("async lookUp(", 1)[1].split("async save(", 1)[0]
    reset = capture_view.split("  reset() {", 1)[1].split("\n  }", 1)[0]
    assert 'this.justSaved = "";' in look_up
    assert 'this.justSaved = "";' in reset


def test_the_ledger_links_to_the_whole_collection(index_html, capture_view):
    """Eight rows were the only navigable collection: the way in to the library
    shipped `hidden`."""
    links = re.findall(r"<button[^>]*data-go=\"library\"[^>]*>", index_html)
    assert links, "the onward link is gone"
    assert all("hidden" not in link for link in links)
    assert any('id="library-link"' in link for link in links)
    assert 'total === 1 ? "word" : "words"' in capture_view


def test_the_ledger_rules_add_no_second_spelling_of_a_scale_value(styles):
    """44px beside var(--tap) is the drift this stylesheet was cleaned of, and
    a hardcoded colour is invisible in one theme."""
    rules = "\n".join(
        _rule(styles, selector)
        for selector in (
            ".index-divider",
            ".index-day",
            ".index-count",
            ".index-mark",
            ".index-row.is-just-saved",
        )
    )
    rules += _media(styles, "(min-width: 560px)")
    rules += _media(styles, "(prefers-reduced-motion: no-preference)")
    assert not re.search(r"#[0-9a-fA-F]{3,8}|(?:rgb|hsl)a?\(", rules)
    font_sizes = re.findall(r"font-size:\s*([^;]+)", rules)
    assert font_sizes
    assert all(value.strip().startswith("var(--t-") for value in font_sizes)
    assert not re.search(r"min-height:\s*\d", rules)
    assert not re.search(r"\b\d+ms\b", rules)


@pytest.fixture(scope="module")
def library_view() -> str:
    return (STATIC / "library-view.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def app_js() -> str:
    return (STATIC / "app.js").read_text(encoding="utf-8")


def test_letter_dividers_use_the_key_the_server_sorted_by(entry_list):
    """The divider has to agree with the order the rows arrive in. A bare NFD
    pass files "Œuvre" under "#" while the server's key expands the ligature and
    sorts it among the O's, so that divider printed in the middle of the O block
    and the rail offered an O the list never reached. The browser mirrors the
    expansions `normalize_word_key` applies, and this fails if that table moves
    without the mirror."""
    from vocab_builder.models import _SPECIAL_REPLACEMENTS

    for original, replacement in _SPECIAL_REPLACEMENTS:
        assert f'["{original}", "{replacement}"]' in entry_list, original
    assert "normalize_word_key" in entry_list


def test_the_glossary_asks_for_the_index_once_and_the_entry_on_open(
    library_view,
    entry_list,
    index_html,
):
    """A letter rail has to know where every letter begins, which a page cannot
    say, so browse is one slim request and "Load more" is gone. The record a row
    omits is fetched when the row opens — building 573 detail panels for the one
    that gets opened is the cost that made the slim index worth having."""
    assert "/api/library/index?sort=${this.sort}" in library_view
    assert "/api/library/search?${params}" in library_view
    assert "/api/library/entry?word=" in library_view
    assert 'scope: "library-entry"' in library_view
    assert "Opening…" in library_view
    assert 'id="library-more"' not in index_html and "Load more" not in index_html
    assert "options.loadDetail" in entry_list
    # The row shows what the slim index carries, or the definitions a history
    # record and a search hit bring with them.
    assert "entry.gloss ?? entry.definitions?.[0]" in entry_list
    reset = library_view.split("  reset() {", 1)[1].split("\n  }", 1)[0]
    assert "this.entries.clear()" in reset


def test_glossary_input_paths_do_work_proportional_to_the_change(
    library_view,
    entry_list,
):
    """A key moves one cursor and a render publishes one completed fragment.

    Walking every row twice per arrow press and appending hundreds of live DOM
    nodes made input cost scale with collection size instead of the change.
    """
    cursor = library_view.split("  setCursor(next) {", 1)[1].split("\n  }", 1)[0]
    assert "this.rows.forEach" not in cursor
    assert "this.rows[this.cursor]" in cursor
    assert "this.rows[next]" in cursor
    focus = library_view.split('addEventListener("focusin"', 1)[1].split("});", 1)[0]
    assert "event.target === this.rows[this.cursor]" in focus

    renderer = entry_list.split("export function renderEntries", 1)[1].split(
        "\nfunction appendRow", 1
    )[0]
    assert "document.createDocumentFragment()" in renderer
    assert "container.replaceChildren(fragment)" in renderer
    assert "return rows" in renderer
    render = library_view.split("  render() {", 1)[1].split("\n  }", 1)[0]
    assert 'this.rows = renderEntries(el("entry-list")' in render
    assert "querySelectorAll" not in render
    abbreviation = entry_list.split("function abbreviateType", 1)[1].split(
        "\n}", 1
    )[0]
    assert "TYPE_ABBREVIATIONS.find" in abbreviation
    assert "const pairs" not in abbreviation


def test_search_clear_is_immediate_and_remote_results_stay_slim(library_view):
    """Clearing search is local and must not wait out the network debounce.
    Remote hits are finder rows; opening one follows the existing detail path.
    """
    search = library_view.split('el("search-input").addEventListener', 1)[1].split(
        'el("stats-button")', 1
    )[0]
    empty = search.split("if (!this.query)", 1)[1].split("return;", 1)[0]
    assert "this.render()" in empty
    assert "setTimeout" not in empty
    run_search = library_view.split("  async runSearch() {", 1)[1].split("\n  }", 1)[0]
    assert "/api/library/search?${params}" in run_search
    assert "this.entries.set" not in run_search
    assert "SEARCH_DEBOUNCE = 120" in library_view


def test_acquisition_order_prints_no_dividers(library_view):
    """Letter dividers over the order words were acquired in would contradict
    it, and an index row carries no timestamp to build day headings from, so
    "Added" prints no dividers rather than inventing them."""
    render = library_view.split("  render() {", 1)[1].split("\n  }", 1)[0]
    assert 'grouped: !searching && this.sort === "alpha"' in render


def test_the_letter_rail_is_offered_only_where_it_is_true(
    library_view,
    styles,
    index_html,
):
    """The rail's census counts the whole collection and its jumps land on
    dividers, so it is shown exactly when the rows on screen are the whole
    collection in alphabetical order. A letter with no words is not a
    destination, said in colour and weight: fading a letter fades its own
    label."""
    rail = library_view.split("railApplies() {", 1)[1].split("\n  }", 1)[0]
    assert 'this.sort === "alpha"' in rail
    assert "!this.query" in rail and "!this.wordType" in rail
    assert '<nav class="rail" id="letter-rail" aria-label="Jump to a letter"' in index_html
    assert 'setAttribute("aria-disabled"' in library_view
    empty = _rule(styles, '.rail-letter[aria-disabled="true"]')
    assert "opacity" not in empty
    assert "var(--dim)" in empty
    assert "var(--ink-soft)" in _rule(styles, ".rail-letter")


def test_dragging_the_rail_scrubs_with_an_indicator_in_the_display_face(
    library_view,
    styles,
):
    """A drag has to move the list continuously, and the letter under the finger
    has to be legible while the finger covers the rail."""
    assert "pointerdown" in library_view and "pointermove" in library_view
    assert "setPointerCapture" in library_view
    assert "touch-action: none" in _rule(styles, ".rail")
    bubble = _rule(styles, ".rail-bubble")
    assert "var(--display)" in bubble
    assert "var(--hue)" in bubble and "var(--on-hue)" in bubble


def test_the_rail_fits_the_shortest_supported_viewport(styles):
    """Twenty-seven letters at the 44px tap floor would be 1,188px of screen, so
    the rail as a whole is the drag target and the letters inside it are marks.
    They still have to fit above the tab bar on a 667px phone."""
    letter = _rule(styles, ".rail-letter")
    height = int(re.search(r"height:\s*(\d+)px", letter).group(1))
    assert height * 27 <= 667 - 62


def test_the_glossary_answers_the_keyboard_without_moving_focus_off_the_list(
    library_view,
):
    """The desktop frame is a real surface and the CLI is arrow-driven. One tab
    stop reaches the list and the arrows move inside it, so Tab never has to
    walk 573 rows to reach the footer."""
    assert 'event.key === "/"' in library_view
    assert 'event.key === "ArrowDown"' in library_view
    assert 'event.key === "Escape"' in library_view
    assert "/^[a-z]$/i" in library_view
    assert "row.tabIndex = at === 0 ? 0 : -1" in library_view
    cursor = library_view.split("  setCursor(next) {", 1)[1].split("\n  }", 1)[0]
    assert "previous.tabIndex = -1" in cursor
    assert "current.tabIndex = 0" in cursor
    assert "this.rows.forEach" not in cursor
    # Escape closes the open row first and only then clears the query.
    escape = library_view.split("  escape(search) {", 1)[1].split("\n  }", 1)[0]
    assert escape.index("open.click()") < escape.index('this.query = ""')


def test_search_marks_the_matching_fragment_as_a_real_element(entry_list, styles):
    """CSS `content:` is not reliably announced, and nothing else in the row can
    say which words the search matched."""
    gloss = entry_list.split("function glossNode", 1)[1].split("\nfunction ", 1)[0]
    assert 'element("mark"' in gloss
    rule = _rule(styles, ".index-gloss mark")
    assert "var(--hue-wash)" in rule and "var(--ink)" in rule
    assert "content:" not in rule


def test_the_glossary_hands_a_word_to_capture_instead_of_owning_the_rule(
    library_view,
    app_js,
):
    """Looking a held word up again is capture's collected state, reached from
    the glossary by handing the entry over. Practice and Anki selection are
    deferred with the views they would hand off to."""
    assert "Look up more senses" in library_view
    assert "this.onLookUp(entry)" in library_view
    for endpoint in ("/api/preview", "/api/save", "/api/anki", "/api/practice"):
        assert endpoint not in library_view, endpoint
    assert "views.capture.showCollected(entry)" in app_js
    assert 'showView("capture")' in app_js


def test_stats_and_random_flashcard_own_separate_disclosures(index_html, library_view):
    """A random card must not overwrite the statistics it shares a row with.
    Each action owns one panel, while one coordinator closes the other panel and
    keeps the controls' accessible expanded state truthful."""
    assert 'id="random-button" type="button" aria-controls="random-panel"' in index_html
    assert 'id="stats-button" type="button" aria-controls="stats-panel"' in index_html
    assert 'id="stats-panel" hidden' in index_html
    assert 'id="random-panel" hidden' in index_html

    load_stats = library_view.split("  async loadStats() {", 1)[1].split("\n  }", 1)[0]
    show_random = library_view.split("  async showRandom() {", 1)[1].split("\n  }", 1)[0]
    assert 'el("stats-panel")' in load_stats
    assert 'el("random-panel")' not in load_stats
    assert 'el("random-panel")' in show_random
    assert 'el("stats-panel")' not in show_random
    assert 'this.setAuxiliaryPanel("random-panel")' in show_random

    coordinator = library_view.split("  setAuxiliaryPanel(", 1)[1].split("\n  }", 1)[0]
    assert '["random-button", "random-panel"]' in coordinator
    assert '["stats-button", "stats-panel"]' in coordinator
    assert 'setAttribute("aria-expanded", String(expanded))' in coordinator
    assert "panel.classList" not in library_view


def test_the_header_count_is_a_way_into_the_glossary(index_html, styles):
    """It is the one place the whole collection is named on every screen."""
    match = re.search(r'<button class="count"[^>]*>', index_html)
    assert match, "the header count is not a control"
    assert 'data-go="library"' in match.group(0)
    assert "var(--tap)" in _rule(styles, ".count")


def test_english_keeps_two_tabs_rather_than_one(styles):
    """English is monolingual, so capability data removes the translator. The
    glossary keeps the collection one tap away instead of leaving a single
    tab."""
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in _rule(styles, ".tabbar")
    monolingual = _rule(styles, ':root[data-translation="false"] .tabbar')
    assert "repeat(2, minmax(0, 1fr))" in monolingual


def test_the_glossary_foot_inflects_and_names_the_instrument_at_hand(library_view):
    """At a desktop width the keyboard is the faster instrument; on a phone the
    rail is, and it is only named where it exists."""
    foot = library_view.split("renderFoot(shown, searching) {", 1)[1].split("\n  }", 1)[0]
    assert "tap a row, or drag the rail" in foot
    assert "tap a row, or press / to search" in foot
    assert 'count(this.total, "word", "words")' in foot
    assert 'count(letters, "letter", "letters")' in foot
    counter = library_view.split("function count(", 1)[1].split("\n}", 1)[0]
    assert "value === 1 ? singular : plural" in counter


def test_the_glossary_rules_add_no_second_spelling_of_a_scale_value(styles):
    """44px beside var(--tap) is the drift this stylesheet was cleaned of, and a
    hardcoded colour is invisible in one theme."""
    rules = "\n".join(
        _rule(styles, selector)
        for selector in (
            ".rail",
            ".rail-letter",
            '.rail-letter[aria-disabled="true"]',
            ".rail-letter.is-current",
            ".rail-bubble",
            ".index-gloss mark",
            ".index-row.is-cursor",
            ".index-loading",
            ".index-letter",
            ".index-controls",
            ".entry-actions .ghost-button",
            ".count",
        )
    )
    assert not re.search(r"#[0-9a-fA-F]{3,8}|(?:rgb|hsl)a?\(", rules)
    font_sizes = re.findall(r"font-size:\s*([^;]+)", rules)
    assert font_sizes
    assert all(value.strip().startswith("var(--t-") for value in font_sizes)
    assert not re.search(r"min-height:\s*\d", rules)
    assert not re.search(r"\b\d+ms\b", rules)


def _media(styles: str, query: str) -> str:
    """The block of an @media rule, braces balanced so nested rules survive."""
    start = styles.find(f"@media {query}")
    assert start >= 0, f"no @media {query}"
    depth = 0
    for index in range(start, len(styles)):
        if styles[index] == "{":
            depth += 1
        elif styles[index] == "}":
            depth -= 1
            if depth == 0:
                return styles[start:index]
    raise AssertionError(f"unclosed @media {query}")


def _rule(styles: str, selector: str) -> str:
    match = re.search(
        rf"(^|\n)\s*{re.escape(selector)}\s*(,[^{{]*)?\{{(?P<body>[^}}]*)\}}",
        styles,
    )
    assert match, f"no rule found for {selector}"
    return match.group("body")
