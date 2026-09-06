"""memgit Pro — licence-key entitlement, validated against Polar, cached locally.

Design constraints (all deliberate):
  * NO new dependency. Plain memgit stays `click + rich + mcp`; the check uses urllib.
  * NOTHING about the store ever leaves the machine. The only bytes sent are the
    licence key and our organisation id, to Polar's public validation endpoint.
  * FAIL OPEN, bounded. A network failure never breaks a working install: a key
    that validated within GRACE_DAYS keeps its entitlement; a key that has never
    validated, or whose last good check is older than the grace window, is free.
  * The key is never printed in full. `pro status` shows the last 4 characters.

State lives OUTSIDE the store (a licence belongs to a person, not to a repo):
    $MEMGIT_HOME/license.json   (default ~/.memgit/license.json, mode 0600)

    {"key": "...", "activation_id": null, "status": "granted",
     "validated_at": "2026-09-03T10:00:00+00:00", "expires_at": null,
     "customer_email": null, "error": null}

Entitlement is also readable from the environment for headless/MCP hosts:
    MEMGIT_LICENSE_KEY=<key>   (validated with the same cache; never written to disk
                               unless `memgit pro activate` is run explicitly)
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

POLAR_API = os.environ.get("MEMGIT_POLAR_API", "https://api.polar.sh")
# Public identifier of the memgit organisation on Polar. Not a secret — it is the
# same value every customer's client sends. Overridable so tests and a future
# org migration never need a code change.
POLAR_ORGANIZATION_ID = os.environ.get(
    "MEMGIT_POLAR_ORG_ID", "1267be9a-acd0-4cdb-a3e4-0ee41134e87e"
)

GRACE_DAYS = 14          # keep entitlement this long after the last successful check
RECHECK_HOURS = 24       # do not hit the network more often than this
TIMEOUT_S = 6

_LICENSE_FILE = "license.json"


def home_dir() -> Path:
    return Path(os.environ.get("MEMGIT_HOME") or (Path.home() / ".memgit"))


def _path() -> Path:
    return home_dir() / _LICENSE_FILE


@dataclass
class License:
    key: str = ""
    activation_id: Optional[str] = None
    status: str = "none"              # none | granted | revoked | disabled | invalid | unknown
    validated_at: Optional[str] = None
    expires_at: Optional[str] = None
    customer_email: Optional[str] = None
    error: Optional[str] = None
    source: str = "file"              # file | env
    extra: dict = field(default_factory=dict)

    # ── derived ────────────────────────────────────────────────────────────
    @property
    def masked(self) -> str:
        k = self.key or ""
        return ("…" + k[-4:]) if len(k) >= 4 else ("…" if k else "")

    def _validated_dt(self) -> Optional[datetime]:
        if not self.validated_at:
            return None
        try:
            return datetime.fromisoformat(self.validated_at)
        except ValueError:
            return None

    def _expires_dt(self) -> Optional[datetime]:
        if not self.expires_at:
            return None
        try:
            return datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError:
            return None

    def is_entitled(self, now: Optional[datetime] = None) -> bool:
        """True when the last successful validation is within the grace window
        and the key has not passed its own expiry. Never consults the network."""
        now = now or datetime.now(timezone.utc)
        if self.status != "granted":
            return False
        v = self._validated_dt()
        if v is None or now - v > timedelta(days=GRACE_DAYS):
            return False
        e = self._expires_dt()
        if e is not None and now > e:
            return False
        return True

    def needs_recheck(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        v = self._validated_dt()
        return v is None or now - v > timedelta(hours=RECHECK_HOURS)


# ── persistence ────────────────────────────────────────────────────────────

def read() -> License:
    """The stored licence, or the env-supplied one, or an empty record."""
    p = _path()
    data: dict = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    lic = License(**{k: v for k, v in data.items() if k in License.__dataclass_fields__})
    env_key = os.environ.get("MEMGIT_LICENSE_KEY", "").strip()
    if env_key and env_key != lic.key:
        # An env key overrides the file but inherits nothing from it.
        lic = License(key=env_key, source="env")
    elif env_key:
        lic.source = "env+file"
    return lic


def write(lic: License) -> Path:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    payload = {k: v for k, v in asdict(lic).items() if k != "source"}
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(p)
    return p


def clear() -> bool:
    p = _path()
    if p.exists():
        p.unlink()
        return True
    return False


# ── network ────────────────────────────────────────────────────────────────

class ValidationResult(dict):
    """Raw validate() outcome. Keys: ok (bool), status (str), http (int|None),
    body (dict), error (str|None). `status` is one of granted/revoked/disabled/
    invalid/unknown — 'unknown' means the network did not answer, not that the
    key is bad."""


def _post_json(url: str, payload: dict, timeout: float = TIMEOUT_S) -> tuple[int, dict]:
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json",
                 "User-Agent": "memgit-pro/1"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — fixed https host
            return r.status, _safe_json(r.read())
    except urllib.error.HTTPError as e:
        try:
            body = _safe_json(e.read())
        except Exception:
            body = {}
        return e.code, body


def _safe_json(raw: bytes) -> dict:
    try:
        v = json.loads(raw.decode("utf-8") or "{}")
        return v if isinstance(v, dict) else {"value": v}
    except (ValueError, UnicodeDecodeError):
        return {}


def validate(key: str, activation_id: Optional[str] = None,
             org_id: Optional[str] = None, post=None) -> ValidationResult:
    """Ask Polar whether `key` is granted. Pure function over `post` so tests can
    substitute the transport; never raises."""
    post = post or _post_json   # resolved at call time so tests can monkeypatch the module
    org = org_id if org_id is not None else POLAR_ORGANIZATION_ID
    if not key:
        return ValidationResult(ok=False, status="invalid", http=None, body={}, error="no key")
    if not org:
        return ValidationResult(ok=False, status="unknown", http=None, body={},
                                error="MEMGIT_POLAR_ORG_ID is not configured in this build")
    payload = {"key": key, "organization_id": org}
    if activation_id:
        payload["activation_id"] = activation_id
    try:
        http, body = post(f"{POLAR_API}/v1/customer-portal/license-keys/validate", payload)
    except Exception as e:  # DNS, TLS, timeout, offline
        return ValidationResult(ok=False, status="unknown", http=None, body={}, error=str(e)[:200])
    if http == 200:
        st = str(body.get("status", "")).lower() or "granted"
        return ValidationResult(ok=(st == "granted"), status=st if st in ("granted", "revoked", "disabled") else "invalid",
                                http=http, body=body, error=None)
    if http in (400, 403, 404, 422):
        detail = body.get("detail") or body.get("error") or f"HTTP {http}"
        return ValidationResult(ok=False, status="invalid", http=http, body=body,
                                error=str(detail)[:200])
    # 5xx / 429 / anything else: the provider did not answer the question
    return ValidationResult(ok=False, status="unknown", http=http, body=body,
                            error=f"provider returned HTTP {http}")


def refresh(lic: License, now: Optional[datetime] = None, post=None,
            force: bool = False) -> License:
    """Validate when due and fold the answer into the record. Fail-open: an
    'unknown' answer leaves the last good validation untouched."""
    now = now or datetime.now(timezone.utc)
    if not lic.key:
        return lic
    if not force and not lic.needs_recheck(now):
        return lic
    res = validate(lic.key, lic.activation_id, post=post)
    if res["status"] == "unknown":
        lic.error = res["error"]
        return lic
    lic.status = res["status"]
    lic.error = None if res["ok"] else res["error"]
    if res["ok"]:
        lic.validated_at = now.isoformat()
        body = res["body"]
        lic.expires_at = body.get("expires_at")
        cust = body.get("customer") or {}
        lic.customer_email = cust.get("email") if isinstance(cust, dict) else None
        lic.extra = {k: body.get(k) for k in ("usage", "limit_usage", "validations", "id") if k in body}
    return lic


# ── the one call everything else uses ─────────────────────────────────────

def entitled(now: Optional[datetime] = None, allow_network: bool = True,
             post=None) -> bool:
    """Is this machine entitled to memgit Pro right now?

    Cheap path: the cached record answers without the network. When a recheck
    is due and the network is allowed, refresh (fail-open) and persist the
    result for file-sourced keys. Never raises."""
    try:
        lic = read()
        if not lic.key:
            return False
        if allow_network and lic.needs_recheck(now):
            lic = refresh(lic, now=now, post=post)
            if lic.source == "file":
                try:
                    write(lic)
                except OSError:
                    pass
        return lic.is_entitled(now)
    except Exception:
        return False


PRO_URL = "https://memgit.dev/#pricing"
