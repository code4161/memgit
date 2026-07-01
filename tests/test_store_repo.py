"""Tests for object store and repository operations."""

import pytest
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from memgit.models import Mnemonic, MindState, MindStateEntry, Checkpoint, DiffSummary
from memgit.store import ObjectStore
from memgit.repo import Repository


def now():
    return datetime.now(timezone.utc)


def make_mnemonic(slug='test-rule', rule='do not break things', type_code='fb'):
    return Mnemonic(
        type_code=type_code,
        slug=slug,
        timestamp=now(),
        rule=rule,
        why='stability',
        tags=['testing'],
    )


# ── ObjectStore ───────────────────────────────────────────────────────────────

class TestObjectStore:
    @pytest.fixture
    def store(self, tmp_path):
        (tmp_path / 'objects').mkdir()
        return ObjectStore(tmp_path)

    def test_mnemonic_write_read_roundtrip(self, store):
        m = make_mnemonic()
        sha = store.write_mnemonic(m)
        assert len(sha) == 64
        assert store.exists(sha)

        m2 = store.read_mnemonic(sha)
        assert m2.slug == m.slug
        assert m2.rule == m.rule
        assert m2.why == m.why
        assert m2.sha == sha

    def test_same_mnemonic_same_sha(self, store):
        m1 = make_mnemonic()
        m2 = make_mnemonic()
        # Same content → same SHA
        sha1 = store.mnemonic_sha(m1)
        sha2 = store.mnemonic_sha(m2)
        assert sha1 == sha2

    def test_different_content_different_sha(self, store):
        m1 = make_mnemonic(rule='rule one')
        m2 = make_mnemonic(rule='rule two')
        assert store.mnemonic_sha(m1) != store.mnemonic_sha(m2)

    def test_mindstate_write_read(self, store):
        m = make_mnemonic()
        mnem_sha = store.write_mnemonic(m)

        ms = MindState(timestamp=now(), entries=[MindStateEntry(slug='test-rule', mnem_sha=mnem_sha)])
        ms_sha = store.write_mindstate(ms)
        assert store.exists(ms_sha)

        ms2 = store.read_mindstate(ms_sha)
        assert ms2.count == 1
        assert ms2.entries[0].slug == 'test-rule'
        assert ms2.entries[0].mnem_sha == mnem_sha

    def test_checkpoint_write_read(self, store):
        ms = MindState(timestamp=now(), entries=[])
        ms_sha = store.write_mindstate(ms)

        ck = Checkpoint(
            mindstate_sha=ms_sha,
            timestamp=now(),
            trigger='explicit',
            message='test checkpoint',
            author='test',
            session_id='sess-1',
            parent_sha=None,
            diff_summary=DiffSummary(added=['new-thing']),
        )
        ck_sha = store.write_checkpoint(ck)
        assert store.exists(ck_sha)

        ck2 = store.read_checkpoint(ck_sha)
        assert ck2.message == 'test checkpoint'
        assert ck2.trigger == 'explicit'
        assert ck2.parent_sha is None
        assert 'new-thing' in ck2.diff_summary.added
        assert ck2.sha == ck_sha

    def test_idempotent_writes(self, store):
        m = make_mnemonic()
        sha1 = store.write_mnemonic(m)
        sha2 = store.write_mnemonic(m)
        assert sha1 == sha2
        assert store.object_count() == 1


# ── Repository ────────────────────────────────────────────────────────────────

class TestRepository:
    @pytest.fixture
    def repo(self, tmp_path):
        return Repository.init(tmp_path)

    def test_init_creates_structure(self, tmp_path):
        repo = Repository.init(tmp_path)
        assert (tmp_path / '.memgit').is_dir()
        assert (tmp_path / '.memgit' / 'objects').is_dir()
        assert (tmp_path / '.memgit' / 'refs' / 'threads' / 'main').exists()
        assert (tmp_path / '.memgit' / 'HEAD').exists()
        assert (tmp_path / '.memgit' / 'TOON_INDEX').exists()

    def test_init_creates_root_checkpoint(self, repo):
        head = repo.head_sha()
        assert head is not None
        ck = repo.store.read_checkpoint(head)
        assert ck.message == 'Initial checkpoint'
        assert ck.parent_sha is None

    def test_add_and_get(self, repo):
        m = make_mnemonic()
        sha = repo.add(m)
        assert sha is not None

        m2 = repo.get('test-rule')
        assert m2 is not None
        assert m2.slug == 'test-rule'
        assert m2.rule == m.rule

    def test_commit_creates_checkpoint(self, repo):
        repo.add(make_mnemonic('rule-a', 'never do this'))
        repo.add(make_mnemonic('rule-b', 'always do that'))

        sha = repo.commit(message='Added two rules')
        assert sha is not None

        # log should show 2 checkpoints (root + this one)
        history = repo.log(limit=5)
        assert len(history) == 2
        assert history[0].message == 'Added two rules'
        assert history[0].sha == sha

    def test_commit_noop_when_unchanged(self, repo):
        repo.add(make_mnemonic())
        sha1 = repo.commit()
        sha2 = repo.commit()  # nothing changed
        assert sha2 is None

    def test_diff(self, repo):
        repo.add(make_mnemonic('rule-a', 'rule text'))
        sha1 = repo.commit()

        repo.add(make_mnemonic('rule-b', 'new rule'))
        sha2 = repo.commit()

        d = repo.diff(sha1, sha2)
        assert 'rule-b' in d.added
        assert 'rule-a' in d.unchanged

    def test_list(self, repo):
        repo.add(make_mnemonic('rule-x'))
        repo.add(make_mnemonic('rule-y'))
        mnemonics = repo.list()
        slugs = [m.slug for m in mnemonics]
        assert 'rule-x' in slugs
        assert 'rule-y' in slugs

    def test_remove(self, repo):
        repo.add(make_mnemonic('will-be-removed'))
        assert repo.get('will-be-removed') is not None
        repo.remove('will-be-removed')
        assert repo.get('will-be-removed') is None

    def test_find_repo(self, tmp_path):
        repo = Repository.init(tmp_path)
        subdir = tmp_path / 'deep' / 'nested'
        subdir.mkdir(parents=True)
        found = Repository.find(subdir)
        assert found is not None
        assert found.path == repo.path

    def test_fsck_clean(self, repo):
        repo.add(make_mnemonic())
        repo.commit()
        errors = repo.fsck()
        assert errors == []

    def test_thread_create_and_switch(self, repo):
        repo.add(make_mnemonic('shared-rule'))
        repo.commit()

        t = repo.thread_create('work/client')
        assert t.name == 'work/client'

        repo.thread_switch('work/client')
        assert repo.current_thread() == 'work/client'

        # Add something only on this thread
        repo.add(make_mnemonic('client-specific'))
        repo.commit()

        # Switch back — client-specific should not be there
        repo.thread_switch('main')
        assert repo.get('client-specific') is None
        assert repo.get('shared-rule') is not None
