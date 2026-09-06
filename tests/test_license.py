"""memgit Pro licence: cached entitlement, fail-open refresh, env override,
masking, and the `memgit pro` commands. The network is replaced by a fake
transport; no test ever reaches Polar."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from click.testing import CliRunner

from memgit import license as lic_mod


NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMGIT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MEMGIT_POLAR_ORG_ID", "org_test")
    monkeypatch.setattr(lic_mod, "POLAR_ORGANIZATION_ID", "org_test")
    monkeypatch.delenv("MEMGIT_LICENSE_KEY", raising=False)


def granted(**over):
    body = {"status": "granted", "expires_at": None, "customer": {"email": "a@b.c"},
            "usage": 0, "limit_usage": None, "validations": 3, "id": "lk_1"}
    body.update(over)

    def _post(url, payload):
        assert url.endswith("/v1/customer-portal/license-keys/validate")
        assert payload["organization_id"] == "org_test"
        return 200, body
    return _post


def http(code, body=None):
    def _post(url, payload):
        return code, (body or {"detail": "nope"})
    return _post


def offline(url, payload):
    raise OSError("no route to host")


# ── validate() ─────────────────────────────────────────────────────────────

def test_validate_granted():
    r = lic_mod.validate("KEY-1234", post=granted())
    assert r["ok"] and r["status"] == "granted"


def test_validate_revoked_is_not_ok():
    r = lic_mod.validate("KEY-1234", post=granted(status="revoked"))
    assert not r["ok"] and r["status"] == "revoked"


@pytest.mark.parametrize("code", [400, 403, 404, 422])
def test_validate_client_errors_are_invalid(code):
    r = lic_mod.validate("KEY-1234", post=http(code))
    assert r["status"] == "invalid" and not r["ok"]


@pytest.mark.parametrize("code", [429, 500, 502, 503])
def test_validate_server_errors_are_unknown(code):
    r = lic_mod.validate("KEY-1234", post=http(code))
    assert r["status"] == "unknown"


def test_validate_offline_is_unknown():
    r = lic_mod.validate("KEY-1234", post=offline)
    assert r["status"] == "unknown" and "no route" in r["error"]


def test_validate_without_org_is_unknown(monkeypatch):
    monkeypatch.setattr(lic_mod, "POLAR_ORGANIZATION_ID", "")
    r = lic_mod.validate("KEY-1234", post=granted())
    assert r["status"] == "unknown"


# ── entitlement arithmetic (no network) ────────────────────────────────────

def test_entitled_within_grace_and_not_after():
    lic = lic_mod.License(key="K", status="granted",
                          validated_at=(NOW - timedelta(days=3)).isoformat())
    assert lic.is_entitled(NOW)
    assert not lic.is_entitled(NOW + timedelta(days=lic_mod.GRACE_DAYS))


def test_expired_key_is_not_entitled():
    lic = lic_mod.License(key="K", status="granted", validated_at=NOW.isoformat(),
                          expires_at=(NOW - timedelta(hours=1)).isoformat())
    assert not lic.is_entitled(NOW)


def test_recheck_cadence():
    lic = lic_mod.License(key="K", status="granted", validated_at=NOW.isoformat())
    assert not lic.needs_recheck(NOW + timedelta(hours=1))
    assert lic.needs_recheck(NOW + timedelta(hours=lic_mod.RECHECK_HOURS + 1))


# ── refresh(): fail-open ───────────────────────────────────────────────────

def test_refresh_offline_keeps_last_good_validation():
    lic = lic_mod.License(key="K", status="granted",
                          validated_at=(NOW - timedelta(days=2)).isoformat())
    out = lic_mod.refresh(lic, now=NOW, post=offline, force=True)
    assert out.status == "granted" and out.is_entitled(NOW)
    assert "no route" in out.error


def test_refresh_revoked_drops_entitlement():
    lic = lic_mod.License(key="K", status="granted", validated_at=NOW.isoformat())
    out = lic_mod.refresh(lic, now=NOW, post=granted(status="revoked"), force=True)
    assert out.status == "revoked" and not out.is_entitled(NOW)


def test_refresh_records_customer_and_expiry():
    lic = lic_mod.License(key="K")
    out = lic_mod.refresh(lic, now=NOW, post=granted(expires_at="2027-01-01T00:00:00Z"))
    assert out.customer_email == "a@b.c"
    assert out.expires_at == "2027-01-01T00:00:00Z"
    assert out.validated_at == NOW.isoformat()


# ── persistence + env ──────────────────────────────────────────────────────

def test_write_read_roundtrip_and_mode(tmp_path):
    p = lic_mod.write(lic_mod.License(key="ABCD-EFGH", status="granted", validated_at=NOW.isoformat()))
    assert p.exists() and (p.stat().st_mode & 0o777) == 0o600
    back = lic_mod.read()
    assert back.key == "ABCD-EFGH" and back.source == "file" and back.masked == "…EFGH"


def test_env_key_overrides_file(monkeypatch):
    lic_mod.write(lic_mod.License(key="FILE-KEY", status="granted", validated_at=NOW.isoformat()))
    monkeypatch.setenv("MEMGIT_LICENSE_KEY", "ENV-KEY")
    lic = lic_mod.read()
    assert lic.key == "ENV-KEY" and lic.source == "env" and lic.status == "none"


def test_entitled_persists_only_file_keys(monkeypatch):
    monkeypatch.setenv("MEMGIT_LICENSE_KEY", "ENV-KEY")
    assert lic_mod.entitled(now=NOW, post=granted())
    assert not lic_mod._path().exists()          # env keys are never written to disk


def test_entitled_is_false_with_no_key():
    assert not lic_mod.entitled(now=NOW, post=granted())


def test_clear():
    lic_mod.write(lic_mod.License(key="K"))
    assert lic_mod.clear() and not lic_mod.clear()


# ── CLI: memgit pro ────────────────────────────────────────────────────────

def test_cli_activate_status_deactivate(monkeypatch):
    from memgit import cli as cli_mod
    monkeypatch.setattr(lic_mod, "_post_json", granted())
    r = CliRunner().invoke(cli_mod.cli, ["pro", "activate", "ABCD-1234-WXYZ"])
    assert r.exit_code == 0, r.output
    assert "activated" in r.output.lower()
    assert "ABCD-1234-WXYZ" not in r.output          # never echo the key
    assert "…WXYZ" in r.output

    r = CliRunner().invoke(cli_mod.cli, ["pro", "status"])
    assert r.exit_code == 0 and "Pro" in r.output and "…WXYZ" in r.output

    r = CliRunner().invoke(cli_mod.cli, ["pro", "deactivate"])
    assert r.exit_code == 0
    assert not lic_mod._path().exists()


def test_cli_activate_rejects_bad_key(monkeypatch):
    from memgit import cli as cli_mod
    monkeypatch.setattr(lic_mod, "_post_json", http(404, {"detail": "License key does not exist"}))
    r = CliRunner().invoke(cli_mod.cli, ["pro", "activate", "NOPE-0000"])
    assert r.exit_code != 0
    assert not lic_mod._path().exists()             # a rejected key is not stored


def test_cli_activate_offline_stores_key_unverified(monkeypatch):
    from memgit import cli as cli_mod
    monkeypatch.setattr(lic_mod, "_post_json", offline)
    r = CliRunner().invoke(cli_mod.cli, ["pro", "activate", "LATER-9999"])
    assert r.exit_code == 0 and "could not reach" in r.output.lower()
    assert lic_mod.read().key == "LATER-9999"
    assert not lic_mod.entitled(now=NOW, allow_network=False)


def test_cli_status_free():
    from memgit import cli as cli_mod
    r = CliRunner().invoke(cli_mod.cli, ["pro", "status"])
    assert r.exit_code == 0 and "Free" in r.output


def test_cli_status_json(monkeypatch):
    from memgit import cli as cli_mod
    lic_mod.write(lic_mod.License(key="ABCD-1234", status="granted", validated_at=NOW.isoformat()))
    monkeypatch.setattr(lic_mod, "_post_json", granted())
    r = CliRunner().invoke(cli_mod.cli, ["pro", "status", "--json"])
    assert r.exit_code == 0
    d = json.loads(r.output)
    assert d["entitled"] is True and d["key"] == "…1234" and "ABCD" not in r.output
