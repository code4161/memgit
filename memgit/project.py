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
from typing import Iterable, Optional

# Claude Code keeps [A-Za-z0-9-] and turns everything else into a dash, one
# dash per character (runs are NOT collapsed, so '/.x' becomes '--x').
# The _ character is NOT kept. This regex used to keep it, which broke the
# byte-for-byte agreement the module docstring promises: ~/Freelance/logistics_crm
# derived as Freelance-logistics_crm from the path and Freelance-logistics-crm
# from the projects dir name, and a live store held 24 memories under one and 1
# under the other. Measured 2026-09-20: zero of the ~2,000 directories in
# ~/.claude/projects/ contain a _ character.
_MUNGE_RE = re.compile(r'[^A-Za-z0-9-]')

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


def normalize_label(label: Optional[str]) -> Optional[str]:
    """The form two labels are COMPARED in, never the form they are stored in.

    Labels written before the munge fix keep the _ character, and a memory
    synced from a machine still running an older memgit keeps it too. Comparing
    the raw strings would strand every one of them the moment detection starts
    returning the dash form: on the store this was measured against, 268
    memories across three projects would have gone dark between the fix and the
    relabel that follows it.

    So comparison folds the two forms together and storage is left alone. That
    ordering is what makes the fix safe to land on its own, and it keeps
    working afterwards for anything arriving from an older writer.

    The quarantine label is returned untouched. It carries a _ by design and
    must never fold onto a real label.
    """
    if not label or label == UNKNOWN_PROJECT:
        return label
    return label.replace('_', '-')


def project_label_from_path(path: Path,
                            home: Optional[Path] = None) -> Optional[str]:
    """Derive a project label from a filesystem path (home prefix stripped).

    `home` defaults to the real home directory, which is what every caller in
    the product wants. It is a parameter so a caller working against a
    different root derives labels through THIS function rather than writing a
    second copy of the munging. A second copy is how the label derivations
    drifted apart in the first place.
    """
    try:
        resolved = path.expanduser().resolve()
        home = (home or Path.home()).expanduser().resolve()
    except OSError:
        return None
    if resolved == home:
        return None
    munged = munge(str(resolved))
    home_munged = munge(str(home))
    if munged.startswith(home_munged + '-'):
        return munged[len(home_munged) + 1:] or None
    return munged.lstrip('-') or None


# ── Repository identity ──────────────────────────────────────────────────────
#
# A label is a path, so it names a CHECKOUT, not a project. Measured 2026-11-12
# on 0.15.0 against a local cloud API: a teammate whose clone sat at
# ~/work/acme-api, the same user's second machine at ~/src/api and a server at
# /srv/acme-api all held the synced memories saved from ~/code/acme-api, and
# every default search on all three answered "No results" and told the agent to
# bootstrap the project from scratch. Sync worked; scoping hid what it delivered.
#
# The repository's remote URL is the same on every clone, so it is what joins
# those labels. The identity is the remote plus the path inside the checkout
# (github.com/acme/api, github.com/acme/api/src): a monorepo's sibling folders
# stay separate projects, as their labels always were, and a home directory
# that is itself a dotfiles repository does not fold every project under it
# into one. Identities match the way labels do, exactly or as an ancestor.
# Each save inside a git repo records it on the memory as the REPO field (kept in Mnemonic.extra, which every memgit since 0.11 carries
# through unchanged, so older readers never strip it). Labels are then the same
# project when any memory under them names the same repository. A label learns
# its repository from ANY one of its memories, so an existing project joins up
# on its next save from inside the checkout; no relabel, no rewrite.

REPO_FIELD = 'REPO'

#: label (normalized) -> repository ids, learned from the store's memories.
_learned_repos: dict[str, set] = {}
#: label (normalized) -> repository ids, seen by detection in this process.
_detected_repos: dict[str, set] = {}


def _git_dir(start: Path) -> Optional[tuple]:
    """(git directory holding the config, checkout root, start resolved) for
    the checkout containing start, or None."""
    try:
        current = start.expanduser().resolve()
    except OSError:
        return None
    for d in [current, *current.parents]:
        dot = d / '.git'
        try:
            if dot.is_dir():
                return dot, d, current
            if dot.is_file():   # worktree or submodule: "gitdir: <path>"
                text = dot.read_text(errors='replace').strip()
                if text.startswith('gitdir:'):
                    gd = Path(text[7:].strip())
                    gd = gd if gd.is_absolute() else (d / gd)
                    common = gd / 'commondir'
                    if common.is_file():
                        c = Path(common.read_text().strip())
                        return (c if c.is_absolute() else gd / c).resolve(), d, current
                    return gd.resolve(), d, current
                return None
        except OSError:
            return None
    return None


