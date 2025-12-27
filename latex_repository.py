from __future__ import annotations

from pathlib import Path
from typing import List, Tuple, Optional

from models import WordEntry


def parse_balanced_group(s: str, start: int) -> Tuple[str, int]:
    """Parse a single {...} group starting at index `start` (which should point to '{').

    Returns (content_without_outer_braces, next_index_after_group).
    Raises ValueError if malformed.

    This is a module-level function for reuse across LaTeX parsing operations.
    """
    if start >= len(s) or s[start] != '{':
        raise ValueError("Group must start with '{'")
    depth = 0
    i = start
    out: List[str] = []
    while i < len(s):
        ch = s[i]
        if ch == '{':
            depth += 1
            # don't include outermost braces in out
            if depth > 1:
                out.append(ch)
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return (''.join(out), i + 1)
            out.append(ch)
        else:
            out.append(ch)
        i += 1
    raise ValueError("Unbalanced braces while parsing group")


def parse_entry_groups(s: str, start: int, num_groups: int = 4) -> Optional[Tuple[List[str], int, int]]:
    """Parse an entry command's brace groups starting at index `start`.

    Expects `start` to point to the first '{' of the groups (after the command name).
    Returns (list_of_group_contents, entry_start_index, next_index) or None if parsing fails.

    The entry_start_index is passed through for convenience (set to start).
    """
    i = start
    groups: List[str] = []
    n = len(s)
    for _ in range(num_groups):
        # skip whitespace
        while i < n and s[i].isspace():
            i += 1
        if i >= n or s[i] != '{':
            return None
        try:
            content, i = parse_balanced_group(s, i)
            groups.append(content)
        except ValueError:
            return None
    return (groups, start, i)


def find_entry_bounds(content: str, entry_cmd: str, word: str) -> Optional[Tuple[int, int]]:
    """Find the start and end indices of an entry with the given word.

    Returns (start_index, end_index) where content[start:end] is the full entry,
    or None if not found.
    """
    i = 0
    n = len(content)
    word_lower = word.lower().strip()
    while i < n:
        j = content.find(entry_cmd, i)
        if j == -1:
            break
        entry_start = j
        i = j + len(entry_cmd)
        # skip whitespace to first brace
        while i < n and content[i].isspace():
            i += 1
        if i >= n or content[i] != '{':
            continue
        result = parse_entry_groups(content, i, num_groups=4)
        if result is None:
            continue
        groups, _, entry_end = result
        entry_word = groups[0].strip().lower()
        if entry_word == word_lower:
            return (entry_start, entry_end)
        i = entry_end
    return None


def parse_all_entries(content: str, entry_cmd: str) -> List[Tuple[List[str], int, int]]:
    """Parse all entries in content, returning list of (groups, start, end) tuples.

    Each tuple contains:
    - groups: [word, type, definitions_block, examples_block]
    - start: index of the entry command start
    - end: index immediately after the last brace
    """
    entries: List[Tuple[List[str], int, int]] = []
    i = 0
    n = len(content)
    while i < n:
        j = content.find(entry_cmd, i)
        if j == -1:
            break
        entry_start = j
        i = j + len(entry_cmd)
        # skip whitespace to first brace
        while i < n and content[i].isspace():
            i += 1
        if i >= n or content[i] != '{':
            continue
        result = parse_entry_groups(content, i, num_groups=4)
        if result is None:
            continue
        groups, _, entry_end = result
        entries.append((groups, entry_start, entry_end))
        i = entry_end
    return entries


class LatexRepository:
    """Read-only LaTeX repository with robust entry parsing.

    For now, this class focuses on loading entries with a balanced-brace parser.
    Write/update operations can be added incrementally to replace regex usage.
    """

    def __init__(self, latex_file: Path, entry_command: str = "\\entry"):
        self.latex_file = Path(latex_file)
        if not entry_command.startswith("\\"):
            entry_command = f"\\{entry_command}"
        self.entry_command = entry_command
        self._entry_command_len = len(entry_command)

    def _parse_balanced_group(self, s: str, start: int) -> Tuple[str, int]:
        """Parse a single {...} group starting at index `start` (which should point to '{').
        Returns (content_without_outer_braces, next_index_after_group).
        Raises ValueError if malformed.

        Delegates to the module-level parse_balanced_group function.
        """
        return parse_balanced_group(s, start)

    def _parse_entry_at(self, s: str, start: int) -> Optional[Tuple[WordEntry, int]]:
        r"""Parse an entry command \entry{...}{...}{...}{...} starting at index `start`.
        Returns (WordEntry, next_index) or None if not a valid entry.
        """
        cmd = self.entry_command
        if not s.startswith(cmd, start):
            return None
        i = start + self._entry_command_len
        groups: List[str] = []
        # Expect exactly four groups
        for _ in range(4):
            # skip whitespace
            while i < len(s) and s[i].isspace():
                i += 1
            if i >= len(s) or s[i] != '{':
                return None
            content, i = self._parse_balanced_group(s, i)
            groups.append(content)
        try:
            word_raw = groups[0].strip()
            type_raw = groups[1].strip().strip("'\"")
            # third group is an itemize block with \item lines
            defs_block = groups[2]
            exs_block = groups[3]
            definitions = [line.strip() for line in defs_block.split('\n')
                           if line.strip().startswith('\\item')]
            # strip the leading \item and any extra spaces
            definitions = [d[len('\\item'):].strip() for d in definitions]
            # examples as list of (fr, en) — same structure we generate
            examples: List[Tuple[str, str]] = []
            for line in exs_block.split('\n'):
                ls = line.strip()
                if not ls.startswith('\\item'):
                    continue
                payload = ls[len('\\item'):].strip()
                # Expect "FR \\ (EN)" — split on \\
                if '\\\\' in payload:
                    fr, rest = payload.split('\\\\', 1)
                    fr = fr.strip()
                    en = rest.strip()
                    # unwrap optional parentheses
                    if en.startswith('(') and en.endswith(')'):
                        en = en[1:-1]
                    examples.append((fr, en))
                else:
                    # Fallback: store the entire payload as FR, empty EN
                    examples.append((payload, ''))

            entry = WordEntry(
                word=word_raw.strip(),
                type=type_raw,
                definitions=[d for d in definitions if d],
                examples=examples,
            )
            return entry, i
        except Exception:
            return None

    def load_entries(self) -> List[WordEntry]:
        if not self.latex_file.exists():
            return []
        content = self.latex_file.read_text(encoding='utf-8')
        entries: List[WordEntry] = []
        i = 0
        n = len(content)
        while i < n:
            j = content.find(self.entry_command, i)
            if j == -1:
                break
            parsed = self._parse_entry_at(content, j)
            if parsed is None:
                i = j + self._entry_command_len
                continue
            entry, next_i = parsed
            entries.append(entry)
            i = next_i
        return entries
