# Environment variables

Contract: invariants only. Routed from `docs/operations_map.md`; dated evidence lives
in `reports/` and is linked from the rule it supports.

## Variables
All variables use the `VOCABBUILDER_*` prefix. Legacy `FRENCHVOCAB_*` and `FRENCH_VOCAB_*` names are still recognized via `vocab_builder/compat.py` with deprecation warnings.
- `GEMINI_API_KEY` / `ANTHROPIC_API_KEY`: Provider API credentials.
- `VOCABBUILDER_CLAUDE_MODEL`: Override Claude model ID (default `claude-sonnet-4-6`).
- `VOCABBUILDER_GEMINI_MODEL`: Override Gemini model ID (default `gemini-3.8-flash`).
- `VOCABBUILDER_PROVIDER_TIMEOUT`: Provider request deadline in seconds (default `120`).
- `VOCABBUILDER_PROVIDER_RETRY_COOLDOWN`: Minimum seconds between silent provider re-initialization attempts (default `30`).
- `VOCABBUILDER_ALLOWED_TAILSCALE_USER`: Tailscale login accepted by the private mobile interface; requests are not identity-checked when unset.
- `VOCABBUILDER_CONFIG_DIR`: Override directory used for `.env` storage/loading.
- `VOCABBUILDER_SKIP_KEYRING=1`: Disable keyring lookups/storage.
- `VOCABBUILDER_FORCE_SYNC_LOAD=1`: Force synchronous loading (useful in tests).
- `VOCABBUILDER_ESC_SEQUENCE_TIMEOUT`: ESC key sequence timeout in seconds (default `0.03`).
- `VOCABBUILDER_ESC_DEBUG=1`: Enable ESC latency tracing.
- `VOCABBUILDER_ESC_DEBUG_LOG`: Custom log path for ESC latency tracing.
- `VOCABBUILDER_DEBUG_EXPORT=1`: Print export debug details during Anki generation.
- `VOCABBUILDER_AUTO_TRANSLATOR`: Enable/disable intelligent translator option.
- `VOCABBUILDER_COMPOSITION`: Enable/disable composition practice (default on).
- `VOCABBUILDER_ANKI_EXPORT_DIR`: Operator-controlled root for deck-name-only Anki exports. When set, an absolute destination outside it is rejected; the VM sets this to `/var/lib/vocabbuilder/exports`.
- `VOCABBUILDER_COMPOSITION_WORDS`: Target words per use-these-words attempt (default `3`, int >= 1).
- `VOCABBUILDER_COMPOSITION_SET_SIZE`: Attempts per daily composition set (default `3`, int >= 1).
- `VOCABBUILDER_MAX_BACKUPS`: Maximum timestamped backup snapshots to retain per file (default `10`; `0` disables pruning).
- `VOCABBUILDER_MAX_CHARS`: Override maximum input length.
- `VOCABBUILDER_MAX_WORDS`: Override max words allowed per input.
- `VOCABBUILDER_SENTENCE_MODE` / `VOCABBUILDER_ALLOW_PUNCT`: Toggle punctuation/sentence acceptance.
- `VOCABBUILDER_ROUTE_SENTENCES`: Toggle sentence routing behavior.
- `VOCABBUILDER_SENTENCE_EXAMPLES`: Toggle sentence examples in vocab entries.
- `VOCABBUILDER_HISTORY_DISABLED` / `VOCABBUILDER_HISTORY_ENABLED`: Disable/enable translation history logging.
- `VOCABBUILDER_HISTORY_DIR`: Override history log directory (default `~/.vocabbuilder/history`).
- Boolean flags accept typical truthy values such as `1`, `true`, `yes`, `y`, and `on`.