def normalize_remote(url: Optional[str]) -> Optional[str]:
    """host/owner/name for a git remote URL, the same for every way of cloning it.

        git@github.com:Acme/API.git          -> github.com/acme/api
        https://user@github.com/acme/api     -> github.com/acme/api
        ssh://git@github.com:22/acme/api.git -> github.com/acme/api

    A local path or file:// remote names a directory, not a shared repository,
    so it gives no identity (None).
    """
    if not url:
        return None
    u = url.strip()
    if not u or u.startswith(('/', '.', '~', 'file:')):
        return None
    m = re.match(r'^[a-z][a-z0-9+.-]*://(?:[^@/]*@)?([^/:]+)(?::\d+)?/(.+)$', u, re.I)
    if m:
        host, path = m.group(1), m.group(2)
    else:
        m = re.match(r'^(?:[^@/]+@)?([^:/]+):(.+)$', u)   # scp form git@host:path
        if not m or len(m.group(1)) == 1:                 # C:\path is not a host
            return None
        host, path = m.group(1), m.group(2)
    path = path.strip('/')
    if path.endswith('.git'):
        path = path[:-4]
    path = path.strip('/')
    if not path:
        return None
    return f'{host}/{path}'.lower()


def repo_identity(path: Optional[Path]) -> Optional[str]:
    """Identity of path within its git repository: the origin remote (else the
    first remote), normalized, plus the path inside the checkout. None outside
    a repository or without a remote. Reads .git/config directly: this runs on
    every recall, and a git subprocess there would cost more than the search."""
    if path is None:
        return None
    found = _git_dir(Path(path))
    if found is None:
        return None
    gd, top, here = found
    try:
        text = (gd / 'config').read_text(errors='replace')
    except OSError:
        return None
    remotes: dict[str, str] = {}
    section = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('['):
            m = re.match(r'\[remote\s+"([^"]+)"\]', s)
            section = m.group(1) if m else None
        elif section and '=' in s:
            k, v = s.split('=', 1)
            if k.strip().lower() == 'url' and section not in remotes:
                remotes[section] = v.strip()
    for name in (['origin'] + [r for r in remotes if r != 'origin']):
        ident = normalize_remote(remotes.get(name))
        if ident:
            try:
                rel = here.relative_to(top).as_posix()
            except ValueError:
                rel = '.'
            return ident if rel in ('', '.') else f'{ident}/{rel}'
    return None


def note_repo(label: Optional[str], repo: Optional[str]) -> None:
    """Record that detection found `label` inside repository `repo`."""
    if label and repo and label != UNKNOWN_PROJECT:
        _detected_repos.setdefault(normalize_label(label), set()).add(repo)


def learn_repos(mnemonics) -> None:
    """Rebuild label -> repository identities from a store's memories."""
    learned: dict[str, set] = {}
    for m in mnemonics:
        repo = (getattr(m, 'extra', None) or {}).get(REPO_FIELD)
        if repo and m.project and m.project != UNKNOWN_PROJECT:
            learned.setdefault(normalize_label(m.project), set()).add(repo)
    _learned_repos.clear()
    _learned_repos.update(learned)


def learn_label_repos(pairs) -> None:
    """Add (label, repository) pairs to the learned map, for a caller that holds
    cached rows rather than the store's memories (the action gate)."""
    for label, repo in pairs:
        if label and repo and label != UNKNOWN_PROJECT:
            _learned_repos.setdefault(normalize_label(label), set()).add(repo)


def repos_of(label: Optional[str]) -> set:
    if not label or label == UNKNOWN_PROJECT:
        return set()
    key = normalize_label(label)
    return _learned_repos.get(key, set()) | _detected_repos.get(key, set())


