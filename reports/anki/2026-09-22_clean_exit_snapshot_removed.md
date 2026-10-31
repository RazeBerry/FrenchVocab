# Why the clean-exit Anki snapshot was removed

Evidence, 2026-09-22. Never edited after landing; a correction is a new dated
report that links this one. Moved verbatim from `AGENTS.md` by the 2026-10-31
knowledge sweep.

Every Anki package is an explicit export: the VM CLI's Anki tools, the Mac client's Anki menu (which downloads the package to the Mac), or the phone's Tools view. The clean-exit snapshot that rebuilt a complete `.apkg` on the VM was removed on 2026-09-22. Nothing on the Mac ever fetched that file, the remote client's exit path never called it, and the phone has no exit, so it was a mode that wrote a package no reader consumed. Do not reintroduce an unattended export without a consumer on the Mac side. A tracker written before that date still carries `snapshot_hash` and `snapshot_export`; the loader ignores them and the next save drops them.
