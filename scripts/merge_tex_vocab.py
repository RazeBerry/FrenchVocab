#!/usr/bin/env python3
"""
merge_tex_vocab.py — Merge two LaTeX vocabulary lists without duplicates
and spit them back *alphabetically*.

Changes vs. v1
--------------
* _split_tex():  now grabs **the first itemize that carries the
                 ‘leftmargin’ option**, so it skips the one hidden
                 inside the \entry definition.
* _deduplicate(): after removing duplicates, it sorts the blocks
                  case‑ & accent‑insensitively before returning them.
"""
from __future__ import annotations
import argparse
import datetime as _dt
import pathlib as _pl
import re
import sys
import unicodedata as _ud

# ----------------------------------------------------------------------
# Regexes
# ----------------------------------------------------------------------
# The vocabulary list we want always starts with \begin{itemize}[leftmargin=
_OUTER_ITEMIZE_RE = re.compile(
    r"\\begin{itemize}\[[^\]]*leftmargin[^\]]*\]", re.IGNORECASE
)
_ENTRY_RE = re.compile(
    r"""
    \\entry
    \{(?P<word>[^{}]+?)\}
    \s*\{[^{}]*?\}
    \s*\{[^{}]*?\}
    \s*\{[^{}]*?\}
    """,
    re.DOTALL | re.VERBOSE,
)

# ----------------------------------------------------------------------
def _strip_accents(text: str) -> str:
    return "".join(ch for ch in _ud.normalize("NFKD", text) if not _ud.combining(ch))

def _key(word: str) -> str:
    return _strip_accents(word).casefold()

def _split_tex(tex: str) -> tuple[str, str, str]:
    """Return (preamble, body‑inside‑itemize, postamble)."""
    m = _OUTER_ITEMIZE_RE.search(tex)
    if not m:
        raise ValueError("Could not find the main \\begin{itemize}[leftmargin=*] block.")
    start = m.start()
    end = tex.find(r"\end{itemize}", m.end())
    if end == -1:
        raise ValueError("Missing \\end{itemize} matching the vocabulary block.")
    end += len(r"\end{itemize}")
    return tex[:start], tex[start:end], tex[end:]

def _extract_entries(body: str) -> list[str]:
    return [m.group(0) for m in _ENTRY_RE.finditer(body)]

def _deduplicate_and_sort(entries: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for block in entries:
        word = _ENTRY_RE.match(block).group("word")  # type: ignore[arg-type]
        k = _key(word)
        if k not in seen:
            seen[k] = block
    # Sort by the same normalization so É and E sit together, etc.
    return [seen[k] for k in sorted(seen, key=lambda k: _key(k))]

def _unique_output_path(path: _pl.Path) -> _pl.Path:
    stem = f"{path.stem}_merged_{_dt.datetime.now():%Y%m%d_%H%M%S_%f}"
    candidate = path.with_stem(stem)
    counter = 1
    while candidate.exists():
        candidate = path.with_stem(f"{stem}_{counter}")
        counter += 1
    return candidate

def _merge(path1: _pl.Path, path2: _pl.Path) -> _pl.Path:
    tex1, tex2 = path1.read_text(), path2.read_text()
    pre1, body1, post1 = _split_tex(tex1)
    _,   body2, _      = _split_tex(tex2)

    merged_entries = _deduplicate_and_sort(
        _extract_entries(body1) + _extract_entries(body2)
    )

    # Re‑use the outer \begin{itemize[… line from file #1
    header_line = _OUTER_ITEMIZE_RE.search(body1).group(0)  # type: ignore[union-attr]
    body = "\n".join(
        [header_line, *merged_entries, r"\end{itemize}", ""]
    )

    out = _unique_output_path(path1)
    with out.open("x", encoding="utf-8") as handle:
        handle.write(pre1 + body + post1)
    return out

# ----------------------------------------------------------------------
def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Merge two LaTeX vocab files uniquely.")
    p.add_argument("file1", type=_pl.Path)
    p.add_argument("file2", type=_pl.Path)
    args = p.parse_args(argv)
    try:
        dst = _merge(args.file1, args.file2)
        print(f"[SUCCESS] Merged file written to: {dst}")
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
