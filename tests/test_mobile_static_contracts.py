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
    collected = capture_view.split("showCollected(existingEntry)", 1)[1].split(
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


def test_sticky_letter_paints_the_same_ground_as_the_page(styles):
    """--bg is the gradient's lower stop; a chip pinned at top: 0 sits against
    its upper one, so a flat token leaves a visible band."""
    assert "--page:" in styles
    letter = _rule(styles, ".index-letter")
    assert "var(--page)" in letter
    assert "background-attachment: fixed" in letter


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


def _rule(styles: str, selector: str) -> str:
    match = re.search(
        rf"(^|\n)\s*{re.escape(selector)}\s*(,[^{{]*)?\{{(?P<body>[^}}]*)\}}",
        styles,
    )
    assert match, f"no rule found for {selector}"
    return match.group("body")
