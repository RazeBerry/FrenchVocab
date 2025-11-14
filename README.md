# FrenchVocab

An AI-assisted command line companion for growing bilingual vocabulary lists, producing tidy LaTeX, and exporting Anki decks. The current release focuses on a smooth first-run experience so you can get productive within minutes.

---

## What You Get
- **Multi-language vocab builder** – swap languages with `--language` (French `fr` and German `de` included) and keep each glossary in its own LaTeX file.
- **Rich CLI UX** – colour panels, guided prompts, and smart duplicate detection make the terminal feel welcoming.
- **Bidirectional translators** – jump between English→Target and Target→English flows with sentence-aware routing.
- **Deterministic exports** – LaTeX remains brace-balanced; Anki decks use language-specific metadata with stable note IDs.

---

## Requirements
- Python 3.11
- `pip install -r requirements.txt`
- Internet access for the selected AI provider (Google Gemini or Anthropic Claude)

---

## Quick Start (Interactive Wizard)
```bash
git clone https://github.com/RazeBerry/FrenchVocab.git
cd FrenchVocab
pip install -r requirements.txt
python FrenchVocab.py --language fr
```
What happens next:
1. **Provider choice.** The wizard lets you pick Google Gemini (recommended) or Anthropic Claude. Each option links to the provider’s signup page.
2. **Key entry.** Paste your API key; the input is hidden. The app validates the key format and performs a live connection test (5 s timeout) before accepting it.
3. **Storage decision.** After a successful validation you choose where to store the key:
   - **System keyring (default).** Saved securely via your OS keychain.
   - **Project `.env` file.** Writes or updates `.env` in the repository root.
   - **Session only.** Sets an environment variable for the current process and reminds you that future runs will prompt again.
4. **Run the CLI.** Once stored, the key is placed in `os.environ` for immediate use and the vocabulary menu appears.

Tips:
- If the keyring backend is unavailable, the wizard automatically falls back and asks you to choose another storage option.
- Keys saved to `.env` are auto-loaded on future runs—even when you launch the CLI from a different directory.

---

## Non-Interactive Credential Setup
Need to script or automate? Provide the key before starting the CLI and the wizard is skipped.

### Option 1 — Environment Variable (highest priority)
```bash
export GEMINI_API_KEY="AIza…"
# or
export ANTHROPIC_API_KEY="sk-ant-…"
python FrenchVocab.py --language fr
```

### Option 2 — System Keyring Entry
```bash
python - <<'PY'
import keyring
keyring.set_password("french_vocab_builder", "gemini_api_key", "AIza…")
PY
python FrenchVocab.py --language fr
```

### Option 3 — Manually Maintain `.env`
Create or update `.env` in the repository root:
```
GEMINI_API_KEY=AIza...
# or
ANTHROPIC_API_KEY=sk-ant-...
```
The file is picked up automatically during startup.

Current resolution order on startup:
1. Environment variable (`GEMINI_API_KEY` / `ANTHROPIC_API_KEY`)
2. Project `.env` file (auto-loaded from the repo root)
3. System keyring entry (service `french_vocab_builder`)
4. Interactive wizard

Invalid values are ignored with an on-screen warning, after which the next source is tried.

---

## Diagnostics

### ESC Latency Trace
If you suspect the ESC key is laggy inside the Rich/Prompt‑Toolkit prompts, enable the ad-hoc tracer:

```bash
export FRENCHVOCAB_ESC_DEBUG=1
# optional: choose a custom path
# export FRENCHVOCAB_ESC_DEBUG_LOG=/tmp/esc_latency.log
python FrenchVocab.py --language fr
```

While the flag is set the CLI writes lifecycle events (prompt start, escape handler invocation, prompt exit) to `~/.frenchvocab/esc_latency.log` by default. Tail the file to inspect raw timings:

```bash
tail -f ~/.frenchvocab/esc_latency.log
```

Tip: you can also pass `--esc-debug` (and `--esc-debug-log=/tmp/esc_latency.log`) when launching `FrenchVocab.py` to set these environment variables automatically for that session.

Unset the environment variable to disable tracing once you have collected enough data.

---

## Everyday CLI Actions
- `python FrenchVocab.py --language de` → add new vocab entries (default menu option 1).
- Translator modes (options 2 and 3) capture multi-line input and preview results before saving.
- Export queued entries to Anki via menu option 4.
- View and search saved vocab using option 5.

Pass `--verbose` for timing details, or `--provider claude` to select Anthropic directly.

## Feature Flags
- Intelligent translator is now on by default: the Translation menu shows an “auto” option that detects direction and routes to the right LaTeX file while still letting you confirm the save. Set `FRENCH_VOCAB_AUTO_TRANSLATOR=0` (or `false`) if you prefer to hide it and stick with the two explicit directions.

---

## Project Layout
| Path | Purpose |
| --- | --- |
| `FrenchVocab.py` | CLI entry point |
| `core/` | Shared workflows (setup wizard, translators, exporting) |
| `cli/` | Menu helpers and bootstrap logic |
| `languages/` | Per-language configs, prompts, and LaTeX templates |
| `tests/` | Pytest suite covering language configs, exporters, and onboarding flows |

---

## Development Workflow
```bash
pip install -r requirements.txt
pytest
```
The test suite uses stubs for external services; no real API calls are made.

---

## Troubleshooting Checklist
- **"No API key found"** – run `python FrenchVocab.py --language fr` and walk through the wizard, or export the key via `export GEMINI_API_KEY=…`.
- **Keyring errors** – your OS keychain may be locked or unsupported; choose the `.env` or session option when prompted.
- **Timeout during validation** – indicates provider connectivity issues. Verify the key is active and try again.

---

Machine-crafted vocabulary, human-readable output. Enjoy building your language decks!
