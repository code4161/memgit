"""v0.9.0 — durability that does not wait for a human.

The premise under test: a maintenance task requiring a human command is a task
that will not happen (measured — `git init` was never run in five weeks on a
1,734-memory store). These tests pin the automatic path AND the safety boundary
that keeps it from being reckless.
"""
import os
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from memgit.models import Mnemonic
from memgit.repo import Repository


@pytest.fixture
def repo(tmp_path):
    r = Repository.init(tmp_path / "store")
    for i in range(30):
        r.add(Mnemonic(type_code="lx", slug=f"m{i}", rule=f"lesson number {i}",
                       timestamp=datetime.now(timezone.utc), project="P"))
    r.commit(message="seed", trigger="explicit")
    return r


def _fake_home(tmp_path, *names) -> Path:
    home = tmp_path / "home"
    for n in names:
        (home / n).mkdir(parents=True, exist_ok=True)
    home.mkdir(exist_ok=True)
    return home


# ── destination discovery ────────────────────────────────────────────────────

class TestDestinations:
    def test_finds_icloud(self, repo, tmp_path):
        from memgit.backup import detect_destinations
        home = _fake_home(tmp_path, "Library/Mobile Documents/com~apple~CloudDocs")
        dests = detect_destinations(repo, home)
        assert any(d.label == "iCloud Drive" and d.kind == "synced" for d in dests)

    def test_finds_dropbox(self, repo, tmp_path):
        from memgit.backup import detect_destinations
        home = _fake_home(tmp_path, "Dropbox")
        assert any(d.label == "Dropbox" for d in detect_destinations(repo, home))

    def test_no_destinations_when_nothing_present(self, repo, tmp_path, monkeypatch):
        from memgit import backup
        monkeypatch.setattr(backup, "_external_volumes", lambda: [])
        home = _fake_home(tmp_path)
        assert backup.detect_destinations(repo, home) == []

    def test_never_invents_a_git_remote(self, repo, tmp_path):
        """memgit must not create a repository or pick a host on the user's
        behalf — memories can contain credentials."""
        from memgit.backup import _configured_remote
        assert _configured_remote(repo) is None

    def test_configured_remote_ranks_first(self, repo, tmp_path, monkeypatch):
        from memgit import backup
        monkeypatch.setattr(backup, "_configured_remote", lambda r: "origin")
        monkeypatch.setattr(backup, "_external_volumes", lambda: [])
        home = _fake_home(tmp_path, "Dropbox")
        dests = backup.detect_destinations(repo, home)
        assert dests[0].kind == "remote"


# ── the archive ──────────────────────────────────────────────────────────────

class TestArchive:
    def test_produces_one_file_not_a_tree(self, repo, tmp_path):
        """10k small object files into a cloud-sync folder is how you get a
        sync client that never finishes."""
        from memgit.backup import mirror_store, ARCHIVE_NAME
        dest = tmp_path / "dest"
        mirror_store(repo, dest)
        assert (dest / ARCHIVE_NAME).is_file()
        assert not (dest / ".memgit").exists()

    def test_archive_round_trips(self, repo, tmp_path):
        """The only property that matters: it restores."""
        from memgit.backup import mirror_store, ARCHIVE_NAME
        dest = tmp_path / "dest"
        mirror_store(repo, dest)
        out = tmp_path / "restored"
        out.mkdir()
        with tarfile.open(dest / ARCHIVE_NAME) as tar:
            tar.extractall(out, filter="data")
        restored = Repository(out / "memgit-store" / ".memgit")
        assert len(restored.list()) == 30
        assert restored.fsck() == []

    def test_cache_is_excluded(self, repo, tmp_path):
        from memgit.backup import mirror_store, ARCHIVE_NAME
        (repo.path / "cache" / "recall").mkdir(parents=True, exist_ok=True)
        (repo.path / "cache" / "recall" / "sess").write_text("junk")
        dest = tmp_path / "dest"
        mirror_store(repo, dest)
        with tarfile.open(dest / ARCHIVE_NAME) as tar:
            names = tar.getnames()
        assert not any("/cache/" in n for n in names)

    def test_previous_archive_survives_until_new_one_lands(self, repo, tmp_path):
        """An interrupted backup must never leave a corrupt file where a good
        one used to be — that is worse than no backup, because it looks safe."""
        from memgit.backup import mirror_store, ARCHIVE_NAME
        dest = tmp_path / "dest"
        mirror_store(repo, dest)
        first = (dest / ARCHIVE_NAME).read_bytes()
        repo.add(Mnemonic(type_code="lx", slug="later", rule="added after",
                          timestamp=datetime.now(timezone.utc), project="P"))
        repo.commit(message="more", trigger="explicit")
        mirror_store(repo, dest)
        assert (dest / ARCHIVE_NAME).read_bytes() != first
        assert not (dest / (ARCHIVE_NAME + ".incoming")).exists()
        assert not (dest / (ARCHIVE_NAME + ".previous")).exists()

    def test_writes_restore_instructions(self, repo, tmp_path):
        from memgit.backup import mirror_store
        dest = tmp_path / "dest"
        mirror_store(repo, dest)
        text = (dest / "RESTORE.txt").read_text()
        assert "tar -xzf" in text and "memgit fsck" in text


