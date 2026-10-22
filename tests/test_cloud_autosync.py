"""Autosync: a commit starts one background sync, and only when the store can sync.

Before autosync, memgit cloud moved memory only when a person typed
`memgit cloud sync`, so saves made by an AI through MCP never left the machine
(measured 2026-10-22). These tests pin the trigger without touching the network.
"""
import json
import time
from datetime import datetime, timezone

from memgit.cloud import auto
from memgit.models import Mnemonic
from memgit.repo import Repository

NOW = datetime(2026, 10, 22, tzinfo=timezone.utc)


def _repo(tmp_path) -> Repository:
    return Repository.init(tmp_path / "store")


def _ready(repo: Repository, autosync: bool = True) -> None:
    d = repo.path / "cloud"
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps(
        {"autosync": autosync, "team_id": "t1", "repo_id": "r1"}))
    (d / "credentials.json").write_text(json.dumps({"private_key": "x"}))


class _Spawn:
    def __init__(self):
        self.calls = []

    def __call__(self, args, **kw):
        self.calls.append((args, kw))


def test_off_by_default_and_says_why(tmp_path):
    repo = _repo(tmp_path)
    st = auto.status(repo.path)
    assert not st["enabled"]
    assert any("autosync is off" in r for r in st["reasons"])
    assert any("not linked" in r for r in st["reasons"])


def test_no_cached_key_keeps_it_off(tmp_path):
    repo = _repo(tmp_path)
    _ready(repo)
    (repo.path / "cloud" / "credentials.json").write_text("{}")
    assert not auto.enabled(repo.path)


def test_commit_starts_one_background_worker(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _ready(repo)
    spawn = _Spawn()
    monkeypatch.setattr(auto.subprocess, "Popen", spawn)
    monkeypatch.delenv(auto.DISABLE_ENV, raising=False)
    repo.add(Mnemonic(type_code="pj", slug="goes-out", timestamp=NOW, rule="synced"))
    repo.commit(message="save")
    assert len(spawn.calls) == 1
    args, kw = spawn.calls[0]
    assert args[1:3] == ["-m", "memgit.cloud.auto"]
    assert kw["env"][auto.DISABLE_ENV] == "1"
    assert kw["start_new_session"] is True


def test_a_commit_with_no_change_starts_nothing(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _ready(repo)
    spawn = _Spawn()
    monkeypatch.setattr(auto.subprocess, "Popen", spawn)
    monkeypatch.delenv(auto.DISABLE_ENV, raising=False)
    assert repo.commit(message="nothing staged") is None
    assert spawn.calls == []


def test_the_worker_environment_cannot_start_another_worker(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _ready(repo)
    spawn = _Spawn()
    monkeypatch.setattr(auto.subprocess, "Popen", spawn)
    monkeypatch.setenv(auto.DISABLE_ENV, "1")
    assert auto.trigger(repo.path) is False
    assert spawn.calls == []


def test_a_save_during_a_run_marks_it_dirty_instead_of_spawning(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _ready(repo)
    spawn = _Spawn()
    monkeypatch.setattr(auto.subprocess, "Popen", spawn)
    monkeypatch.delenv(auto.DISABLE_ENV, raising=False)
    (repo.path / "cloud" / "autosync.lock").write_text("123")
    assert auto.trigger(repo.path) is True
    assert spawn.calls == []
    assert (repo.path / "cloud" / "autosync.dirty").exists()


def test_a_stale_lock_does_not_block_forever(tmp_path, monkeypatch):
    import os
    repo = _repo(tmp_path)
    _ready(repo)
    spawn = _Spawn()
    monkeypatch.setattr(auto.subprocess, "Popen", spawn)
    monkeypatch.delenv(auto.DISABLE_ENV, raising=False)
    lock = repo.path / "cloud" / "autosync.lock"
    lock.write_text("123")
    old = time.time() - auto.STALE_LOCK_SECS - 5
    os.utime(lock, (old, old))
    assert auto.trigger(repo.path) is True
    assert len(spawn.calls) == 1


def test_the_worker_reruns_when_a_save_lands_mid_run(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _ready(repo)
    runs = []

    def fake_sync(memgit_dir):
        runs.append(1)
        if len(runs) == 1:
            (repo.path / "cloud" / "autosync.dirty").touch()
        return {"ok": True}

    monkeypatch.setattr(auto, "sync_once", fake_sync)
    auto._worker(repo.path)
    assert len(runs) == 2
    assert not (repo.path / "cloud" / "autosync.lock").exists()


def test_sharing_and_sync_guidance_is_in_the_mcp_instructions():
    from memgit.mcp_server import _SERVER_DESCRIPTION as _INSTRUCTIONS
    assert "SHARING AND SYNC" in _INSTRUCTIONS
    assert "memgit cloud auto on" in _INSTRUCTIONS
    assert "memgit cloud watch" in _INSTRUCTIONS


def test_watch_exports_the_digest_once_per_new_head(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    repo.add(Mnemonic(type_code="pj", slug="for-hermes", timestamp=NOW, rule="read me at session start"))
    repo.commit(message="seed")
    heads = iter(["aaa", "aaa"])
    monkeypatch.setattr(auto, "sync_once", lambda d: {"ok": True, "head": next(heads)})
    monkeypatch.setattr(auto.time, "sleep", lambda s: None)
    writes = []
    real = auto.export_digest
    monkeypatch.setattr(auto, "export_digest", lambda d, p: (writes.append(p), real(d, p)))
    out = tmp_path / "ctx" / ".hermes.md"
    out.parent.mkdir()
    auto.watch(repo.path, 1, once=True, export=out)
    assert "for-hermes" in out.read_text()
    assert len(writes) == 1
