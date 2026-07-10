"""Usage ledger — the sidecar signal that makes the core guide self-improving.

Kept deliberately OUTSIDE the content-addressed object store: a memory's sha
must not change when it is merely recalled, or every read would churn the store
and rewrite the index. Hit-counts are cheap, mutable, and disposable, so they
live here in `.memgit/cache/usage.json` instead of on the Mnemonic.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

_LEDGER = "usage.json"


def _path(repo) -> Path:
    d = repo.path / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / _LEDGER


def read_usage(repo) -> dict:
    try:
        return json.loads(_path(repo).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def record_hits(repo, slugs: Iterable[str], now: Optional[datetime] = None) -> None:
    """Increment the recall counter for each slug that was surfaced to the model.
    Best-effort: never raises into a hook/search path."""
    slugs = [s for s in slugs if s]
    if not slugs:
        return
    now = now or datetime.now(timezone.utc)
    ts = now.isoformat()
    try:
        data = read_usage(repo)
        for s in slugs:
            e = data.get(s) or {"hits": 0}
            e["hits"] = int(e.get("hits", 0)) + 1
            e["last_used"] = ts
            data[s] = e
        _path(repo).write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def reset_usage(repo) -> None:
    """Wipe the ledger — used by `core heal` when the signal looks corrupted."""
    try:
        _path(repo).unlink(missing_ok=True)
    except OSError:
        pass


def usage_score(entry: dict, now: datetime, half_life_days: float = 14.0) -> float:
    """Recency-weighted hit score. Decays with a 2-week half-life so a memory
    that stops being useful falls out of the guide instead of calcifying."""
    hits = int(entry.get("hits", 0))
    if hits <= 0:
        return 0.0
    last_iso = entry.get("last_used")
    if not last_iso:
        return float(hits)
    try:
        last = datetime.fromisoformat(last_iso)
    except ValueError:
        return float(hits)
    age_days = max(0.0, (now - last).total_seconds() / 86400.0)
    return hits * (0.5 ** (age_days / half_life_days))
