"""Memory-to-memory relations: supersession, the entity index, and the tagmap.

Supersession is DERIVED, never stored as a tombstone: a slug is superseded iff
some memory currently in the index lists it in `supersedes`. Removing the
superseder automatically resurrects the superseded memory. The edge direction
is new→old (the correction event is when the writer knows both slugs).

The entity index and tagmap exist for one measured reason: injected context is
read in ~59-100%% of sessions while active memory queries happen in ~7%%. A
count ("6 more memories on '8a8f4ec'") plus the exact query to run is what
converts a passive reader into an active one — so the passive surfaces must
advertise what the active layer knows.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional

from .models import Mnemonic


# ── supersession ──────────────────────────────────────────────────────────────

def superseded_slugs(mnemonics: Iterable[Mnemonic]) -> set[str]:
    """Slugs hidden because a LIVE memory supersedes them.

    Self-references never count (a memory cannot retire itself), and edges
    pointing at slugs not currently in the index are inert — they may refer
    to memories that will be synced in later, or that were removed.
    """
    live = {m.slug for m in mnemonics}
    out: set[str] = set()
    for m in mnemonics:
        for target in m.supersedes:
            if target in live and target != m.slug:
                out.add(target)
    return out


def filter_active(mnemonics: list[Mnemonic]) -> list[Mnemonic]:
    """Drop superseded memories — the default view for search/recall/resume.

    Applied BEFORE BM25 scoring so stale chain links neither consume rank
    slots nor distort the IDF-based recall threshold.
    """
    hidden = superseded_slugs(mnemonics)
    if not hidden:
        return list(mnemonics)
    return [m for m in mnemonics if m.slug not in hidden]


def superseded_by(slug: str, mnemonics: Iterable[Mnemonic]) -> list[str]:
    """Direct superseders of `slug` (usually one; forks are possible)."""
    return sorted(
        m.slug for m in mnemonics
        if slug in m.supersedes and m.slug != slug
    )


def resolve_head(slug: str, mnemonics: list[Mnemonic]) -> str:
    """Walk supersession edges from `slug` to the live head of its chain.

    Forks resolve to the newest-timestamp superseder; cycles terminate via
    the visited set (returning the newest node seen). A slug nothing
    supersedes is its own head.
    """
    by_slug = {m.slug: m for m in mnemonics}
    current = slug
    visited = {current}
    while True:
        heirs = [by_slug[s] for s in superseded_by(current, mnemonics)
                 if s in by_slug and s not in visited]
        if not heirs:
            return current
        newest = max(heirs, key=lambda m: m.timestamp)
        current = newest.slug
        visited.add(current)


def would_cycle(new_slug: str, targets: Iterable[str],
                mnemonics: list[Mnemonic]) -> list[str]:
    """Targets that would create a supersession cycle if `new_slug` claimed them.

    A cycle exists when a target's own supersedes-chain (transitively)
    reaches back to `new_slug`.
    """
    edges: dict[str, list[str]] = {m.slug: list(m.supersedes) for m in mnemonics}
    bad: list[str] = []
    for target in targets:
        stack = [target]
        seen: set[str] = set()
        while stack:
            cur = stack.pop()
            if cur == new_slug:
                bad.append(target)
                break
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(edges.get(cur, []))
    return bad


def validate_relations(slug: str, supersedes, related,
                       mnemonics: list[Mnemonic]) -> tuple[list[str], list[str], list[str]]:
    """Shared write-path validation for relation fields (MCP/CLI/HTTP).

    Returns (supersedes, related, warnings): self-references stripped, cycle
    edges DROPPED (never stored), unknown targets KEPT with a warning — the
    old memory may be synced in later, and an inert edge is harmless.
    """
    sup_list = [s for s in normalize_slug_list(supersedes) if s != slug]
    rel_list = [s for s in normalize_slug_list(related) if s != slug]
    warnings: list[str] = []
    if sup_list:
        live = {m.slug for m in mnemonics}
        cycles = set(would_cycle(slug, sup_list, mnemonics))
        for target in sup_list:
            if target in cycles:
                warnings.append(f"cycle rejected: {target} (edge dropped)")
            elif target not in live:
                warnings.append(f"unknown slug: {target} (kept)")
        sup_list = [s for s in sup_list if s not in cycles]
    return sup_list, rel_list, warnings


def normalize_slug_list(value) -> list[str]:
    """Coerce a user/LLM-supplied relation field into a clean slug list.

    Accepts a list or a comma-separated string; strips whitespace, drops
    empties and duplicates while preserving order.
    """
    if value is None:
        return []
    if isinstance(value, str):
        items = value.split(',')
    else:
        items = list(value)
    out: list[str] = []
    for item in items:
        s = str(item).strip()
        if s and s not in out:
            out.append(s)
    return out


# ── entity index ──────────────────────────────────────────────────────────────

def label_noise(project: Optional[str]) -> set[str]:
    """Lowercased tags that are noise for the current workspace: the project
    label and its '-'-components. Importer-derived label tags ('personal',
    'business') are not topics, and every path inside a workspace contains
    the label's words — so no depth surface may advertise them."""
    proj_lower = (project or '').lower()
    parts = {p for p in proj_lower.split('-') if p}
    if proj_lower:
        parts.add(proj_lower)
    return parts

