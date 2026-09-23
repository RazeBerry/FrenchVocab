"""Drive the phone's capture and glossary views under Node.

The real modules run against the small browser stand-in in
``tests/js/fake_dom.mjs``, so each assertion is about what the view does, not
about how its source is spelled.
"""

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "vocab_builder" / "mobile" / "static"
FAKE_DOM = ROOT / "tests" / "js" / "fake_dom.mjs"


def _run(body: str) -> dict:
    node = shutil.which("node")
    assert node, "Node is required to exercise the browser modules"
    script = (
        f'const {{ nodes, store }} = await import({json.dumps(FAKE_DOM.as_uri())});\n'
        f'const STATIC = {json.dumps(STATIC.as_uri())};\n'
        "const out = {};\n"
        f"{body}\n"
        "console.log(JSON.stringify(out));\n"
        # Pending requests hold 30 s abort timers; the answer is already out.
        "process.exit(0);\n"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


CAPTURE = """
const { CaptureView } = await import(`${STATIC}/capture-view.js`);
const FRENCH = { language: "fr", language_name: "French", entry_count: 3, provider: "Test provider" };
"""


def test_french_capture_draft_comes_back_after_a_reload():
    out = _run(CAPTURE + """
store["vocabbuilder-capture-draft-fr"] = "néanmoins";
const view = new CaptureView({ request: async () => [] }, async () => {}, async () => {});
view.setLanguage(FRENCH);
out.value = nodes["entry-input"].value;
""")

    assert out["value"] == "néanmoins"


def test_look_up_fills_the_slip_locks_the_field_and_cancel_returns_the_word():
    out = _run(CAPTURE + """
let pending = null;
const aborted = [];
const api = {
  request: (path) => path.startsWith("/api/recent")
    ? Promise.resolve([])
    : new Promise((resolve, reject) => { pending = { resolve, reject }; }),
  abort(scope) {
    aborted.push(scope);
    pending.reject(Object.assign(new Error("Request superseded."), { code: "request_aborted" }));
  },
};
const view = new CaptureView(api, async () => {}, async () => {});
view.setLanguage(FRENCH);
nodes["entry-input"].value = "flâner";
nodes["entry-input"].fire("input");
const lookUp = view.lookUp();
out.during = {
  mode: view.mode,
  fieldHidden: nodes["entry-input"].hidden,
  word: nodes["preview-word"].textContent,
  waiting: !nodes["slip-wait"].hidden,
  provider: nodes["wait-provider"].textContent,
  seconds: nodes["wait-seconds"].textContent,
  cancel: nodes["discard-button"].textContent,
  cancelEnabled: !nodes["discard-button"].disabled,
  primaryDisabled: nodes["primary-button"].disabled,
  label: nodes["primary-label"].textContent,
};
nodes["discard-button"].click();
await lookUp;
out.after = {
  aborted,
  mode: view.mode,
  fieldHidden: nodes["entry-input"].hidden,
  value: nodes["entry-input"].value,
  waiting: !nodes["slip-wait"].hidden,
  label: nodes["primary-label"].textContent,
  primaryDisabled: nodes["primary-button"].disabled,
};
""")

    assert out["during"] == {
        "mode": "looking",
        "fieldHidden": True,
        "word": "flâner",
        "waiting": True,
        "provider": "Test provider",
        "seconds": "0 s",
        "cancel": "Cancel",
        "cancelEnabled": True,
        "primaryDisabled": True,
        "label": "Looking it up…",
    }
    assert out["after"] == {
        "aborted": ["capture-ai"],
        "mode": "capture",
        "fieldHidden": False,
        "value": "flâner",
        "waiting": False,
        "label": "Look it up",
        "primaryDisabled": False,
    }


def test_merge_button_and_receipt_count_senses_and_examples():
    out = _run(CAPTURE + """
const api = {
  request: async (path) => path === "/api/save"
    ? { action: "merged", word: "Amadouer", added_definitions: 2, added_examples: 1 }
    : [],
};
const view = new CaptureView(api, async () => {}, async () => {});
view.setLanguage(FRENCH);
view.showPreview({
  token: "t",
  word: "amadouer",
  duplicate_action: "merge",
  definitions: ["d", "e"],
  existing_entry: { word: "Amadouer", word_type: "verb", definitions: ["a", "b", "c"], examples: [] },
  new_definitions: ["d", "e"],
  new_examples: [{ source: "x", target: "y" }],
});
out.button = nodes["primary-label"].textContent;
out.ribbon = nodes["ribbon-note"].textContent;
await view.save();
out.receipt = nodes["form-message"].textContent;
""")

    assert out["button"] == "Add 2 senses, 1 example"
    assert out["ribbon"] == "+2 senses, +1 example"
    assert out["receipt"] == "Amadouer gained 2 senses and 1 example."


def test_a_failed_first_glossary_load_is_retried_not_remembered():
    out = _run("""
const { LibraryView } = await import(`${STATIC}/library-view.js`);
let online = false;
const api = {
  request: async (path) => {
    if (!online) throw Object.assign(new Error("Server unavailable"), { code: "network" });
    if (path.startsWith("/api/library/index")) {
      return {
        items: [
          { word: "Abeille", word_type: "noun", gloss: "Bee", letter: "A", added: 1 },
          { word: "Abîme", word_type: "noun", gloss: "Abyss", letter: "A", added: 0 },
        ],
        letters: { A: 2 },
        total: 2,
      };
    }
    return { types: [], total: 2, with_examples: 2, with_multiple_senses: 0 };
  },
};
const view = new LibraryView(api, async () => {});
await view.activate();
out.offline = { loaded: view.loaded, message: nodes["library-message"].textContent };
online = true;
await view.activate();
out.online = { loaded: view.loaded, placeholder: nodes["search-input"].placeholder };
""")

    assert out["offline"] == {"loaded": False, "message": "Server unavailable"}
    assert out["online"] == {"loaded": True, "placeholder": "Search 2 words"}


def test_switching_language_paints_the_known_collection_before_the_network_answers():
    """Over a relayed tailnet a round trip is 150-200 ms; a switch must not wait
    for it to name the collection it switched to."""
    out = _run("""
const payloads = {
  "/api/collections": { default_language: "fr", collections: [
    { language: "fr", language_name: "French" }, { language: "de", language_name: "German" }] },
  "/api/status?language=fr": { language: "fr", language_name: "French", entry_count: 573,
    data_file: "FrenchVocab.tex", supports_translation: true, provider: "p" },
  "/api/status?language=de": { language: "de", language_name: "German", entry_count: 458,
    data_file: "GermanVocab.tex", supports_translation: true, provider: "p" },
};
const seen = {};
globalThis.fetch = (url) => {
  const key = url.startsWith("/api/recent") ? "/api/recent" : url;
  seen[key] = (seen[key] || 0) + 1;
  // After the one background prefetch, German's status never answers.
  if (key === "/api/status?language=de" && seen[key] > 1) return new Promise(() => {});
  const body = key === "/api/recent" ? [] : payloads[key];
  return Promise.resolve({ ok: true, json: async () => body });
};
await import(`${STATIC}/app.js`);
for (let i = 0; i < 20; i++) await new Promise((resolve) => setTimeout(resolve, 0));
out.before = { count: nodes["entry-count"].textContent, file: nodes["data-file"].textContent };
nodes["languages"].children.find((button) => button.dataset.lang === "de").click();
for (let i = 0; i < 5; i++) await new Promise((resolve) => setTimeout(resolve, 0));
out.after = {
  count: nodes["entry-count"].textContent,
  file: nodes["data-file"].textContent,
  slip: nodes["slip-pos"].textContent,
  language: document.documentElement.dataset.language,
  germanStatusRequests: seen["/api/status?language=de"],
};
""")

    assert out["before"] == {"count": "573", "file": "FrenchVocab.tex"}
    assert out["after"] == {
        "count": "458",
        "file": "GermanVocab.tex",
        "slip": "German",
        "language": "de",
        "germanStatusRequests": 2,
    }


def test_returning_to_a_collection_shows_its_ledger_and_glossary_at_once():
    out = _run("""
const { CaptureView } = await import(`${STATIC}/capture-view.js`);
const { LibraryView } = await import(`${STATIC}/library-view.js`);
const index = { items: [{ word: "Abeille", word_type: "noun", gloss: "Bee", letter: "A", added: 1 }],
  letters: { A: 1 }, total: 1 };
const recent = [{ word: "Abeille", word_type: "noun", definitions: ["Bee"], examples: [],
  timestamp: new Date().toISOString(), action: "new" }];
let answer = true;
const api = {
  request: (path) => {
    if (!answer) return new Promise(() => {});
    if (path.startsWith("/api/recent")) return Promise.resolve(recent);
    if (path.startsWith("/api/library/index")) return Promise.resolve(index);
    return Promise.resolve({ types: [], total: 1, with_examples: 0, with_multiple_senses: 0 });
  },
  prefetch() {},
};
document.documentElement.dataset.language = "fr";
const capture = new CaptureView(api, async () => {}, async () => {});
const library = new LibraryView(api, async () => {});
await capture.refresh();
await library.activate();
// Away to German and back, with the network now silent.
answer = false;
for (const language of ["de", "fr"]) {
  document.documentElement.dataset.language = language;
  capture.reset();
  library.reset();
  capture.refresh();
  library.activate();
}
await Promise.resolve();
// The empty-state line is hidden exactly when the ledger has rows.
out.ledgerShown = nodes["recent-empty"].hidden;
out.placeholder = nodes["search-input"].placeholder;
out.loaded = library.loaded;
""")

    assert out == {"ledgerShown": True, "placeholder": "Search 1 word", "loaded": False}


def test_an_unchanged_fresh_index_is_not_rendered_a_second_time():
    out = _run("""
const { LibraryView } = await import(`${STATIC}/library-view.js`);
const index = { items: [{ word: "Abeille", word_type: "noun", gloss: "Bee", letter: "A", added: 1 }],
  letters: { A: 1 }, total: 1 };
const api = {
  request: async (path) => path.startsWith("/api/library/index")
    ? structuredClone(index)
    : { types: [], total: 1, with_examples: 0, with_multiple_senses: 0 },
};
document.documentElement.dataset.language = "fr";
const view = new LibraryView(api, async () => {});
await view.activate();
view.reset();
let renders = 0;
const render = view.render.bind(view);
view.render = () => { renders += 1; render(); };
await view.activate();
out.renders = renders;
index.items[0].gloss = "Honeybee";
await view.refreshIfLoaded();
out.afterChange = renders;
""")

    # One paint from memory; the identical fresh answer adds none, a changed one does.
    assert out == {"renders": 1, "afterChange": 2}


def test_returning_to_the_app_rereads_the_glossary_only_after_the_collection_changed():
    out = _run("""
let version = "v1";
const counts = {};
globalThis.fetch = (url) => {
  const key = url.split("?")[0];
  counts[key] = (counts[key] || 0) + 1;
  const bodies = {
    "/api/collections": { default_language: "fr", collections: [{ language: "fr", language_name: "French" }] },
    "/api/status": { language: "fr", language_name: "French", entry_count: 1, data_file: "F.tex",
      supports_translation: true, provider: "p", collection_version: version },
    "/api/library/index": { items: [], letters: {}, total: 0 },
    "/api/library/stats": { types: [], total: 0, with_examples: 0, with_multiple_senses: 0 },
  };
  return Promise.resolve({ ok: true, json: async () => bodies[key] ?? [] });
};
const tab = document.createElement("button");
tab.dataset.tab = "library";
document.querySelectorAll = (selector) => (selector === "[data-tab]" ? [tab] : []);
const handlers = {};
document.addEventListener = (type, handler) => { handlers[type] = handler; };
document.visibilityState = "visible";
const settle = async () => { for (let i = 0; i < 20; i++) await new Promise((r) => setTimeout(r, 0)); };
await import(`${STATIC}/app.js`);
await settle();
tab.click();
await settle();
out.opened = counts["/api/library/index"];
handlers.visibilitychange();
await settle();
out.unchanged = counts["/api/library/index"];
version = "v2";
handlers.visibilitychange();
await settle();
out.changed = counts["/api/library/index"];
""")

    assert out == {"opened": 1, "unchanged": 1, "changed": 2}


def test_on_the_glossary_a_switch_paints_known_rows_without_waiting_for_status():
    out = _run("""
let silent = false;
const counts = {};
const status = (language, name, count) => ({ language, language_name: name, entry_count: count,
  data_file: "x.tex", supports_translation: true, provider: "p", collection_version: "v" });
const index = (total) => ({ items: [], letters: {}, total });
globalThis.fetch = (url) => {
  const [path, query] = url.split("?");
  const language = new URLSearchParams(query).get("language");
  counts[path] = (counts[path] || 0) + 1;
  if (silent) return new Promise(() => {});
  const bodies = {
    "/api/collections": { default_language: "fr", collections: [
      { language: "fr", language_name: "French" }, { language: "de", language_name: "German" }] },
    "/api/status": language === "de" ? status("de", "German", 458) : status("fr", "French", 573),
    "/api/library/index": language === "de" ? index(458) : index(573),
    "/api/library/stats": { types: [], total: 0, with_examples: 0, with_multiple_senses: 0 },
  };
  return Promise.resolve({ ok: true, json: async () => bodies[path] ?? [] });
};
const tab = document.createElement("button");
tab.dataset.tab = "library";
document.querySelectorAll = (selector) => (selector === "[data-tab]" ? [tab] : []);
const settle = async () => { for (let i = 0; i < 20; i++) await new Promise((r) => setTimeout(r, 0)); };
await import(`${STATIC}/app.js`);
await settle();
tab.click();
await settle();
const button = (code) => nodes["languages"].children.find((item) => item.dataset.lang === code);
button("de").click();
await settle();
out.german = nodes["search-input"].placeholder;
silent = true;
const recentBefore = counts["/api/recent"];
button("fr").click();
for (let i = 0; i < 5; i++) await new Promise((resolve) => setTimeout(resolve, 0));
out.french = nodes["search-input"].placeholder;
out.count = nodes["entry-count"].textContent;
await settle();
out.recentRequests = counts["/api/recent"] - recentBefore;
""")

    assert out == {
        "german": "Search 458 words",
        "french": "Search 573 words",
        "count": "573",
        "recentRequests": 1,
    }


def test_a_quick_second_tap_supersedes_the_first_switch():
    out = _run("""
const status = (language, name, count) => ({ language, language_name: name, entry_count: count,
  data_file: "x.tex", supports_translation: true, provider: "p", collection_version: "v" });
globalThis.fetch = (url) => {
  const [path, query] = url.split("?");
  const language = new URLSearchParams(query).get("language");
  const bodies = {
    "/api/collections": { default_language: "en", collections: [
      { language: "en", language_name: "English" }, { language: "fr", language_name: "French" },
      { language: "de", language_name: "German" }] },
    "/api/status": { en: status("en", "English", 2), fr: status("fr", "French", 573),
      de: status("de", "German", 458) }[language || "en"],
  };
  return Promise.resolve({ ok: true, json: async () => bodies[path] ?? [] });
};
const settle = async () => { for (let i = 0; i < 20; i++) await new Promise((r) => setTimeout(r, 0)); };
await import(`${STATIC}/app.js`);
await settle();
const painted = [];
const count = nodes["entry-count"];
let text = count.textContent;
Object.defineProperty(count, "textContent", { get: () => text, set: (value) => { text = value; painted.push(value); } });
const button = (code) => nodes["languages"].children.find((item) => item.dataset.lang === code);
button("de").click();
button("fr").click();
await settle();
out.painted = painted;
""")

    assert "458" not in out["painted"]
    assert out["painted"][-1] == "573"
