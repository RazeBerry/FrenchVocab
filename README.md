# VocabForge 2.0

An AI-assisted CLI for building bilingual vocabulary libraries, exporting polished LaTeX, and generating Anki decks—now with per-language configuration and German support.

---

## Highlights
- **Multilingual engine** – switch languages with `--language` (French `fr` and German `de` out of the box). Each language ships with its own prompts, LaTeX scaffolding, translator labels, and Anki deck metadata.
- **Smart intake** – paste words, expressions, or full sentences; the app detects the type, streams Gemini (or Claude) responses, and formats consistent definitions and examples.
- **Bidirectional translators** – jump straight into English→Target or Target→English modes, capture multiline input without retyping, confirm results with localized labels, and save to dedicated `.tex` glossaries.
- **Structure-first output** – LaTeX entries stay alphabetized and brace-balanced; Anki export produces deterministic GUIDs and language-specific decks, with tracking files kept per language (`exported_words_<code>.json`).
- **Rich UX** – colorized menus, duplicate resolution (skip/view/merge/force), sentence routing, and searchable vocab tables make CLI work approachable.

---

## Quick Start
```bash
git clone https://github.com/RazeBerry/FrenchVocab.git
cd FrenchVocab
pip install -r requirements.txt

# first run – prompts for (and stores) provider API key if absent
python FrenchVocab.py [path/to/vocab.tex] \
    --language fr \
    --provider gemini \
    --verbose
```

Environment variables bypass the key prompt:
```bash
export GEMINI_API_KEY=your_key_here
# or
export ANTHROPIC_API_KEY=your_claude_key
```

---

## Everyday Tasks
- **Add vocab**  
  `python FrenchVocab.py --language de` → choose option `1`
- **Run translators**  
  Option `2`: English → target language  
  Option `3`: Target language → English
- **Export to Anki**  
  Option `4` → export pending entries to a language-specific `.apkg`
- **Search / review**  
  Option `5` shows a sortable table; duplicate warnings let you inspect, merge, or add variants.

All commands accept `--language` (defaults to French) and `--provider` (`gemini` or `claude`). Verbose mode surfaces timing and stream diagnostics.

---

## Project Layout
| Path | Purpose |
| --- | --- |
| `FrenchVocab.py` | Main CLI orchestrator, routing, and language-aware configuration |
| `languages/` | Config definitions (`french.py`, `german.py`) plus shared schemas (`base.py`) |
| `ai_prompts.py` | Prompt templates for vocab generation per language |
| `core/translator.py` | Shared translator workflow (config-injected labels/templates) |
| `latex_repository.py` | Brace-safe parsing of `\entry{}` structures |
| `anki_exporter.py` | Deterministic deck/model builder parameterized by language metadata |
| `tests/` | Pytest suite; `test_language_configs.py` ensures every registered language initializes cleanly |

---

## Advanced Usage
- **Custom language** – copy `languages/german.py`, adjust prompts, LaTeX templates, translator metadata, and register it in `languages/__init__.py`.
- **Sentence routing** – long inputs auto-route to the target→English translator; accept or decline on the fly.
- **Multiline paste** – translators echo captured text after every line; press Enter on a blank line to submit.
- **Separate tracking** – exported vocab lists are tracked in `exported_words_<language>.json`, avoiding cross-language collisions.

---

## Development
```bash
pip install -r requirements.txt
pytest -q
```

The repo avoids storing API keys or generated `.tex/.apkg` artifacts. Keys are kept via `keyring` (service name `french_vocab_builder`); environment variables take precedence over stored values.

---

## Roadmap
- Expand language configs (additional templates, grammar-aware validators)
- Add localized example tense rules per language
- Parameterize test fixtures for language-specific LaTeX exports

---

Machine-crafted vocabulary, human-readable output—now fluent in more than one language. Enjoy VocabForge 2.0!
