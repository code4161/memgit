"""Retrieval evaluation — the ruler that makes a ranking change provable.

Every ranking knob (usage, recency, stemming, a future dense leg) changes what
comes back for a query. Without a fixed measuring stick, each change is a guess
dressed up as an improvement. This module supplies the stick.

The regression set is mined from the store's OWN history rather than
hand-written: every time prompt-recall fired, it recorded which memories it
surfaced for a real user prompt. Those (prompt -> slugs) pairs are exactly the
behaviour a ranking change must not silently break. A case is generated once
and then frozen to disk, so the baseline is a fixed target and not something
that drifts with the store.

Metrics are the standard retrieval three, reported over the whole set:

  recall@k   fraction of cases where ANY expected slug appears in the top k
  hit@1      fraction where an expected slug ranks first
  MRR        mean reciprocal rank of the first expected slug (0 when absent)

There is deliberately no single "score": a change that trades hit@1 for
recall@5 is a judgement call the operator should see both sides of.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

#: Frozen regression cases live beside the store, not inside the object DB —
#: they are test fixtures, not memories, and must not churn the index.
EVALSET = 'evalset.json'


@dataclass
class EvalCase:
    """One frozen (query -> acceptable answers) pair."""
    query: str
    expected: list[str]
    project: Optional[str] = None
    source: str = 'recall'          # recall | search | manual
    note: str = ''


@dataclass
class EvalResult:
    n: int = 0
    hit_at_1: float = 0.0
    recall_at_3: float = 0.0
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    mrr: float = 0.0
    #: cases whose expected slugs are all missing from the store now
    skipped: int = 0
    #: cases whose expected memory still exists but has been RELABELLED out of
    #: the case's project scope. Not a miss — the case is stale, exactly like a
    #: deleted memory — but reported separately so a `doctor --relabel` never
    #: masquerades as a ranking regression. Re-mine to clear.
    stale: int = 0
    #: per-case detail, best-first rank of the first expected slug (None = miss)
    ranks: list = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop('ranks', None)
        return d


#: The two sets answer different questions and must never overwrite each other:
#: 'recall' measures stability against the ranking that produced the
#: transcripts, 'synthetic' measures correctness independently of it.
SETS = ('recall', 'synthetic')


def evalset_path(repo, name: str = 'recall') -> Path:
    if name == 'recall':
        return repo.path / EVALSET
    return repo.path / f'evalset.{name}.json'


def baseline_path(repo, name: str = 'recall') -> Path:
    return repo.path / f'evalset.{name}.baseline.json'


def load_evalset(repo, name: str = 'recall') -> list[EvalCase]:
    try:
        raw = json.loads(evalset_path(repo, name).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for r in raw:
        try:
            out.append(EvalCase(**r))
        except TypeError:
            continue
    return out


def save_evalset(repo, cases: list[EvalCase], name: str = 'recall') -> int:
    evalset_path(repo, name).write_text(
        json.dumps([asdict(c) for c in cases], indent=1), encoding='utf-8')
    return len(cases)


# ── mining ────────────────────────────────────────────────────────────────────

def mine_from_transcripts(transcript_root: Path, limit: int = 300,
                          min_query_chars: int = 25) -> list[EvalCase]:
    """Recover (user prompt -> slugs memgit surfaced) pairs from host transcripts.

    Reads Claude Code's own session logs: a `<memgit-recall>` block in the
    conversation is a record of what prompt-recall injected, and the user turn
    that triggered it is the query. This is ground truth in the only sense that
    matters — it is what the system did on real work.

    Best-effort and format-tolerant: a transcript shape it does not recognise
    yields no cases rather than an error.
    """
    import re
    cases: dict[str, EvalCase] = {}
    slug_re = re.compile(r'^- \[([a-zA-Z0-9][\w-]{2,80})\]', re.M)

    files = sorted(transcript_root.glob('*/*.jsonl'))
    for f in files:
        if 'observer' in f.parent.name:
            continue
        last_user: Optional[str] = None
        try:
            fh = open(f, errors='replace')
        except OSError:
            continue
        with fh:
            for line in fh:
                if len(line) < 5:
                    continue
                has_recall = '<memgit-recall>' in line
                if not has_recall and '"type":"user"' not in line \
                        and '"type": "user"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if not has_recall:
                    text = _user_text(obj)
                    if text:
                        stripped = text.strip()
                        if len(stripped) >= min_query_chars \
                                and not stripped.startswith('/'):
                            last_user = stripped
                    continue
                block = _recall_block(obj)
                if not block or not last_user:
                    continue
                slugs = slug_re.findall(block)
                if not slugs:
                    continue
                key = last_user[:400]
                if key in cases:
                    continue
                # The hook record carries the real workspace cwd — a better
                # project source than the munged transcript dir name, which
                # can disagree for a session started in a subdirectory.
                cases[key] = EvalCase(
                    query=key, expected=sorted(set(slugs)),
                    project=_project_of_cwd(obj.get('cwd'))
                            or _project_of(f.parent.name),
                    source='recall')
                if len(cases) >= limit:
                    return list(cases.values())
    return list(cases.values())


def _user_text(obj: dict) -> Optional[str]:
    if obj.get('type') != 'user':
        return None
    msg = obj.get('message') or {}
    content = msg.get('content')
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [c.get('text', '') for c in content
                 if isinstance(c, dict) and c.get('type') == 'text']
        return '\n'.join(p for p in parts if p) or None
    return None


def _recall_block(obj: dict) -> Optional[str]:
    """Extract the injected recall text from whatever shape the host logged it in.

    Claude Code records hook output as a top-level `attachment` record
    (`attachment.type == 'hook_success'`), not as user message content —
    checked first because it is the shape that actually occurs. The other
    branches cover older/alternate host layouts.
    """
    att = obj.get('attachment')
    if isinstance(att, dict):
        v = att.get('content')
        if isinstance(v, str) and '<memgit-recall>' in v:
            return v
    for key in ('content', 'text', 'hookOutput', 'systemMessage'):
        v = obj.get(key)
        if isinstance(v, str) and '<memgit-recall>' in v:
            return v
    msg = obj.get('message') or {}
    v = msg.get('content') if isinstance(msg, dict) else None
    if isinstance(v, str) and '<memgit-recall>' in v:
        return v
    if isinstance(v, list):
        for c in v:
            if isinstance(c, dict) and isinstance(c.get('text'), str) \
                    and '<memgit-recall>' in c['text']:
                return c['text']
    return None


def mine_synthetic(repo, limit: int = 300, min_chars: int = 40,
                   seed: int = 1729) -> list[EvalCase]:
    """Build NON-CIRCULAR cases: query from a memory's own `why`, answer itself.

    The transcript-mined set has a methodological flaw that must not be hidden:
    its expected answers ARE what the old ranking chose, so any change to
    ranking looks like a regression even when it is an improvement. It measures
    stability, not correctness.

    This set is independent of ranking history. For each memory carrying a
    substantial `why` (the incident/motivation behind the rule — a field
    weighted 1.0, well below slug at 2.0 and tags at 1.8), the query is that
    text and the single correct answer is the memory it came from. A ranker
    that cannot find a memory from its own stated reason is failing at the
    core job, and no ranking-history bias is involved.

    Deterministic: memories are taken in slug order, so the same store yields
    the same set on every machine.
    """
    import re as _re
    cases: list[EvalCase] = []
    for m in sorted(repo.list(), key=lambda x: x.slug):
        why = (m.why or '').strip()
        if len(why) < min_chars:
            continue
        # Strip the slug's own words out of the query: leaving them in would
        # hand the ranker a 2.0-weighted exact match and measure nothing.
        slug_words = {w for w in m.slug.lower().split('-') if len(w) > 2}
        words = [w for w in _re.findall(r"[A-Za-z0-9']+", why)
                 if w.lower() not in slug_words]
        query = ' '.join(words).strip()
        if len(query) < min_chars:
            continue
        cases.append(EvalCase(query=query[:400], expected=[m.slug],
                              project=m.project, source='synthetic',
                              note='query=why, slug tokens removed'))
        if len(cases) >= limit:
            break
    return cases


def _project_of(munged_dir: str) -> Optional[str]:
    from .project import project_label_from_munged
    try:
        return project_label_from_munged(munged_dir)
    except Exception:
        return None


def _project_of_cwd(cwd) -> Optional[str]:
    if not cwd:
        return None
    from .project import project_label_from_path
    try:
        return project_label_from_path(Path(cwd))
    except Exception:
        return None


# ── running ───────────────────────────────────────────────────────────────────

def run_eval(repo, cases: list[EvalCase], top_k: int = 10,
             use_usage: bool = True, now=None) -> EvalResult:
    """Score every case against the CURRENT ranking and report the metrics.

    Cases whose expected slugs have all left the store are skipped, not
    counted as misses — a deleted memory is not a ranking regression.
    """
    from .scorer import score as bm25_score
    from .links import filter_active
    from .usage import read_usage
    from .project import same_project_family

    mnemonics = filter_active(repo.list())
    by_slug = {m.slug: m for m in mnemonics}
    live = set(by_slug)
    usage = read_usage(repo) if use_usage else None

    res = EvalResult()
    rr_total = 0.0
    hits = {1: 0, 3: 0, 5: 0, 10: 0}
    for case in cases:
        expected = [s for s in case.expected if s in live]
        if not expected:
            res.skipped += 1
            continue
        # A case whose answer has been relabelled out of its own scope can
        # never pass, no matter how good the ranking is. Counting it as a miss
        # would report every `doctor --relabel` as a retrieval regression.
        if case.project and not any(
                by_slug[s].project is None
                or same_project_family(by_slug[s].project, case.project)
                for s in expected):
            res.stale += 1
            continue
        results = bm25_score(case.query, mnemonics, top_k=top_k,
                             boost_project=case.project,
                             scope_project=case.project,
                             usage=usage, now=now)
        ranked = [r.mnemonic.slug for r in results]
        rank = None
        for i, slug in enumerate(ranked, start=1):
            if slug in expected:
                rank = i
                break
        res.n += 1
        res.ranks.append({'query': case.query[:80], 'rank': rank,
                          'expected': expected[:3]})
        if rank is None:
            continue
        rr_total += 1.0 / rank
        for k in hits:
            if rank <= k:
                hits[k] += 1

    if res.n:
        res.hit_at_1 = round(hits[1] / res.n, 4)
        res.recall_at_3 = round(hits[3] / res.n, 4)
        res.recall_at_5 = round(hits[5] / res.n, 4)
        res.recall_at_10 = round(hits[10] / res.n, 4)
        res.mrr = round(rr_total / res.n, 4)
    return res


def compare(before: EvalResult, after: EvalResult) -> dict:
    """Signed deltas between two runs — what a ranking change actually did."""
    keys = ('hit_at_1', 'recall_at_3', 'recall_at_5', 'recall_at_10', 'mrr')
    return {k: round(getattr(after, k) - getattr(before, k), 4) for k in keys}
