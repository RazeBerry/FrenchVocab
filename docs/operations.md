# Operations and security

Contract: invariants only. Routed from `docs/operations_map.md`; dated evidence lives
in `reports/` and is linked from the rule it supports.

## Deployment and security
- `scripts/deploy/deploy_vm.sh` is the sole repeat-deploy front door for an existing VM. It uses the private `~/.config/vocabbuilder/remote.env` login, requires a clean checkout whose `HEAD` equals the configured upstream's live remote tip, streams `git archive`, preserves the VM `.venv` and `/var/lib/vocabbuilder`, installs the package with its `[mobile]` dependencies and runs `pip check`, verifies the installed bytes, refreshes units, then restarts and probes the service. See `docs/MOBILE.md` for usage. Do not encode a personal VM login or tailnet address in tracked files.
- Deployed provider credentials live in `/var/lib/vocabbuilder/.env`, where the non-interactive provider manager can rotate them atomically. `/etc/vocabbuilder/mobile.env` is reserved for the allowed Tailscale identity and non-secret service settings; putting a key there would override the rotatable credential on restart.
- Keep deployment identity in root-owned VM environment files or untracked local shell configuration. Tracked documentation and launcher defaults should use generic machine names and placeholders wherever practical.
- Public service topology and filesystem paths are not authentication. Preserve the actual boundary: localhost binding, Tailscale Serve identity, tailnet policy, and server-only credentials.

## Backup and restore
- `scripts/deploy/backup_mobile_data.sh` takes the same catalog lock with util-linux `flock` before archiving. Any new backup/export path that needs a coherent multi-file snapshot must join that lock domain.
- Daily archives are named `vocabbuilder-data-*.tar.gz` and never contain `.env`. That name is the contract `MobileStorage` reads: only those archives join the read-only recovery downloads, so the provider key still never leaves the VM, while older `vocabbuilder-*.tar.gz` archives (which may hold it) stay VM-local until the 30-day prune. The Mac keeps the off-host copy: `vocab_builder/cli/backup_pull.py` pulls the newest archive through the identity-checked API, not Tailscale SSH, whose periodic browser check would stall an unattended job; it reads the whole stream before keeping a file and keeps 30. `scripts/macos/install_backup_pull.sh` schedules it with launchd and resolves the interpreter and private URL at install time, so no personal value is tracked.
- `scripts/deploy/restore_mobile_data.sh ARCHIVE` is the one restore path: it verifies the archive decompresses whole before stopping anything, stops the service (its in-memory journal must not replay onto restored files), moves every current file into `backups/pre-restore-<stamp>/` rather than deleting it, extracts under the catalog lock, never touches `.env`, and restarts. `tests/test_backup_restore.py` runs the real backup and restore scripts and reads the collection back.
