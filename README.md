# FrenchVocab — LaTeX + Anki Builder (AI‑Assisted)

**What It Is**
- Interactive CLI to build a structured French vocabulary LaTeX file and export to Anki.
- AI‑assisted definitions/examples using Gemini (default) or Claude.
- Stores API keys securely in the system keyring; never commits secrets.

**Why Use It**
- Fast capture: type a word/expression, get clean LaTeX, examples, and consistent formatting.
- Export to `.apkg` for spaced repetition in Anki.
- Robust LaTeX parsing with balanced‑brace logic for reliability.

**Quick Start**
- Requirements: Python 3.8+, `pip`, and an API key for one provider.
- Install dependencies:
  - `pip install -r requirements.txt`
- Run the app:
  - `python FrenchVocab.py [path/to/FrenchVocab.tex] [--provider gemini|claude] [--verbose]`
- First run bootstraps your API key (prompted, saved to system keyring). Environment variables also work:
  - `GEMINI_API_KEY` for Gemini
  - `ANTHROPIC_API_KEY` for Claude

**Core Features**
- Add words/expressions with AI‑generated:
  - Word type, English definitions, 3 examples (FR + EN translation)
- Duplicate handling (skip/view/merge/force‑add)
- Alphabetize entries automatically
- Search and display existing entries
- Export to Anki (`.apkg`) via `genanki`

**CLI Usage**
- Default provider is Gemini. Override with `--provider claude`.
- Optional LaTeX path argument; otherwise uses `FrenchVocab.tex` next to the script.
- Example:
  - `python FrenchVocab.py --provider gemini --verbose`
  - `python FrenchVocab.py ~/notes/FrenchVocab.tex --provider claude`

**Configuration**
- Keys are read in this order: environment variable → system keyring → interactive prompt.
- Secure storage via `keyring` under the service `french_vocab_builder`.
- Minimal validity checks are applied before setting `GEMINI_API_KEY`/`ANTHROPIC_API_KEY` in process env.

**Project Layout**
- `FrenchVocab.py` — main CLI app: prompts, AI orchestration, LaTeX insert/sort, Anki export.
- `latex_repository.py` — balanced‑brace LaTeX parser that loads `\entry{...}` blocks into `WordEntry`.
- `latex_templates.py` — LaTeX preamble, sample entry, and AI prompt template contract.
- `llm_client.py` — provider factory and streaming clients: Gemini (default), optional Claude.
- `models.py` — `WordEntry` dataclass and normalization helpers.
- `ui_helper.py` — Rich‑based UI panels, tables, messages.
- `eng_to_fr_translator.py` / `fr_to_eng_translator.py` — simple translators writing `EnglishToFrench.tex` and `FrenchToEnglish.tex`.
- `eng_to_fr_latex_templates.py` / `fr_to_eng_latex_templates.py` — respective LaTeX scaffolding.
- `merge_tex_vocab.py` — CLI to merge two LaTeX vocab files uniquely.
- `tests/` — parsing and formatting tests for core behaviors.

**Security Notes**
- No API keys or `.tex/.pdf/.json/.apkg` artifacts are tracked; see `.gitignore`.
- Keys are entered via hidden prompt (`getpass`) and saved only to system keyring on consent.
- Consider adding `.env` to your global gitignore if you use dotenv locally.

**Troubleshooting**
- Missing key: set `GEMINI_API_KEY` or `ANTHROPIC_API_KEY`, or follow the interactive setup.
- Token/stream errors: re‑check provider and key validity; `--verbose` prints timing metrics.
- LaTeX insertion point not found: ensure file still contains the generated `\begin{itemize}` / `\end{itemize}` scaffolding.
- Anki export: verify at least one valid `\entry{...}` exists.

**Development**
- Clone:
  - `git clone https://github.com/RazeBerry/FrenchVocab.git`
  - `cd FrenchVocab`
- Install deps:
  - `pip install -r requirements.txt`
- Run tests (if you have a test runner configured):
  - `python -m pytest -q`

**License**
- No license file is present; default is “all rights reserved”. Add a license if you plan external contributions.
