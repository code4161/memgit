"""Metrics ledger — the SHOWABLE, honest account of what memgit costs and does.

Kept outside the content-addressed object store (like usage.py): these are
mutable, disposable counters, not memory content. Lives in
`.memgit/cache/metrics.json`.

Two things are recorded, both cheap and best-effort (never raise into a hook,
search, or session-start path):

  * SPEND — every injected surface (session-start digest, prompt-recall block,
    context-recall line, stop-guard nudge) records how many tokens it ACTUALLY
    rendered. No estimates: the block is tokenized as printed. This closes the
    "recall/ctx cost is guessed, not measured" gap.

  * CONVERSION — the only defensible savings-adjacent signal. A true "tokens
    saved" counterfactual is unmeasurable (a recall hit is context injected, not
    a file-read avoided), so we DO NOT invent one. Instead we measure whether
    depth advertising works: when a hint says `search_memories("x")` and a
    search for `x` follows within a short window, that hint was ACTED ON. The
    ratio acted/advertised is the honest "did it help" number.

Deliberately NOT recorded: any fabricated savings percentage or dollar figure.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

_LEDGER = "metrics.json"

#: An advertised tag counts as "acted on" only if a matching search lands within
#: this window — long enough to cover a turn or two, short enough that an
#: unrelated later search doesn't get miscredited.
CONVERSION_WINDOW_MIN = 30
#: Cap the recent-advertised map so it can't grow unbounded.
_MAX_RECENT_ADVERTISED = 200
#: The injection surfaces we account for.
KINDS = ("digest", "prompt_recall", "ctx_recall", "stop_guard")


def _path(repo) -> Path:
    d = repo.path / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / _LEDGER


def read_metrics(repo) -> dict:
    try:
        return json.loads(_path(repo).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _blank() -> dict:
    return {
        "injections": {k: {"count": 0, "tokens": 0} for k in KINDS},
        "advertised_total": 0,
        "acted_total": 0,
        "recent_advertised": {},   # tag -> iso timestamp of last advertisement
    }


def _load(repo) -> dict:
    data = read_metrics(repo)
    if not data:
        return _blank()
    # tolerate older/partial files
    base = _blank()
    base.update({k: v for k, v in data.items() if k in base})
    inj = base["injections"]
    for k in KINDS:
        inj.setdefault(k, {"count": 0, "tokens": 0})
    return base


def _write(repo, data: dict) -> None:
    try:
        _path(repo).write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def record_injection(repo, kind: str, tokens: int,
                     advertised_tag: Optional[str] = None,
                     now: Optional[datetime] = None) -> None:
    """Record one injected surface: its measured token cost and, if it carried a
    depth hint, the advertised tag (so a later search can be credited)."""
    if kind not in KINDS:
        return
    now = now or datetime.now(timezone.utc)
    try:
        data = _load(repo)
        e = data["injections"][kind]
        e["count"] = int(e.get("count", 0)) + 1
        e["tokens"] = int(e.get("tokens", 0)) + max(0, int(tokens or 0))
        if advertised_tag:
            data["advertised_total"] = int(data.get("advertised_total", 0)) + 1
            ra = data.setdefault("recent_advertised", {})
            ra[advertised_tag.lower()] = now.isoformat()
            if len(ra) > _MAX_RECENT_ADVERTISED:      # prune oldest
                for tag, _ in sorted(ra.items(), key=lambda kv: kv[1])[
                        : len(ra) - _MAX_RECENT_ADVERTISED]:
                    ra.pop(tag, None)
        _write(repo, data)
    except Exception:
        pass


def record_search(repo, query: str, now: Optional[datetime] = None,
                  window_min: int = CONVERSION_WINDOW_MIN) -> None:
    """If this search matches a recently-advertised tag, credit the conversion.

    Matching is exact-token: a search whose terms include an advertised tag
    (case-insensitive) within the window is that hint being acted on. The tag is
    then consumed so a single hint is credited at most once."""
    if not query or not query.strip():
        return
    now = now or datetime.now(timezone.utc)
    terms = {t for t in _query_terms(query)}
    if not terms:
        return
    try:
        data = _load(repo)
        ra = data.get("recent_advertised") or {}
        if not ra:
            return
        cutoff = now - timedelta(minutes=window_min)
        credited = False
        for tag in list(ra.keys()):
            if tag not in terms:
                continue
            try:
                when = datetime.fromisoformat(ra[tag])
            except (ValueError, TypeError):
                ra.pop(tag, None)
                continue
            if when >= cutoff:
                data["acted_total"] = int(data.get("acted_total", 0)) + 1
                credited = True
            ra.pop(tag, None)          # consume whether stale or credited
        if credited or ra != (data.get("recent_advertised") or {}):
            data["recent_advertised"] = ra
            _write(repo, data)
    except Exception:
        pass


def _query_terms(query: str) -> set:
    import re
    return {t for t in re.split(r"[^a-z0-9]+", query.lower()) if len(t) >= 2}


def reset_metrics(repo) -> None:
    try:
        _path(repo).unlink(missing_ok=True)
    except OSError:
        pass


def summary(repo) -> dict:
    """A flat, honest snapshot for `memgit metrics` — no fabricated savings."""
    data = _load(repo)
    inj = data["injections"]
    # sessions each channel actually fired in = one cache file per session
    def _sessions(kind: str) -> int:
        d = repo.path / "cache" / kind
        try:
            return sum(1 for _ in d.iterdir()) if d.is_dir() else 0
        except OSError:
            return 0
    total_inj_tokens = sum(int(v.get("tokens", 0)) for v in inj.values())
    total_inj_count = sum(int(v.get("count", 0)) for v in inj.values())
    adv = int(data.get("advertised_total", 0))
    acted = int(data.get("acted_total", 0))
    return {
        "injections": {
            k: {
                "count": int(inj[k].get("count", 0)),
                "tokens": int(inj[k].get("tokens", 0)),
                "avg_tokens": (round(inj[k]["tokens"] / inj[k]["count"])
                               if inj[k].get("count") else 0),
            }
            for k in KINDS
        },
        "total_injections": total_inj_count,
        "total_injected_tokens": total_inj_tokens,
        "sessions": {
            "prompt_recall": _sessions("recall"),
            "ctx_recall": _sessions("ctx-recall"),
            "stop_guard": _sessions("stop-guard"),
        },
        "advertised_total": adv,
        "acted_total": acted,
        "conversion_pct": (round(100 * acted / adv, 1) if adv else None),
    }
