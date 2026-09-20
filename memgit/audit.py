"""Store audit: the end-to-end health read behind memgit doctor --audit.

doctor answers four narrow questions (quarantine, globals, stale caches, orphan
usage entries). It cannot see the failure that actually costs recall: a project
whose memories have SPLIT across two labels, so half the store is invisible from
the workspace that owns it. A split reports no error anywhere. Every save
succeeds, fsck stays clean, and the only symptom is an answer that is missing
things.

Four split mechanisms are detected here, each measured on the live store before
being written down:

  * the directory MOVED, so new saves land on a new label and the old ones are
    stranded (1,819 memories on a path that no longer exists);
  * a label was typed by hand and misspelled (75 memories on a transposition);
  * a short label was used where the workspace label was meant, which
    canonical_project only heals while the short one has no memories of its
    own (98 against 234);
  * the two label derivations DISAGREE. project_label_from_path keeps the
    _ character; Claude Code rewrites it as a dash, so
    project_label_from_munged returns a different label for the same
    directory. project.py's own docstring asserts these agree byte for byte.

Reads only. Nothing here writes to the store.
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from .project import (UNKNOWN_PROJECT, munge, project_label_from_path,
                      same_project_family)

#: How deep to walk below home looking for workspace directories. Three levels
#: reaches a component inside a project inside a client folder, which is the
#: deepest real workspace on the machine this was measured against.
SCAN_DEPTH = 3

#: Directories that never hold a workspace and cost the most to walk.
SKIP_DIRS = frozenset({
    'Library', 'node_modules', 'Applications', 'Movies', 'Music', 'Pictures',
    'Public', 'venv', '.venv', '__pycache__', 'dist', 'build', 'target',
})


def _iter_workspace_dirs(home: Path, depth: int = SCAN_DEPTH):
    """Yield candidate workspace directories below home.

    Hidden directories are skipped: a label derived from one is a tool's own
    state directory, never a workspace someone works in.
    """
    for root, dirs, _files in os.walk(home):
        here = Path(root)
        try:
            level = len(here.relative_to(home).parts)
        except ValueError:
            dirs[:] = []
            continue
        if level >= depth:
            dirs[:] = []
        else:
            dirs[:] = [d for d in dirs
                       if not d.startswith('.') and d not in SKIP_DIRS]
        if level:
            yield here


def live_labels(home: Optional[Path] = None, depth: int = SCAN_DEPTH) -> dict:
    """{label: path} for every directory below home that could be a workspace."""
    home = home or Path.home()
    out: dict = {}
    for d in _iter_workspace_dirs(home, depth):
        label = project_label_from_path(d, home)
        if label and label not in out:
            out[label] = str(d)
    return out


def _edit_distance(a: str, b: str, cap: int = 2) -> int:
    """Levenshtein distance, giving up once it passes cap.

    Bounded because the only question asked of it is "is this a typo of that",
    and an unbounded distance over 45 labels squared is wasted work.
    """
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def _dash_form(label: str) -> str:
    """The label Claude Code would produce for the same path.

    Claude Code keeps only letters, digits and dashes, so it rewrites the
    _ character that project_label_from_path preserves.
    """
    return label.replace('_', '-')


def label_splits(counts: dict, live: Optional[dict] = None) -> list:
    """Label pairs that name one project and hold two separate stores.

    counts is {label: memory count}, live the {label: path} of directories
    that exist. Each result carries the mechanism, so a repair can be
    mechanical rather than a judgement.

    Which label survives is decided by the DIRECTORY, not by the memory count.
    The count is the wrong signal and the live store shows why three times
    over: the dead label Downloads-log-report holds 1,819 memories against 18
    on the live one, and the misspelled masagrti-Networking-pro holds 75
    against 18. Healing toward the bigger pile would keep the label no session
    will ever run under and strand the work a second time. The count breaks
    ties only when both labels are live, or neither is.

    Family pairs are NOT splits. A label and its own sub-path already see each
    other through same_project_family, so reporting them would bury the real
    findings under every component of every project.
    """
    live = live or {}
    labels = [l for l in counts if l and l != UNKNOWN_PROJECT]
    seen: set = set()
    out: list = []
    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            # The munge check runs BEFORE the family skip. Comparison folds the
            # two forms together, so a munge pair is family and no longer costs
            # recall, but it is still two labels in the store and a repair
            # should still collapse it. It reports with costs_recall False.
            kind = None
            if _dash_form(a) == _dash_form(b) and a != b:
                kind = 'munge'
            elif same_project_family(a, b):
                continue
            elif a.lower() == b.lower():
                kind = 'case'
            elif a.endswith('-' + b) or b.endswith('-' + a):
                kind = 'short-label'
            elif _edit_distance(a.lower(), b.lower()) <= 2:
                kind = 'typo'
            if not kind:
                continue
            pair = tuple(sorted((a, b)))
            if pair in seen:
                continue
            seen.add(pair)
            keep = _survivor(a, b, kind, counts, live)
            drop = b if keep == a else a
            out.append({
                'kind': kind,
                'keep': keep,
                'drop': drop,
                'keep_count': counts.get(keep, 0),
                'drop_count': counts.get(drop, 0),
                'keep_is_live': keep in live,
                'costs_recall': kind != 'munge',
            })
    out.sort(key=lambda r: -r['drop_count'])
    return out


def _survivor(a: str, b: str, kind: str, counts: dict, live: dict) -> str:
    """Which of two split labels the memories should be healed onto.

    A munge disagreement is decided by the format, not by the filesystem: only
    the dash form is reachable from both label derivations, so it wins even
    when its directory carries the _ character.
    """
    if kind == 'munge':
        return a if '_' not in a else b
    a_live, b_live = a in live, b in live
    if a_live != b_live:
        return a if a_live else b
    return a if counts.get(a, 0) >= counts.get(b, 0) else b


def _trailing_containment(a: str, b: str) -> bool:
    """True when one label is exactly a trailing segment run of the other.

    This is the relation a move or a short label produces: FittyMe against
    Freelance-FittyMe, log-report against Downloads-log-report. Matching on
    the last segment alone is far too loose and the live store proves it.
    Freelance-logistics-crm and Freelance-FittyMe-fittyme-crm share the
    segment crm and are two different clients.
    """
    return a == b or a.endswith('-' + b) or b.endswith('-' + a)


def stranded_labels(counts: dict, live: dict) -> list:
    """Labels with memories but no directory, and where the work went.

    A label whose directory is gone is where a project's history goes to die:
    every new save lands on the label of wherever the work moved to, and
    nothing points back. successor names the live label that most likely
    owns the work now, and is None when no single candidate stands out,
    because guessing files a memory under the wrong project.

    A candidate has to clear two bars. It must be a trailing segment run of the
    stranded label or contain one, and it must already HOLD memories, because a
    successor is where the work continued and a directory nobody has saved
    against is not that. The second bar is what keeps a dated recovery copy of
    an archived project from being named the successor of the original.

    What survives both is then ranked by how deep the directory sits below
    home, and the shallowest unique one wins. A project that moved sits at the
    top of the tree; copies of it inside a recovery folder carry the same name
    one level down. The live store holds three copies of log-report, so without
    the depth rank the largest split in the store reports no successor at all.
    """
    out: list = []
    for label, n in counts.items():
        if not label or label == UNKNOWN_PROJECT or label in live:
            continue
        cands = [l for l in live
                 if l != label and counts.get(l, 0) > 0
                 and _trailing_containment(label, l)]
        ranked = sorted(cands, key=lambda l: (str(live[l]).count(os.sep), l))
        successor = None
        if len(ranked) == 1:
            successor = ranked[0]
        elif len(ranked) > 1:
            top = str(live[ranked[0]]).count(os.sep)
            if str(live[ranked[1]]).count(os.sep) > top:
                successor = ranked[0]
        out.append({
            'label': label,
            'count': n,
            'successor': successor,
            'candidates': ranked,
        })
    out.sort(key=lambda r: -r['count'])
    return out


def home_labels(counts: dict, home: Optional[Path] = None) -> list:
    """Labels that are the munged home path itself.

    Home is not a project. project_label_from_path returns None for home
    exactly, but a label can still reach the store from another machine, from
    an explicit project argument, or from a path that resolved differently.
    Such a memory is a machine-level fact filed under a project no session ever
    runs in, so it surfaces nowhere. It belongs in global scope.
    """
    home = home or Path.home()
    munged = munge(str(home)).lstrip('-')
    return [{'label': l, 'count': n} for l, n in counts.items()
            if l and l == munged]


def dangling_links(mnemonics: Iterable) -> dict:
    """Supersedes and related edges pointing at slugs that do not exist.

    A dangling supersedes is the worse half: the chain resolver cannot tell
    that this memory retired something, so a reader cannot tell which claim
    won.
    """
    mems = list(mnemonics)
    known = {m.slug for m in mems}
    sup = [{'from': m.slug, 'to': s} for m in mems
           for s in (m.supersedes or []) if s not in known]
    rel = [{'from': m.slug, 'to': s} for m in mems
           for s in (m.related or []) if s not in known]
    return {'supersedes': sup, 'related': rel}


def save_rate(mnemonics: Iterable, now: Optional[datetime] = None) -> dict:
    """Throughput and landing quality.

    landing_rate is the share of saves that reached a real project scope.
    Quarantined saves did not, and neither did saves on a stranded or home
    label, so all three are counted against it. A raw quarantine count hides
    the splits, which are the larger loss.
    """
    mems = list(mnemonics)
    now = now or datetime.now(timezone.utc)
    by_day = Counter(m.timestamp.strftime('%Y-%m-%d') for m in mems)
    by_month = Counter(m.timestamp.strftime('%Y-%m') for m in mems)
    cutoff = now - timedelta(days=30)
    recent = [m for m in mems if m.timestamp >= cutoff]
    return {
        'total': len(mems),
        'by_day': dict(sorted(by_day.items())),
        'by_month': dict(sorted(by_month.items())),
        'last_30d': len(recent),
        'per_day_30d': round(len(recent) / 30.0, 1),
        'by_project_30d': dict(Counter(m.project or '(global)'
                                       for m in recent).most_common()),
    }


def audit(repo, home: Optional[Path] = None, depth: int = SCAN_DEPTH) -> dict:
    """The whole health read. Reads the store, writes nothing."""
    home = home or Path.home()
    mems = repo.list()
    counts = Counter(m.project for m in mems if m.project)
    live = live_labels(home, depth)

    splits = label_splits(counts, live)
    stranded = stranded_labels(counts, live)
    homed = home_labels(counts, home)
    dangling = dangling_links(mems)
    quarantined = [m.slug for m in mems if m.project == UNKNOWN_PROJECT]

    # Three ways a save misses its scope, reported separately because they have
    # different fixes and different severity. Collapsing them into one
    # percentage hides that almost all of it is one relabel away, and reads as
    # if half the store were unrecoverable.
    split_drops = {r['drop'] for r in splits if r['costs_recall']}
    stranded_set = {r['label'] for r in stranded}
    home_set = {r['label'] for r in homed}
    by_cause = {'quarantined': set(quarantined), 'split': set(), 'stranded': set()}
    for m in mems:
        if m.project in split_drops:
            by_cause['split'].add(m.slug)
        elif m.project in stranded_set or m.project in home_set:
            by_cause['stranded'].add(m.slug)
    lost = set().union(*by_cause.values())

    total = len(mems)
    rate = save_rate(mems)
    rate['misfiled'] = len(lost)
    rate['misfiled_by_cause'] = {k: len(v) for k, v in by_cause.items()}
    rate['recoverable'] = len(by_cause['split']) + len(by_cause['stranded'])
    rate['landing_rate'] = round(1 - len(lost) / total, 4) if total else 1.0

    return {
        'total': total,
        'labels': len(counts),
        'live_labels': len(live),
        'by_project': dict(counts.most_common()),
        'splits': splits,
        'stranded': stranded,
        'home_labels': homed,
        'quarantined': quarantined,
        'dangling': dangling,
        'save_rate': rate,
        'globals': sum(1 for m in mems if m.project is None),
    }