# ── the automatic path + its safety boundary ─────────────────────────────────

class TestAutoBackup:
    def test_refuses_to_run_unattended_on_a_scratch_store(self, repo, monkeypatch):
        """Regression: a test exercising the sync path fired a real backup into
        the developer's actual iCloud, because discovery reads the true home
        while the store was a temp path."""
        from memgit.backup import auto_backup_allowed, maybe_auto_backup
        monkeypatch.setenv("MEMGIT_STORE", "/tmp/whatever")
        assert auto_backup_allowed(repo) is False
        assert maybe_auto_backup(repo) is None

    def test_refuses_under_pytest(self, repo, monkeypatch):
        from memgit.backup import auto_backup_allowed
        monkeypatch.delenv("MEMGIT_STORE", raising=False)
        # PYTEST_CURRENT_TEST is always set while a test is executing
        assert os.environ.get("PYTEST_CURRENT_TEST")
        assert auto_backup_allowed(repo) is False

    def test_explicit_backup_is_never_blocked_by_the_guard(self, repo, tmp_path):
        """`backup now` is someone asking on purpose — the guard is only for
        the unattended path."""
        from memgit.backup import run_backup, Destination
        dest = Destination("path", "explicit", str(tmp_path / "dest"), True)
        ok, msg = run_backup(repo, dest)
        assert ok, msg

    def test_staleness(self, repo):
        from memgit.backup import (read_state, write_state, is_stale,
                                   hours_since_backup, STALE_AFTER_HOURS)
        assert is_stale(repo) is True          # never backed up
        assert hours_since_backup(repo) is None
        s = read_state(repo)
        s.last_ok = datetime.now(timezone.utc).isoformat()
        write_state(repo, s)
        assert is_stale(repo) is False
        s.last_ok = (datetime.now(timezone.utc)
                     - timedelta(hours=STALE_AFTER_HOURS + 1)).isoformat()
        write_state(repo, s)
        assert is_stale(repo) is True

    def test_disabled_state_is_respected(self, repo):
        from memgit.backup import read_state, write_state, maybe_auto_backup
        s = read_state(repo)
        s.disabled = True
        write_state(repo, s)
        assert maybe_auto_backup(repo) is None

    def test_state_records_success(self, repo, tmp_path):
        from memgit.backup import run_backup, Destination, read_state
        ok, _ = run_backup(repo, Destination("path", "x", str(tmp_path / "d"), True))
        assert ok
        s = read_state(repo)
        assert s.last_ok and s.memories == 30 and s.last_error is None

    def test_failure_is_recorded_not_raised(self, repo, monkeypatch, tmp_path):
        from memgit import backup
        def boom(*a, **k):
            raise OSError("disk gone")
        monkeypatch.setattr(backup, "mirror_store", boom)
        ok, msg = backup.run_backup(
            repo, backup.Destination("path", "x", str(tmp_path / "d"), True))
        assert ok is False and "disk gone" in msg
        assert backup.read_state(repo).last_error


# ── the digest warning ───────────────────────────────────────────────────────

class TestDurabilityHint:
    def test_warns_when_no_backup_exists(self, repo):
        from memgit.backup import status_line
        line = status_line(repo)
        assert line and "backup" in line.lower() and "30 memories" in line

    def test_silent_for_a_tiny_store(self, tmp_path):
        """Nothing worth protecting yet — a warning that always fires is noise."""
        from memgit.backup import status_line
        r = Repository.init(tmp_path / "small")
        r.add(Mnemonic(type_code="lx", slug="one", rule="only one",
                       timestamp=datetime.now(timezone.utc)))
        r.commit(message="x", trigger="explicit")
        assert status_line(r) is None

    def test_silent_right_after_a_backup(self, repo):
        from memgit.backup import read_state, write_state, status_line
        s = read_state(repo)
        s.last_ok = datetime.now(timezone.utc).isoformat()
        write_state(repo, s)
        assert status_line(repo) is None

    def test_warns_again_when_very_stale(self, repo):
        from memgit.backup import read_state, write_state, status_line
        s = read_state(repo)
        s.last_ok = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        write_state(repo, s)
        line = status_line(repo)
        assert line and "30d ago" in line

    def test_silent_when_disabled(self, repo):
        from memgit.backup import read_state, write_state, status_line
        s = read_state(repo)
        s.disabled = True
        write_state(repo, s)
        assert status_line(repo) is None

    def test_hint_reaches_the_resume_digest(self, repo):
        assert repo.resume_context().get("durability")
