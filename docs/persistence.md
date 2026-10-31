# Persistence and concurrency

Contract: invariants only. Routed from `docs/core_map.md`; dated evidence lives
in `reports/` and is linked from the rule it supports.

## Rules
- `file_safety.py` provides atomic file operations and rotating backups, and
  owns the lost-file rule: when a vocabulary or translation file is missing
  but a `.bak` beside it proves it held data, `refuse_to_recreate_lost_file`
  raises `LostDataFileError` naming the newest backup, and the CLI exits with
  that message. Three copies of an automatic restore used to put the `.bak`
  back, which is the state before the last write, so the latest save
  vanished while history and Anki still referenced it. Only a file with no
  backups at all is a first run and gets the blank template.
- In the deployed topology, `/var/lib/vocabbuilder` is the only writable source of truth. The phone surface and the Mac `vocab` launcher operate on that VM state; repository-local vocabulary files are migration snapshots, not a second database. Do not introduce bidirectional file sync.
- Every persisted read-modify-write must use `vocab_builder.core.file_safety.file_lock(path)`. It acquires the catalog-wide `.vocabbuilder.lock` before the artifact sidecar `.<filename>.lock`; nested acquisition in one thread is deliberately reentrant.
- Cross-process lock files must remain beside the authoritative data/config root, never in the temporary directory. The systemd service uses `PrivateTmp=true`, so `/tmp` locks would split the API worker and legacy SSH CLI into different lock domains and reintroduce silent lost updates.
- Reload authoritative disk state only after acquiring the commit lock. Duplicate checks, merge calculations, insertion decisions, and Anki state reconciliation must be recomputed inside that transaction rather than trusting pre-lock caches.
- Keep a vocabulary mutation, its history append, and its Anki acquisition-order update inside one outer catalog transaction. Continue using atomic replacement for rewritten files and `flush` + `fsync` for append-only JSONL.
- Each language service has a short-lived state lock and a dedicated AI lock. Provider calls are serialized within one language so mutable provider clients and usage counters cannot overlap; separate language services may still generate concurrently. Read-only library/status work remains responsive while capture AI is running.
- Mobile preview releases its state lock across provider recovery and generation, then re-validates duplicates after reacquiring it. Phone saves register Anki acquisition order inside the same catalog transaction as the vocabulary write and history append.
- A vocabulary or translation save is idempotent by its durable preview token. Persist the journal before the primary file mutation, record the primary commit before auxiliary work, and retain incomplete history/Anki steps for replay. A restart after the file write must reconstruct the same receipt rather than duplicate or lose the entry.
- A save that raises in the same request decides from disk, inside the commit lock, whether the primary write landed. If it did not, the journal is dropped before the error reaches the phone, so the next `/api/status` cannot quietly commit a save the user was told failed; the preview survives, so tapping Save again works once. If it did, the request returns the receipt of the save that happened.
- Practice grading records its generated feedback before appending attempt history, then repairs a missing append by stable attempt ID. Auxiliary history failures may produce a visible pending state, but they must never roll back or misreport an already committed primary file.
- A merge that adds nothing must not claim it did. `save()` recomputes the diff
  from reloaded disk state inside the commit lock; an empty diff writes no
  journal entry, leaves the vocabulary file byte-identical, and returns
  `action: "unchanged"`. A non-empty diff records its counts on the transaction
  *before* the primary write, because afterwards the content is already present
  and a re-derived diff would be empty -- replay would then report "unchanged"
  for a merge that really happened. The repository rewrites a merged block and
  returns success whether or not anything changed, so this is the only layer
  that can tell the user the truth.
- A merge history record states what the merge added, with counts from the diff
  recomputed against reloaded disk state inside the commit lock. The mobile save
  carries that diff on the transaction as `history_metadata` *before* the
  primary write, because once the file is written the added senses are part of
  the entry and a replayed history step could no longer derive them. Both
  surfaces write the same `metadata.added_definitions` / `added_examples` shape,
  so `/api/recent` reads one shape. A journal record written before the field
  existed replays with empty metadata; its counts are display-only, so replay
  completes rather than stalling on every restart (a test seeds such a record).
- Never infer transaction ownership from the presence of a duplicate alone. Recovery may treat stored content as this operation only when the durable pre-write journal and exact/contained structured payload prove it; a competing session's duplicate must remain a conflict.
- Repository cache invalidation uses `(device, inode, mtime_ns, size)` signatures. Do not weaken it to timestamps alone.

## Persisting mutable state safely
1. Acquire `file_lock()` for the authoritative artifact (which also takes the catalog lock).
2. Reload the current file/index while holding that lock.
3. Repeat duplicate/conflict validation and compute the mutation from the refreshed state.
4. Commit the primary file atomically, then write coupled history/tracker state before releasing the outer transaction.
5. Add a multiprocessing regression test that starts stale independent instances and proves every successful mutation survives. Thread-only tests are insufficient for VM/CLI concurrency.