def stamp_repo(m) -> None:
    """Record the repository on a memory being saved, when its label was
    detected inside exactly one repository. Explicit other-project saves and
    globals are left alone: only the checkout we are standing in is known."""
    if not m.project or m.project == UNKNOWN_PROJECT:
        return
    if (m.extra or {}).get(REPO_FIELD):
        return
    repos = _detected_repos.get(normalize_label(m.project), set())
    if len(repos) == 1:
        m.extra = dict(m.extra or {})
        m.extra[REPO_FIELD] = next(iter(repos))


def repo_relation(a: Optional[str], b: Optional[str]) -> int:
    """2 when two labels are the same place in the same repository (different
    checkouts of it), 1 when one is a folder inside the other, else 0."""
    ra, rb = repos_of(a), repos_of(b)
    if not ra or not rb:
        return 0
    if ra & rb:
        return 2
    for x in ra:
        for y in rb:
            if x.startswith(y + '/') or y.startswith(x + '/'):
                return 1
    return 0


def same_repository(a: Optional[str], b: Optional[str]) -> bool:
    """True when two labels are the same place in the same repository."""
    return repo_relation(a, b) == 2


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
    na, nb = normalize_label(a), normalize_label(b)
    if na == nb:
        return True
    if na.startswith(nb + '-') or nb.startswith(na + '-'):
        return True
    return repo_relation(a, b) >= 1


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
    if normalize_label(memory_project) == normalize_label(current):
        return 2
    if same_repository(memory_project, current):
        return 2   # the same repository in another checkout is this project
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
    candidates = []
    if cwd is not None:
        candidates.append(Path(cwd))
    claude_dir = os.environ.get('CLAUDE_PROJECT_DIR', '').strip()
    if claude_dir:
        candidates.append(Path(claude_dir))
    try:
        candidates.append(Path.cwd())
    except OSError:
        pass
    for path in candidates:
        label = project_label_from_path(path)
        if label:
            # The checkout's repository joins this label to every other clone
            # of it (see "Repository identity" above). A forced MEMGIT_PROJECT
            # is not tied to the cwd's repository, so only derived labels are.
            note_repo(label, repo_identity(path))
            return label
    return None


def canonical_project(label: Optional[str], known) -> Optional[str]:
    """Fold a free-text project label onto an existing one when it clearly means it.

    The MCP/HTTP save tools take `project` as a free string, and agents supply
    the short name they have in their head ('log-report') rather than the
    munged workspace label ('Downloads-log-report'). Filter-by-default scoping
    then treats the two as unrelated stores, and memories written under the
    short name become invisible from the real workspace. Measured on a live
    store: six projects had split into two labels each, hiding 68 memories.

    `known` is either a mapping {label: memory_count} or a plain iterable of
    labels (treated as count 1 each). Counts matter: a label that ALREADY has
    memories is an established project and is never folded away, whichever
    direction the containment runs. That is what makes this safe in both real
    cases seen on the live store —

        'log-report'(0 memories) + {'Downloads-log-report': 850}
            -> 'Downloads-log-report'          (the split is healed)
        'FittyMe'(90 memories)   + {'Freelance-FittyMe': 1, 'FittyMe': 90}
            -> 'FittyMe'                       (established; left alone)

    — where a rule that always folded onto the longer label would have moved
    90 memories onto the label holding 1.

    Folding is otherwise conservative: the input must be a trailing '-'-segment
    of EXACTLY ONE known label. Ambiguity leaves it untouched, because guessing
    wrong files a memory under the wrong project, which is worse than a new
    label. An exact match, a fully unknown label, and `_unknown` pass through.
    Every fold is reported to the caller as a warning — it is never silent.
    """
    if not label or label == UNKNOWN_PROJECT:
        return label
    if isinstance(known, dict):
        counts = {k: v for k, v in known.items()
                  if k and k != UNKNOWN_PROJECT}
    else:
        counts = {k: 1 for k in known if k and k != UNKNOWN_PROJECT}
    # An established label is authoritative — never fold it onto a sibling.
    if counts.get(label):
        return label
    matches = [k for k in counts if k.endswith('-' + label) and counts[k]]
    if len(matches) == 1:
        return matches[0]
    return label


def known_projects(mnemonics) -> dict:
    """{project label: memory count} for the store (quarantine excluded)."""
    counts: dict = {}
    for m in mnemonics:
        p = m.project
        if p and p != UNKNOWN_PROJECT:
            counts[p] = counts.get(p, 0) + 1
    return counts


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
