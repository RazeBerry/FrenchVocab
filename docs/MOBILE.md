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
- Capture has the same AI preview, spelling correction, duplicate rejection,
  explicit merge/variant choices, sentence routing, atomic save, history, and
  Anki ordering as the CLI. Translate, Library, Practice, and Tools expose the
  remaining non-interactive workflows. For the current production presentation,
  the bottom navigation shows only Add and Translate; the other implemented
  views are hidden until their phone UI is ready. English is monolingual and
  therefore presents Add alone.
- On Mac, use the same website or run `vocab` for the Rich terminal interface.
  The remote CLI asks which language collection to open, then reads and writes
  the same authoritative files as the phone. Neither surface synchronizes a
  local copy.
- Do not run the old local `vocabbuilder` command against the repository's local
  vocabulary files after cutover. They become migration snapshots, not a second
  production database.

The server listens only on `127.0.0.1:8080`. Tailscale Serve supplies private
HTTPS and the signed-in Tailscale identity; no application port is opened to the
public internet. The provider API key remains in
`/var/lib/vocabbuilder/.env` on the VM and is never returned by the API or
written to browser storage. The private Tools view can validate and rotate it;
the service-user config remains authoritative after a restart.

The mobile process owns one isolated service per configured language. Each
service keeps its own repository lock, AI lock, durable preview/receipt journal,
history, and authoritative LaTeX file while sharing the authenticated HTTPS
surface and provider credential. Run one web worker: the journal is a
single-process request state machine, while file locks make the underlying data
safe when the remote CLI and phone operate at the same time.

The phone deliberately has no arbitrary edit, delete, upload, or restore API.
Those are not normal CLI workflows either. Current files, backups, and generated
Anki decks are exposed only through allowlisted downloads so recovery access
cannot become remote filesystem access.

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
It preserves CLI options, so commands such as `vocab --language de` behave like
their direct `vocabbuilder` equivalents on the VM.

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
- `/var/lib/vocabbuilder/exports`: operator-enforced destination for remote CLI and mobile Anki packages
- `/etc/vocabbuilder/mobile.env`: root-readable allowed identity and non-secret service settings
- `/var/lib/vocabbuilder/.env`: service-readable provider credentials
- `/usr/local/sbin/vocabbuilder-cli`: root wrapper that sets authoritative
  runtime paths and then drops privileges before launching the full CLI; the
  provider manager reads the service-user credential
- `vocabbuilder-mobile.service`: app server bound to localhost
- `vocabbuilder-backup.timer`: daily local snapshot
