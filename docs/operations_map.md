# Operations: deploy, backup, security, configuration, tests

Router: routes an intent to the document or code that owns it. It carries no
invariants; if a rule is written here, move it to its owner.

## Routes

| To | Read |
|---|---|
| Deploy, or understand the VM and Tailscale topology | `docs/MOBILE.md`, `docs/operations.md` |
| Back up or restore VM data | `docs/operations.md` (Backup and restore) |
| Add or change an environment variable | `docs/environment.md` |
| Write tests, or change CI | `docs/testing.md` |
| Check the knowledge ratchet | `python scripts/knowledge_ratchet.py --check` |

## Where the code lives
- `scripts/deploy/` holds the pushed-commit VM deploy front door, provisioning, backup and restore scripts; `scripts/macos/vocab` launches the local Rich client backed by the VM API, and `scripts/macos/install_backup_pull.sh` schedules the daily off-host archive copy.
- `deploy/` holds the systemd unit and timer files for the mobile server and its daily backup.
- `tests/` is a pytest suite (`test_*.py`) for architecture boundaries, onboarding, translators, language config, exporters, and UI behavior.
