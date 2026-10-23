"""Drift between memgit's critical rules and the rule files a host loads.

A host's own rules file (CLAUDE.md, AGENTS.md, ...) is read every session and
usually told to win over memgit. When it says the opposite of a critical
memory, the memory loses twice: it may not surface, and if it does, the agent
is instructed to obey the file. Measured 2026-10-23 on a client repo: the
CLAUDE.md said "Always branch from staging" against a rule forbidding feature
branches, and "hand the user SELECT + DELETE SQL" against a rule that data
fixes ship as scripts. Both rules were broken that day.

Whether two sentences contradict is a judgement, so this module does not
claim it. It finds, for each critical behaviour rule, the rule-file passage on
the same topic (TF-IDF cosine over the rule and the passage), and reports the
pairs for a reader to judge. The memgit-managed block in a rules file, and the
files memgit itself delivers, are excluded: comparing memgit with its own copy
would only ever find agreement.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

#: Rule files hosts load, relative to a directory.
RULE_FILES = ('CLAUDE.md', 'AGENTS.md', 'GEMINI.md', '.cursorrules',
              '.windsurfrules', '.github/copilot-instructions.md')
RULE_GLOBS = ('.claude/rules/*.md', '.cursor/rules/*.mdc')
#: Files memgit writes itself; never compared.
MEMGIT_OWNED = ('.claude/rules/memgit.md', '.cursor/rules/memgit.mdc')
_BLOCK_RE = re.compile(r'<!--\s*MEMGIT:BEGIN\s*-->.*?<!--\s*MEMGIT:END\s*-->',
                       re.DOTALL)
#: Cosine at or above which a passage is reported as on the same topic.
#: Calibrated 2026-10-23 on a client CLAUDE.md: the two passages known to
#: contradict a critical rule scored 0.315 and 0.194; the next unrelated
#: passage for either rule scored 0.139.
DRIFT_MIN = 0.18
#: Passages reported per rule. One was not enough: on that CLAUDE.md the
#: "hand the user SQL" line scored 0.194 against the scripts rule, second to
#: a migrations line at 0.253.
PER_RULE = 2
MIN_PASSAGE_CHARS = 30


@dataclass
class Passage:
    path: Path
    line: int
    text: str


@dataclass
class DriftPair:
    slug: str
    rule: str
    passage: Passage
    score: float


def rule_files(start: Path, stop: Optional[Path] = None) -> list[Path]:
    """Rule files a session started in `start` is likely to load: those in
    `start` and each parent up to `stop` (default: the home directory), plus
    those one directory below `start` (sub-repos of a workspace)."""
    start = start.resolve()
    stop = (stop or Path.home()).resolve()
    dirs: list[Path] = []
    d = start
    while True:
        dirs.append(d)
        if d == stop or d.parent == d:
            break
        d = d.parent
    try:
        dirs += sorted(p for p in start.iterdir()
                       if p.is_dir() and not p.name.startswith('.')
                       and p.name not in ('node_modules', 'venv', '.venv'))
    except OSError:
        pass
    seen: set[Path] = set()
    out: list[Path] = []
    for d in dirs:
        cands = [d / n for n in RULE_FILES]
        for g in RULE_GLOBS:
            cands += sorted(d.glob(g))
        for p in cands:
            try:
                if not p.is_file():
                    continue
                if any(str(p).endswith(o) for o in MEMGIT_OWNED):
                    continue
                real = p.resolve()
            except OSError:
                continue
            if real in seen:            # AGENTS.md is often a symlink to CLAUDE.md
                continue
            seen.add(real)
            out.append(p)
    return out


def passages(path: Path) -> list[Passage]:
    """Split a markdown rules file into list items and paragraphs."""
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return []
    # Blank out the memgit-managed block but keep line numbers.
    text = _BLOCK_RE.sub(lambda m: '\n' * m.group(0).count('\n'), text)
    out: list[Passage] = []
    cur: list[str] = []
    start = 0
    in_code = False

    def flush():
        if cur:
            body = ' '.join(s.strip() for s in cur).strip()
            if len(body) >= MIN_PASSAGE_CHARS:
                out.append(Passage(path, start, body))
        cur.clear()

    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if line.lstrip().startswith('```'):
            flush()
            in_code = not in_code
            continue
        if in_code:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or stripped.startswith('|') \
                or stripped in ('---', '***'):
            flush()
            continue
        if re.match(r'^\s*([-*+]|\d+[.)])\s+', line) and not line.startswith('     '):
            flush()
        if not cur:
            start = i
        cur.append(stripped)
    flush()
    return out


def _tokens(text: str) -> list[str]:
    from .scorer import content_tokens
    return content_tokens(text)


def find_drift(mnemonics, files: list[Path], project: Optional[str],
               floor: float = DRIFT_MIN, per_rule: int = PER_RULE) -> list[DriftPair]:
    """For each critical fb/cn rule in scope, its closest rule-file passages
    (up to `per_rule`) scoring at or above `floor`. Best-scoring pairs first."""
    from .links import filter_active
    from .project import project_affinity
    rules = [m for m in filter_active(mnemonics)
             if m.priority == 3 and m.type_code in ('fb', 'cn')
             and not m.unverified and m.project
             and project and project_affinity(m.project, project) >= 1]
    if not rules:
        return []
    ps = [p for f in files for p in passages(f)]
    if not ps:
        return []
    rule_toks = {m.slug: _tokens((m.rule or '') + ' ' + (m.when or ''))
                 for m in rules}
    pas_toks = [_tokens(p.text) for p in ps]
    df: Counter = Counter()
    for t in list(rule_toks.values()) + pas_toks:
        df.update(set(t))
    n = len(rules) + len(ps)

    def vec(tokens):
        tf = Counter(tokens)
        v = {t: (1 + math.log(c)) * math.log((n + 1) / (df[t] + 1))
             for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    pvecs = [vec(t) for t in pas_toks]
    out: list[DriftPair] = []
    for m in rules:
        q = vec(rule_toks[m.slug])
        scored = sorted(((sum(x * pv.get(t, 0.0) for t, x in q.items()), i)
                         for i, pv in enumerate(pvecs)), key=lambda s: (-s[0], s[1]))
        for c, i in scored[:per_rule]:
            if c >= floor:
                out.append(DriftPair(m.slug, m.rule or '', ps[i], round(c, 3)))
    out.sort(key=lambda d: (-d.score, d.slug))
    return out