def entity_index(mnemonics: list[Mnemonic], project: Optional[str],
                 min_count: int = 2, cap: int = 8) -> list[tuple[str, int]]:
    """Tag → memory-count pairs advertising the store's depth on each topic.

    Tags are the operator-curated taxonomy and score at field weight 1.8 in
    BM25, so every advertised topic is guaranteed to return results when
    searched — a count that leads nowhere would teach the model to ignore
    counts. Pool matches resume scoping (this project's tree + unscoped),
    superseded memories excluded, core guides excluded (not an entity).
    Tags with fewer than `min_count` memories are dropped: a count of 1 is
    not depth. The project's own label is dropped as noise.
    """
    from .project import project_affinity

    counts: Counter[str] = Counter()
    for m in filter_active(mnemonics):
        if m.type_code == 'co':
            continue
        if project and m.project and project_affinity(m.project, project) < 1:
            continue
        if not project and m.project:
            continue
        for tag in m.tags:
            tag = tag.strip()
            if tag:
                counts[tag] += 1
    noise = label_noise(project)
    items = [
        (tag, n) for tag, n in counts.items()
        if n >= min_count and tag.lower() not in noise
    ]
    items.sort(key=lambda tn: (-tn[1], tn[0]))
    return items[:cap]


# ── tagmap cache (context-triggered recall) ───────────────────────────────────
# The PostToolUse hook fires on every Read/Grep/Glob — it must NEVER load the
# object store. The tagmap is rebuilt once per commit and read as one small
# JSON file: {tag: {project_label_or_"": count}}, superseded filtered.

_TAGMAP = 'tagmap.json'


def _tagmap_path(repo) -> Path:
    d = repo.path / 'cache'
    d.mkdir(parents=True, exist_ok=True)
    return d / _TAGMAP


def write_tagmap(repo) -> None:
    """Rebuild the tagmap from the current index. Best-effort — called from
    the commit path, so it must never raise into a save."""
    try:
        data: dict[str, dict[str, int]] = {}
        for m in filter_active(repo.list()):
            if m.type_code == 'co':
                continue
            proj = m.project or ''
            for tag in m.tags:
                tag = tag.strip()
                if not tag:
                    continue
                per = data.setdefault(tag, {})
                per[proj] = per.get(proj, 0) + 1
        _tagmap_path(repo).write_text(json.dumps(data), encoding='utf-8')
    except Exception:
        pass


def read_tagmap(repo) -> dict:
    try:
        return json.loads(_tagmap_path(repo).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}


def tagmap_count(tagmap: dict, tag: str, project: Optional[str]) -> int:
    """Project-scoped count for one tag: this project's tree + unscoped."""
    from .project import project_affinity

    per = tagmap.get(tag)
    if not per:
        return 0
    total = 0
    for proj, n in per.items():
        if not proj:
            total += int(n)
        elif project and project_affinity(proj, project) >= 1:
            total += int(n)
        elif not project:
            continue
    return total
