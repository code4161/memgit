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

    from .project import detect_project, scope_filter
    from .scorer import score as bm25_score

    cwd = payload.get('cwd')
    project = detect_project(Path(cwd) if cwd else None)

    try:
        from .links import filter_active
        # Superseded memories are filtered BEFORE scoring: stale chain links
        # must not consume rank slots or distort the IDF threshold below.
        # Then scoped to this project's family + explicit-global: recall is
        # filter-by-default — another project's memories never inject, and
        # the IDF corpus (and the depth hint below) see only the scoped pool.
        mnemonics = scope_filter(filter_active(repo.list()), project)
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
    # Depth advertisement: the injected top-3 reads as "memory has been
    # consulted", which trains the model never to query the store — so tell
    # it, with a count and the exact call, when more exists on-topic.
    # (Measured before this line existed: 6.8% of recall-injected sessions
    # ever ran a search.) Hinted-but-not-shown memories are deliberately NOT
    # added to the dedup file or the usage ledger — they weren't surfaced.
    more_line, hinted_tag = _depth_hint(results, mnemonics, seen, project)
    if more_line:
        lines.append(more_line)
    lines.append('</memgit-recall>')
    print('\n'.join(lines))

    # Record the hinted tag so the context-recall channel never repeats it.
    if hinted_tag and session_id:
        try:
            hint_file = _session_cache_dir(repo, 'recall-hints') / str(session_id)
            prev = set(hint_file.read_text().split()) if hint_file.exists() else set()
            prev.add(hinted_tag)
            hint_file.write_text('\n'.join(sorted(prev)))
        except OSError:
            pass

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


def _depth_hint(results, mnemonics, seen: set[str],
                project: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    """One '+N more on <tag>' line advertising depth behind the injected hits.

    Picks the single best tag: among tags carried by the injected results,
    the one with the most ACTIVE memories that were neither injected nor
    already seen this session. `mnemonics` is the SCOPED pool (family +
    explicit-global), so the advertised count is exactly what a scoped
    search will return — a count inflated by foreign projects would lead
    nowhere. Requires >= 2 (a count of 1 is not depth and teaches the model
    to ignore counts). Project-label tags are excluded — the same noise rule
    as the memory index and context recall. At most one line, ever.
    Returns (line, tag) — both None when nothing clears the bar.
    """
    from .links import label_noise
    noise = label_noise(project)
    injected = {r.mnemonic.slug for r in results}
    tags: set[str] = set()
    for r in results:
        tags.update(t.strip() for t in r.mnemonic.tags
                    if t.strip() and len(t.strip()) <= 40
                    and t.strip().lower() not in noise)
    if not tags:
        return None, None
    best_tag, best_n = None, 0
    for tag in sorted(tags):
        n = sum(
            1 for m in mnemonics
            if tag in m.tags and m.slug not in injected and m.slug not in seen
        )
        if n > best_n:
            best_tag, best_n = tag, n
    if best_tag is None or best_n < 2:
        return None, None
    line = f'- +{best_n} more saved on \'{best_tag}\' — search_memories("{best_tag}")'
    return line, best_tag


# ── context recall (PostToolUse) ──────────────────────────────────────────────

# Tags advertised for a file path need real depth behind them.
CTX_MIN_TAG_COUNT = 3
# Hard per-session cap on context-recall injections: this hook rides the two
# hottest tools (Read/Grep) — unbounded, it would become noise the model
# learns to skip.
CTX_MAX_PER_SESSION = 3

_PATH_SPLIT_RE = None  # compiled lazily


def _path_tokens(*values: str) -> set[str]:
    """Lowercased path-segment tokens: split on / - _ . and whitespace."""
    global _PATH_SPLIT_RE
    if _PATH_SPLIT_RE is None:
        import re
        _PATH_SPLIT_RE = re.compile(r'[/\\\-_.\s]+')
    out: set[str] = set()
    for v in values:
        out.update(t for t in _PATH_SPLIT_RE.split(v.lower()) if len(t) >= 3)
    return out


def context_recall() -> int:
    """PostToolUse (Read|Grep|Glob): hint when memories exist about a file.

    Prompt-recall fires on what the user SAYS; this fires on where the model
    LOOKS — subtasks drift away from the prompt's keywords, and the file
    being read is the better signal mid-task. Never loads the object store:
    reads only the tagmap cache rebuilt at commit time. Emits at most one
    line per matched tag per session, hard-capped per session.
    """
    payload = _read_payload()
    tool_input = payload.get('tool_input') or {}
    # Path-ish fields across Read/Grep/Glob payload shapes.
    raw = ' '.join(str(tool_input.get(k) or '') for k in
                   ('file_path', 'path', 'pattern', 'glob'))
    if not raw.strip():
        return 0

    repo = _find_repo()
    if repo is None:
        return 0

    from .links import read_tagmap, tagmap_count, write_tagmap
    from .project import detect_project

    tagmap = read_tagmap(repo)
    if not tagmap:
        # A store last committed by pre-0.6.0 code has no tagmap yet — build
        # it once here (the only store load this hook ever does), so existing
        # installs work before their next commit.
        write_tagmap(repo)
        tagmap = read_tagmap(repo)
    if not tagmap:
        return 0
    cwd = payload.get('cwd')
    project = detect_project(Path(cwd) if cwd else None)

    tokens = _path_tokens(raw)
    if not tokens:
        return 0
    # Tag matches a path token exactly, case-insensitive. (Substring matching
    # would fire 'api' against half the filesystem.) Project-label tags are
    # excluded via the shared noise rule.
    from .links import label_noise
    noise = label_noise(project)
    lower_tags = {t.lower(): t for t in tagmap}
    candidates = []
    for tok in tokens:
        if tok in noise:
            continue
        tag = lower_tags.get(tok)
        if not tag:
            continue
        n = tagmap_count(tagmap, tag, project)
        if n >= CTX_MIN_TAG_COUNT:
            candidates.append((n, tag))
    if not candidates:
        return 0
    candidates.sort(key=lambda nt: (-nt[0], nt[1]))
    n, tag = candidates[0]

    # Session-scoped dedup + hard cap. Shares one file with prompt-recall's
    # namespace-cousin: a tag hinted by EITHER channel is not re-hinted here.
    session_id = payload.get('session_id')
    if session_id:
        try:
            marker = _session_cache_dir(repo, 'ctx-recall') / str(session_id)
            hinted = set(marker.read_text().split()) if marker.exists() else set()
            if tag in hinted or len(hinted) >= CTX_MAX_PER_SESSION:
                return 0
            recall_seen = _session_cache_dir(repo, 'recall-hints') / str(session_id)
            prompt_hinted = (set(recall_seen.read_text().split())
                             if recall_seen.exists() else set())
            if tag in prompt_hinted:
                return 0
            hinted.add(tag)
            marker.write_text('\n'.join(sorted(hinted)))
        except OSError:
            return 0

    import json as _json
    print(_json.dumps({
        'hookSpecificOutput': {
            'hookEventName': 'PostToolUse',
            'additionalContext': (
                f"memgit: {n} memories tagged '{tag}' relate to this path — "
                f'search_memories("{tag}")'
            ),
        }
    }))
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
            'detail in body. If you corrected a saved memory, pass '
            "supersedes=[old-slug] instead of a 'CORRECTED:' prefix. If you "
            'changed the state of anything tracked (see the status board at '
            'session start), update its <entity>-status tracker (save_memory, '
            'same slug, type tr). If genuinely nothing durable was learned, '
            'just finish your response; this check will not repeat.'
        ),
    }))
    return 0
