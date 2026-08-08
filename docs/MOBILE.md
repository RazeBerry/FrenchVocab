# Private phone and Mac access

VocabBuilder uses the cloud VM as its single writable home. The phone and the
Mac are two interfaces to the same language-specific files; they are not
independent copies that need bidirectional synchronization.

```text
iPhone home-screen app ─┐
                        ├─ Tailscale ─ VM ─ FrenchVocab.tex + history + backups
Mac browser / SSH CLI ──┘
```

## Everyday use

- On iPhone, connect Tailscale and open the private HTTPS address. Select
  French, German, or English from the header. Safari's **Share → Add to Home
  Screen** makes it behave like a small standalone app.
- On Mac, use the same website for quick capture or run `vocab` for the complete
  Rich terminal workflow. The remote CLI asks which language collection to open,
  then reads and writes the same authoritative files as the phone.
- Do not run the old local `vocabbuilder` command against the repository's local
  vocabulary files after cutover. They become migration snapshots, not a second
  production database.

The server listens only on `127.0.0.1:8080`. Tailscale Serve supplies private
HTTPS and the signed-in Tailscale identity; no application port is opened to the
public internet. The provider API key remains in `/etc/vocabbuilder/mobile.env`
on the VM and is never sent to browser storage.

The mobile process owns one isolated service per configured language. Each
service keeps its own repository lock, preview tokens, history, and authoritative
LaTeX file while sharing the authenticated HTTPS surface and provider credential.

## Mac launcher

Install the launcher somewhere on `PATH`:

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/scripts/macos/vocab" ~/.local/bin/vocab
```

Keep the VM login in the private per-user launcher configuration rather than
hardcoding deployment identity in the public repository:

```text
# ~/.config/vocabbuilder/remote.env
VOCABBUILDER_REMOTE_USER=your-vm-login
```

The host defaults to the private MagicDNS name `vocabbuilder-mobile`; override
it in the same file with `VOCABBUILDER_REMOTE_HOST` if the Tailscale machine
name changes. `VOCABBUILDER_LAUNCHER_CONFIG` can select a different config
path. The launcher uses `tailscale ssh`, which verifies the VM host key against
your tailnet and does not depend on a manually maintained `known_hosts` entry.

## Storage and recovery

The VM stores mutable state under `/var/lib/vocabbuilder`. Atomic writes and the
existing rotating `.tex` backups protect each edit. A systemd timer also creates
a compressed daily snapshot in `/var/lib/vocabbuilder/backups` and keeps 30
days. Periodically copying one snapshot to the Mac protects against loss of the
entire VM or disk.

## Deployment layout

- `/opt/vocabbuilder`: read-only installed application
- `/opt/vocabbuilder/.venv`: Python runtime and mobile dependencies
- `/var/lib/vocabbuilder`: vocabulary, history, exports, and backups
- `/etc/vocabbuilder/mobile.env`: root-readable provider credential and allowed user
- `/usr/local/sbin/vocabbuilder-cli`: root wrapper that injects the server-only
  credential and then drops privileges before launching the full CLI
- `vocabbuilder-mobile.service`: app server bound to localhost
- `vocabbuilder-backup.timer`: daily local snapshot
