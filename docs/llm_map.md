# LLM: providers, credentials, prompts

Router: routes an intent to the document or code that owns it. It carries no
invariants; if a rule is written here, move it to its owner.

## Routes

| To | Read |
|---|---|
| Change a provider client, model default, SDK bound, retries, thinking level or diagnostics | `docs/providers.md` |
| Change credential storage or resolution | `docs/providers.md` (Credentials) |
| Edit a vocabulary, merge or translation prompt, or the response parser | `docs/prompts.md` |
| Measure a prompt or thinking-level change | `docs/prompts.md` (Prompt panel), then save the run in `scripts/prompt_panel/results/` |
| Read why a prompt or provider setting is what it is | `reports/prompt_panel/`, `reports/providers/` |

## Where the code lives
- `vocab_builder/core/providers/manager.py` encapsulates provider selection, credential validation, and secure storage.
