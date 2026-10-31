# CLI and local terminal

Contract: invariants only. Routed from `docs/core_map.md`; dated evidence lives
in `reports/` and is linked from the rule it supports.

## Commands
```bash
# Run the CLI
vocabbuilder --help
vocabbuilder --language fr
vocabbuilder --language de
vocabbuilder --language en
vocabbuilder --language fr --provider gemini
vocabbuilder --language fr --provider claude
vocabbuilder --language fr --latex-file ./FrenchVocab.custom.tex
vocabbuilder --language fr --eager-llm
python -m vocab_builder --help

# Diagnostics and demos
vocabbuilder --esc-debug
vocabbuilder --esc-debug --esc-debug-log /tmp/esc_latency.log
python scripts/demo_guided_onboarding.py

# Operator bulk-add workflow
python scripts/bulk_add.py --language fr --file entries.json --dry-run
python scripts/bulk_add.py --language fr --file entries.json --json
```

## Local terminal boundary
- `scripts/macos/vocab` normally launches `vocab_builder.cli.remote_client` on
  the Mac. Rich rendering, arrow navigation, and prompt editing stay local;
  only complete status, data, AI, and mutation requests cross the private
  Tailscale HTTPS boundary. The VM remains the only data store.
- `remote_client.py` adapts terminal interactions to the existing `/api`
  contracts. Do not duplicate repository, translation, duplicate, provider, or
  persistence rules there; those stay in the shared VM services.
- `VOCABBUILDER_LEGACY_SSH_CLI=1` restores the full VM-side CLI for diagnostics.
  It is an explicit escape hatch because every keypress then pays the SSH path's
  round-trip latency.
- `vocab_builder/cli/navigation.py` renders menus with `Live(auto_refresh=False)`
  and repaints only when the selection moves. Re-enabling Rich's refresh thread
  repaints the whole panel about 24 times a second for as long as a menu is open.
- `_read_escape_remainder` stops as soon as the buffered bytes form a complete
  CSI or SS3 sequence. Without that early exit, every arrow key waits out a full
  `VOCABBUILDER_ESC_SEQUENCE_TIMEOUT` for a continuation byte that never comes,
  and that wait lands on top of the round trip.
- `startup_warmup.start_entry_warmup` runs before provider initialization
  because the first menu refresh blocks on an authoritative entry count.
  Scheduling the parse later leaves nothing for it to overlap with and puts it
  in front of the welcome screen.
- Interactive TTY menus deliberately show bullets and accept navigation only
  through the arrow keys followed by Enter. Digit keys are ignored even when a
  menu has nine or fewer choices; do not add ordinals or numeric shortcuts to
  the Rich interface. The numbered line-mode fallback exists only for non-TTY
  environments where raw arrow input is unavailable.
- The local launcher preserves Rich raw-key menus, arrow navigation, immediate
  Escape handling, and prompt-toolkit text editing. Do not replace that
  interaction contract with canonical numbered-line menus.

## UI messaging
Route status messaging through `UIHelper` methods:
```python
self.ui.success("Entry saved!")
self.ui.error("Failed", with_panel=True)
self.ui.warning("Duplicate detected")
self.ui.info("Processing...", accent="dim")
self.ui.panel(content, title="Title", border_style="dark_orange")
```

## Interactive menus
```python
choice = self.ui.interactive_menu(
    "Menu Title",
    [("key1", "Label 1"), ("key2", "Label 2")],
    "Helper text for navigation",
)
```
