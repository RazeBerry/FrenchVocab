# Private phone and Mac access

VocabBuilder uses the cloud VM as its single writable home. The phone and the
Mac are two interfaces to the same language-specific files; they are not
independent copies that need bidirectional synchronization.

```text
iPhone home-screen app ─┐
                        ├─ Tailscale ─ VM ─ FrenchVocab.tex + history + backups
Mac browser / Rich CLI ─┘
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
  Menus and text editing run locally while complete operations use the same
  private HTTPS API as the phone. The VM remains authoritative; neither surface
  synchronizes a local copy.
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
safe if the legacy SSH CLI and phone operate at the same time.

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

The host defaults to the private MagicDNS name `vocabbuilder-mobile`; override
it in the private per-user launcher configuration if the Tailscale machine name
changes:

```text
# ~/.config/vocabbuilder/remote.env
VOCABBUILDER_REMOTE_HOST=your-machine-name
```

The launcher asks the local Tailscale daemon for the machine's certificate DNS
name, then calls its private HTTPS API. `VOCABBUILDER_REMOTE_URL` can override
that URL, `VOCABBUILDER_LOCAL_PYTHON` can select the local interpreter, and
`VOCABBUILDER_LAUNCHER_CONFIG` can select a different config path. Language and
provider flags are preserved, so `vocab --language de --provider gemini` opens
that collection directly.

For VM-side diagnostics only, set `VOCABBUILDER_LEGACY_SSH_CLI=1` and
`VOCABBUILDER_REMOTE_USER=your-vm-login`. This restores the former Tailscale SSH
launcher, including its unavoidable per-key network latency.

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
- `/var/lib/vocabbuilder/exports`: operator-enforced destination for terminal-client and mobile Anki packages
- `/etc/vocabbuilder/mobile.env`: root-readable allowed identity and non-secret service settings
- `/var/lib/vocabbuilder/.env`: service-readable provider credentials
- `/usr/local/sbin/vocabbuilder-cli`: root wrapper that sets authoritative
  runtime paths and then drops privileges before launching the full CLI; the
  provider manager reads the service-user credential
- `vocabbuilder-mobile.service`: app server bound to localhost
- `vocabbuilder-backup.timer`: daily local snapshot
