# Testing and CI

Contract: invariants only. Routed from `docs/operations_map.md`; dated evidence lives
in `reports/` and is linked from the rule it supports.

## Tests
- Keep tests mirrored to modules (for example `vocab_builder/core/vocab.py` -> `tests/test_sentence_flow.py`).
- Name new files `test_<feature>.py` and test functions `test_<behavior>`.
- Use stubs/fixtures (`tests/_stubs.py`) to avoid real API calls.
- Browser logic whose correctness depends on platform behavior runs under Node against the real module, not a grep of its source: `tests/test_mobile_api_client.py` drives `api.js` with Node's real `fetch` against a socket that never answers, because an aborted fetch rejects with the abort reason itself (the string `"timeout"`), not an `AbortError`. Node is required locally and is present on CI's `ubuntu-latest` runner. `tests/test_mobile_views_js.py` runs the real capture and glossary views against the small browser stand-in in `tests/js/fake_dom.mjs`; extend that stand-in rather than asserting on source text when a view's behavior changes.
- Concurrency changes must cover both in-process threads and POSIX processes. Keep the isolated-`tempfile.tempdir` regression in `tests/test_concurrency_transactions.py`; it models systemd `PrivateTmp` without touching production data.
- Mobile changes should exercise the ASGI surface in `tests/test_mobile_service.py`, including duplicate commits, save retries, language routing, Tailscale identity enforcement, and cross-language worker-thread behavior.

## CI
- CI installs the project with its `[mobile]` extra before collecting the full suite because the mobile service tests import FastAPI directly. Keep the extra in the lint-and-test dependency install unless those tests move to a separately provisioned job.
- GitHub workflows use the Node 24 generations of the official actions (`actions/checkout@v7` and `actions/setup-python@v7`). Older Node 20 generations are deprecated and produce runner warnings; update all workflow references uniformly when advancing either action.
- Ruff linting deliberately selects the stable `E4`, `E7`, `E9`, and `F` rule families in `pyproject.toml`, and CI constrains Ruff to the `0.16.x` compatibility line. Ruff minor releases can change defaults incompatibly, so update the rule policy and CI constraint together and review newly enabled rules before adopting a later line.
