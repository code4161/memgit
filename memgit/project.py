"""Project labels — deriving them from paths and matching them hierarchically.

A project label is the munged path of a workspace relative to the user's home,
using the SAME munging Claude Code applies to its `~/.claude/projects/` dir
names: every character outside [A-Za-z0-9_-] becomes '-', with no run
collapsing. Two label sources must agree byte-for-byte or scoping silently
breaks: labels derived from the cwd at recall time (resume, search boost,
MCP save) and labels derived from munged projects/ dir names at sync time.

    /Users/hari/Freelance/BITS            → 'Freelance-BITS'
    /Users/hari/Freelance/BITS/bits_back  → 'Freelance-BITS-bits_back'
    /Users/hari/Personal business         → 'Personal-business'
    /Users/hari/.claude-mem/sessions      → '-claude-mem-sessions'
"""

from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Optional

# Claude Code keeps [A-Za-z0-9_-] and turns everything else into '-',
# one dash per character (runs are NOT collapsed: '/.x' → '--x').
_MUNGE_RE = re.compile(r'[^A-Za-z0-9_-]')

#: Quarantine label for a save whose project could not be determined.
#: A memory with project=None is EXPLICITLY GLOBAL (applies everywhere) —
#: unknown provenance must never silently become global, so it gets this
#: label instead. `_unknown` family-matches NOTHING (not even itself), which
#: keeps quarantined memories out of every cross-project surface until an
#: operator relabels them (`memgit doctor --relabel`).
UNKNOWN_PROJECT = '_unknown'


def munge(text: str) -> str:
    """Munge a path string exactly the way Claude Code munges project dirs."""
    return _MUNGE_RE.sub('-', text)


def project_label_from_path(path: Path) -> Optional[str]:
    """Derive a project label from a filesystem path (home prefix stripped)."""
    try:
        resolved = path.expanduser().resolve()
        home = Path.home().resolve()
    except OSError:
        return None
    if resolved == home:
        return None
    munged = munge(str(resolved))
    home_munged = munge(str(home))
    if munged.startswith(home_munged + '-'):
        return munged[len(home_munged) + 1:] or None
    return munged.lstrip('-') or None


def project_label_from_munged(munged_name: str) -> Optional[str]:
    """Derive a project label from a Claude Code projects/ dir name.

    '-Users-hari-Freelance-BITS' → 'Freelance-BITS' (munged home stripped).
    """
    home_munged = munge(str(Path.home()))
    if munged_name.startswith(home_munged + '-'):
        label = munged_name[len(home_munged) + 1:]
    else:
        label = munged_name.lstrip('-')
    return label or None


def same_project_family(a: Optional[str], b: Optional[str]) -> bool:
    """True when two labels refer to the same project tree.

    Exact match, or one label is a path-ancestor of the other at a '-'
    boundary — so a session in BITS/bits_back still counts BITS memories
    as its own, and vice versa. Labels are munged paths, so the '-'
    boundary is the only separator available; a sibling like
    'Freelance-BITS2' does not match 'Freelance-BITS'.

    The quarantine label `_unknown` never matches — including itself: two
    memories of unknown provenance share nothing but the failure to detect,
    and treating that as kinship would let quarantined content cluster into
    a phantom project.
    """
    if not a or not b:
        return False
    if a == UNKNOWN_PROJECT or b == UNKNOWN_PROJECT:
        return False
    if a == b:
        return True
    return a.startswith(b + '-') or b.startswith(a + '-')


def project_affinity(memory_project: Optional[str],
                     current: Optional[str]) -> int:
    """Rank how strongly a memory belongs to the current workspace.

    2 = exact project match, 1 = same family (ancestor/descendant), 0 = other.
    Global memories (no project) score 0 — they are never *penalized*,
    callers keep them visible; this only orders in-project content first.
    The `_unknown` quarantine label scores 0 against everything, itself
    included — unknown provenance is not affinity.
    """
    if not memory_project or not current:
        return 0
    if UNKNOWN_PROJECT in (memory_project, current):
        return 0
    if memory_project == current:
        return 2
    if same_project_family(memory_project, current):
        return 1
    return 0


def detect_project(cwd: Optional[Path] = None) -> Optional[str]:
    """Derive the current project label — the ONE detection path for every
    surface (MCP server, CLI, hooks), so a label derived at save time and a
    label derived at recall time can never disagree.

    Precedence (explicit caller values are checked BEFORE calling this):
      1. MEMGIT_PROJECT env — a forced label, taken verbatim
      2. `cwd` argument — the hook payload's cwd (hosts report the real
         workspace there even when the process cwd is elsewhere)
      3. CLAUDE_PROJECT_DIR env — set by Claude Code for hook processes
      4. Path.cwd() — the process working directory

    Returns None when nothing yields a label (e.g. running from $HOME) —
    callers on WRITE paths must then quarantine with UNKNOWN_PROJECT, never
    silently store a global memory.
    """
    env = os.environ.get('MEMGIT_PROJECT', '').strip()
    if env:
        return env
    if cwd is not None:
        label = project_label_from_path(Path(cwd))
        if label:
            return label
    claude_dir = os.environ.get('CLAUDE_PROJECT_DIR', '').strip()
    if claude_dir:
        label = project_label_from_path(Path(claude_dir))
        if label:
            return label
    try:
        return project_label_from_path(Path.cwd())
    except OSError:
        return None


def scope_filter(mnemonics, project: Optional[str]) -> list:
    """Filter memories to what `project` may see: its own family plus
    explicitly-global (project=None) memories.

    This is the filter-by-default recall boundary: another project's scoped
    memories never appear, and `_unknown` quarantined memories are excluded
    automatically (they family-match nothing). With no project context the
    pool is returned unchanged — there is no boundary to enforce.
    """
    if not project:
        return list(mnemonics)
    return [m for m in mnemonics
            if m.project is None or same_project_family(m.project, project)]
