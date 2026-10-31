# LLM providers and credentials

Contract: invariants only. Routed from `docs/llm_map.md`; dated evidence lives
in `reports/` and is linked from the rule it supports.

## Providers
- `llm_coordinator.py` manages provider initialization lifecycle, degraded mode, and usage metrics, and uses generation-guarded background init so stale workers cannot overwrite newer provider changes.
- `vocab_builder/core/providers/manager.py` owns provider metadata, setup wizard flows, and storage destinations.
- Gemini defaults to `gemini-3.8-flash` for local and VM use. The VM sets
  `VOCABBUILDER_GEMINI_MODEL` in `/etc/vocabbuilder/mobile.env` so the mobile
  service and legacy remote CLI agree even before a source deployment. Its
  generation config uses thinking levels and omits deprecated sampling
  parameters (`temperature`, `top_p`, and `top_k`) that current Gemini models no
  longer support. Panel results dated before 2026-10-31 measure Gemini 3.7
  (`reports/providers/2026-10-29_gemini_3.8_default.md`).
- The Google Gen AI Python SDK is constrained to `>=2.25.0,<3.0.0`. The floor
  is the version the panel measured
  (`reports/providers/2026-09-28_genai_2.25_floor.md`); the upper bound follows
  Google's published warning that direct model-call behavior changes in the
  next major.
- Gemini generation is atomic because every application caller consumes a full
  response before using it. Each application action makes exactly one generation
  request to the selected model. SDK retries are disabled (`attempts=1`), there
  is no model fallback, automatic function calling is disabled, and a 503 is
  surfaced immediately. Do not add application or SDK retry/fallback loops, a
  token-count follow-up request, or an SSE stream.
- Claude follows the same one-request rule: the Anthropic client is built with
  `max_retries=0`, because the SDK's default of two retries turned one hung
  action into three provider timeouts behind a browser that stops waiting at
  130 seconds. Claude requests send no sampling parameters (`temperature`,
  `top_p`, `top_k`); current Claude models reject them with a 400, so pinning
  one made `VOCABBUILDER_CLAUDE_MODEL` unable to name a current model.
- Vocabulary generation, directional translation, and automatic direction
  detection all think at `DEFAULT_THINKING_LEVEL` in `llm_client.py`, currently
  `low`. No workflow passes its own level, so that constant is the one owner.
  Low trades some entry quality for a look-up of about 3.5 s instead of 10-15 s;
  the measurements and the defects it costs are in
  `reports/prompt_panel/2026-10-31_thinking_level_low.md`. Change the level only
  with a panel run saved in `scripts/prompt_panel/results/`.
- Provider diagnostics record model, elapsed time, classified outcome, and
  exception type but never prompt text. A request taking at least 10 seconds and
  every failure emits a warning to the service journal so production latency can
  be reconstructed without making journald another vocabulary-history store.
- `--provider` selects provider metadata but does not make initialization eager;
  only `--eager-llm` puts provider SDK import, client construction, and credential
  verification on the startup critical path. Background initialization status
  is rendered from the current state without waiting in the welcome or main-menu
  path.
- `provider_settings()` reports `label` (provider and model on one line, for terse
  surfaces) and `model` (the bare identifier) separately, because the phone names
  the provider in a heading and the model beneath it. Splitting a combined label
  with string surgery in the browser would put a server rule in the client.

## Credentials
- Credential resolution is: environment variable first (including values loaded from `.env`), then keyring fallback, then interactive setup.
- Gemini credential setup and reload accept both standard `AIza` keys and
  current `AQ.` authorization keys. Prefix checks only identify the format;
  provider validation determines whether a key is usable. Onboarding must
  not promise a fixed free-tier allowance: limits belong to the Google project
  and billing tier.
- `.env` path resolution order is: `VOCABBUILDER_CONFIG_DIR/.env`, then writable project `.env`, then `~/.vocabbuilder/.env` (falls back to `~/.frenchvocab/.env` for legacy installs).
- Plaintext `.env` fallback writes are atomic, best-effort permission-hardened, and do not retain a stale backup after a successful key rotation.
- Keyring service name is `vocab_builder` (silently migrates from legacy `french_vocab_builder`).

## Provider credential flow
1. Load `.env` from the resolved config path when available.
2. Resolve credentials from environment variables before keyring.
3. Fall back to keyring lookup when env credentials are missing/invalid.
4. Launch guided/advanced interactive setup when credentials are still unavailable.
