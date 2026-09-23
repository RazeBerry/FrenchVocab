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
out.online = { loaded: view.loaded };
""")

    assert out["offline"] == {"loaded": False, "message": "Server unavailable"}
    assert out["online"] == {"loaded": True}
