#!/usr/bin/env python3
"""Knowledge ratchet: the instruction file and its documents may shrink, never sprawl.

AGENTS.md grew from 36 lines to 874 in three months because every change added
a paragraph and nothing ever took one out. This check measures the knowledge
surfaces and fails when a metric rises above the committed baseline:

    python scripts/knowledge_ratchet.py --check            # CI and pytest
    python scripts/knowledge_ratchet.py --print-baseline   # after a cleanup

The baseline in ``knowledge_ratchet_baseline.json`` only ever moves down.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_NAME = "scripts/knowledge_ratchet_baseline.json"
INSTRUCTION_FILE = "AGENTS.md"
LINK = re.compile(r"(?:docs|reports)/[\w./-]+\.md")
DATE = re.compile(r"20\d\d-\d\d-\d\d")


def _tracked(root: Path, *dirs: str) -> list[str]:
    """Markdown files git tracks or would track; ignored local notes are excluded."""
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "--", *dirs],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    return sorted(p for p in out if p.endswith(".md") and (root / p).is_file())


def measure(root: Path, today: dt.date | None = None) -> dict[str, int]:
    today = today or dt.date.today()
    docs = _tracked(root, "docs")
    reports = _tracked(root, "reports")
    routers = [p for p in docs if p.endswith("_map.md")]
    proposals = [p for p in docs if p.startswith("docs/proposals/")]
    contracts = [p for p in docs if p not in routers and p not in proposals]
    text = {p: (root / p).read_text(encoding="utf-8") for p in [INSTRUCTION_FILE, *docs, *reports]}

    owners = [INSTRUCTION_FILE, *docs]  # a report counts as linked only from an owner
    unreachable = 0
    for doc in docs:
        if not any(doc in text[o] for o in owners if o != doc):
            unreachable += 1
    for report in reports:
        if not any(report in text[o] for o in owners):
            unreachable += 1

    broken = sum(
        1 for p in owners for link in set(LINK.findall(text[p])) if not (root / link).is_file()
    )

    bad_proposals = 0
    for p in proposals:
        owner = re.search(r"^owner:\s*\S", text[p], re.M)
        sunset = re.search(r"^sunset:\s*(\d{4}-\d\d-\d\d)", text[p], re.M)
        if not owner or not sunset or dt.date.fromisoformat(sunset.group(1)) < today:
            bad_proposals += 1

    def dated_lines(p: str) -> int:
        return sum(1 for line in text[p].splitlines() if DATE.search(LINK.sub("", line)))

    return {
        "instruction_file_lines": len(text[INSTRUCTION_FILE].splitlines()),
        "router_count": len(routers),
        "largest_contract_lines": max((len(text[p].splitlines()) for p in contracts), default=0),
        "contract_dated_lines": sum(dated_lines(p) for p in contracts + routers),
        "unreachable_documents": unreachable,
        "broken_links": broken,
        "unowned_or_expired_proposals": bad_proposals,
    }


# These must stay at zero whatever the baseline says.
ZERO = ("unreachable_documents", "broken_links", "unowned_or_expired_proposals")
# router_count may grow when a domain appears; it is reported, not ratcheted.
UNRATCHETED = ("router_count",)


def check(root: Path, today: dt.date | None = None) -> list[str]:
    baseline = json.loads((root / BASELINE_NAME).read_text(encoding="utf-8"))
    current = measure(root, today)
    failures = []
    for key, value in current.items():
        limit = 0 if key in ZERO else baseline.get(key)
        if key in UNRATCHETED or limit is None:
            continue
        if value > limit:
            failures.append(f"{key}: {value} > {limit}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--print-baseline", action="store_true")
    args = parser.parse_args(argv)
    if args.print_baseline:
        print(json.dumps(measure(args.root), indent=2))
        return 0
    failures = check(args.root)
    for failure in failures:
        print(f"knowledge ratchet: {failure}", file=sys.stderr)
    if not failures:
        print("knowledge ratchet: held")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
