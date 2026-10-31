# Anki export

Contract: invariants only. Routed from `docs/core_map.md`; dated evidence lives
in `reports/` and is linked from the rule it supports.

## Export
- `anki_manager.py` coordinates export state and Anki generation, including persistent acquisition order so decks do not inherit LaTeX alphabetization.
- Every Anki package is an explicit export: the VM CLI's Anki tools, the Mac
  client's Anki menu (which downloads the package to the Mac), or the phone's
  Tools view. Do not reintroduce an unattended export without a consumer on the
  Mac side. A tracker written before 2026-09-22 still carries `snapshot_hash`
  and `snapshot_export`; the loader ignores them and the next save drops them.
  Why: `reports/anki/2026-09-22_clean_exit_snapshot_removed.md`.
- Anki note GUIDs normally derive from the lowercased, stripped headword.
  `anki_identity_<lang>.json` beside `exported_words_<lang>.json` is the sole
  owner of corrected-headword GUID seeds. Its versioned alias map is private
  mutable VM data, never a language-config literal or tracked repository file.
  An export loads it under the catalog lock and supplies it to `AnkiExporter`;
  a selected-words export updates the existing Anki note when its GUID stays
  the same. Anki never deletes notes omitted from a package.
- The tracker records, for every exported word, a fingerprint of the note
  fields Anki received (headword, type, definitions, examples). Pending means
  never exported *or* exported with different fields, so a merge, a
  correction or a hand edit makes the note pending again and the next
  incremental export updates it in place. Merges used to be marked done for
  Anki and every later incremental export skipped the word, so the deck kept
  the old note for good. The exporter is the sole owner: no write path has to
  remember to mark a word dirty. A word with no fingerprint (tracker written
  before 2026-09-28) counts as changed. When this shipped, the VM's trackers
  were seeded with each word's current fields, because the packages in
  `exports/` showed every merged or corrected word packaged after its last
  change.
- Anki tracker writes use a three-way merge of the manager's persisted baseline, current disk state, and local changes so concurrent additions and intentional removals do not overwrite one another.
