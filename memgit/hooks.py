"""Claude Code hook handlers — guardrail-grade recall and capture.

Voluntary tool calls are not enough: measured across 166 real sessions,
Claude engaged the memory tools in 6% of them while the SessionStart
injection worked in 100%. What a hook enforces happens; what a tool
description suggests mostly doesn't. These handlers close the two gaps
that don't survive on model discipline alone:

- prompt-recall (UserPromptSubmit): BM25-match the user's prompt against
  the store and inject the top hits as context. Recall stops depending on
  the model thinking to search.
- stop-guard (Stop): when a substantive session is about to end with zero
  memory writes, block the stop ONCE with instructions to save durable
  facts (or finish if nothing qualifies). Capture stops depending on the
  model remembering unprompted.

Both read the hook payload from stdin, never write to stdout unless they
have something to inject, and fail silent — a broken store must never
break the user's session.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

# Prompts shorter than this can't carry enough signal to search on.
MIN_PROMPT_CHARS = 20
# BM25 score below which a match is noise, not recall (empirically, real
# hits on a ~165-memory store score 8-32; near-misses land around 7).
MIN_RECALL_SCORE = 8.0
# Max memories injected per prompt.
RECALL_TOP_K = 3
# A session is "substantive" — worth a capture nudge — past this many
# tool uses. Small sessions rarely produce durable facts.
GUARD_MIN_TOOL_USES = 25


def _find_repo():
    from .repo import Repository, default_store_candidates
    for candidate in default_store_candidates():
        memgit_dir = candidate / '.memgit'
        if memgit_dir.is_dir():
            return Repository(memgit_dir)
    return None


def _read_payload() -> dict:
    try:
        return json.loads(sys.stdin.read() or '{}')
    except (json.JSONDecodeError, OSError):
        return {}


def _session_cache_dir(repo, kind: str) -> Path:
    d = repo.path / 'cache' / kind
    d.mkdir(parents=True, exist_ok=True)
    try:
        entries = list(d.iterdir())
        if len(entries) > 512:  # one file per session; prune the oldest half
            entries.sort(key=lambda p: p.stat().st_mtime)
            for old in entries[: len(entries) // 2]:
                old.unlink(missing_ok=True)
    except OSError:
        pass
    return d


def prompt_recall() -> int:
    """UserPromptSubmit: inject memories relevant to this prompt.

    stdout from a UserPromptSubmit hook is appended to the model's context,
    so printing IS injecting. Silent (no output) when nothing clears the
    relevance bar — an empty recall block on every prompt would train the
    model to ignore the real ones.
    """
    payload = _read_payload()
    prompt = (payload.get('prompt') or '').strip()
    if len(prompt) < MIN_PROMPT_CHARS or prompt.startswith('/'):
        return 0

    repo = _find_repo()
    if repo is None:
        return 0

    from .project import project_label_from_path
    from .scorer import score as bm25_score

    cwd = payload.get('cwd') or '.'
    project = project_label_from_path(Path(cwd))

    try:
        mnemonics = repo.list()
        results = bm25_score(prompt, mnemonics, top_k=RECALL_TOP_K,
                             boost_project=project)
    except Exception:
        return 0
    # BM25 IDF collapses on small corpora (a term found in most of 5 docs
    # scores near zero), so an absolute bar tuned on a mature store would
    # silence recall entirely for exactly the users who just adopted.
    # Ramp the bar up with store size instead.
    threshold = max(1.0, MIN_RECALL_SCORE * min(1.0, len(mnemonics) / 50))
    results = [r for r in results if r.score >= threshold]
    if not results:
        return 0

    # Don't re-inject what this session has already seen: repeated blocks
    # burn tokens and dull the signal.
    seen: set[str] = set()
    seen_file: Optional[Path] = None
    session_id = payload.get('session_id')
    if session_id:
        try:
            seen_file = _session_cache_dir(repo, 'recall') / str(session_id)
            if seen_file.exists():
                seen = set(seen_file.read_text().split())
        except OSError:
            seen_file = None
    results = [r for r in results if r.mnemonic.slug not in seen]
    if not results:
        return 0

    lines = ['<memgit-recall># Saved memories relevant to this request:']
    for r in results:
        m = r.mnemonic
        rule = m.rule if len(m.rule) <= 220 else m.rule[:219] + '…'
        detail = ' (full detail: get_memory)' if m.body else ''
        lines.append(f'- [{m.slug}] {rule}{detail}')
    lines.append('</memgit-recall>')
    print('\n'.join(lines))

    if seen_file is not None:
        try:
            seen.update(r.mnemonic.slug for r in results)
            seen_file.write_text('\n'.join(sorted(seen)))
        except OSError:
            pass

    # Feed the self-improving core guide: which memories actually surface.
    try:
        from .usage import record_hits
        record_hits(repo, [r.mnemonic.slug for r in results])
    except Exception:
        pass
    return 0


# Markers in a transcript that count as "this session captured memory".
# Anchored to tool_use JSON shapes: the plain tool NAME appears as text in
# every transcript (the host embeds the tool list), so bare substrings
# would match always and the guard would never fire.
import re as _re

_CAPTURE_RES = (
    _re.compile(r'"name"\s*:\s*"mcp__memgit__save_memory"'),      # MCP save
    _re.compile(r'"file_path"\s*:\s*"[^"]*/memory/[^"]*\.md'),    # md auto-memory write
    _re.compile(r'memgit (add|sync)\b'),                          # CLI save/sync
)
_TOOL_USE_RE = _re.compile(r'"type"\s*:\s*"tool_use"')


def stop_guard() -> int:
    """Stop: block ending a substantive session that captured nothing.

    Emits {"decision": "block", "reason": ...} at most ONCE per session
    (marker file + stop_hook_active double-guard), and only when the
    transcript shows real work with zero memory writes. The reason text
    explicitly allows finishing without saving when nothing durable was
    learned — this is a checkpoint, not a shakedown.
    """
    payload = _read_payload()
    if payload.get('stop_hook_active'):
        return 0
    transcript_path = payload.get('transcript_path')
    if not transcript_path:
        return 0

    repo = _find_repo()
    if repo is None:
        return 0

    session_id = payload.get('session_id') or Path(transcript_path).stem
    try:
        marker = _session_cache_dir(repo, 'stop-guard') / str(session_id)
        if marker.exists():
            return 0
    except OSError:
        return 0

    try:
        text = Path(transcript_path).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return 0

    if len(_TOOL_USE_RE.findall(text)) < GUARD_MIN_TOOL_USES:
        return 0
    if any(rx.search(text) for rx in _CAPTURE_RES):
        return 0

    try:
        marker.write_text('nudged')
    except OSError:
        return 0  # if we can't record the nudge, don't risk nudging forever

    print(json.dumps({
        'decision': 'block',
        'reason': (
            'memgit capture check — this session did substantial work but '
            'saved no memories. Before finishing: if you learned anything '
            'durable (a decision made, a root cause found, a preference or '
            'correction from the user, a gotcha in this codebase), save each '
            'one now with the memgit save_memory tool — one-line rule, full '
            'detail in body. If genuinely nothing durable was learned, just '
            'finish your response; this check will not repeat.'
        ),
    }))
    return 0
