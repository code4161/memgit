"""Tests for object store and repository operations."""

import pytest
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from memgit.models import Mnemonic, MindState, MindStateEntry, Checkpoint, DiffSummary
from memgit import store
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

    def test_resolve_ref(self, repo):
        repo.add(make_mnemonic('rule-a'))
        sha1 = repo.commit()
        repo.add(make_mnemonic('rule-b'))
        sha2 = repo.commit()

        assert repo.resolve_ref('HEAD') == sha2
        assert repo.resolve_ref('HEAD~1') == sha1
        assert repo.resolve_ref(sha1[:8]) == sha1
        assert repo.resolve_ref('nonexistent') is None

    def test_rollback(self, repo):
        repo.add(make_mnemonic('rule-a', 'original rule'))
        sha1 = repo.commit()

        repo.add(make_mnemonic('rule-b', 'a mistake'))
        repo.commit()

        # dry run: reports the removal, changes nothing
        new_sha, d = repo.rollback('HEAD~1', dry_run=True)
        assert new_sha is None
        assert 'rule-b' in d.removed
        assert repo.get('rule-b') is not None

        # real rollback: rule-b gone, rule-a intact, history preserved
        new_sha, d = repo.rollback(sha1)
        assert new_sha is not None
        assert repo.get('rule-b') is None
        assert repo.get('rule-a').rule == 'original rule'
        history = repo.log(limit=10)
        assert history[0].sha == new_sha
        assert history[0].trigger == 'rollback'
        assert len(history) == 4  # root + 2 commits + rollback

    def test_rollback_bad_ref(self, repo):
        with pytest.raises(ValueError):
            repo.rollback('does-not-exist')

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


class TestObjectCache:
    """The parsed-object cache added 2026-09-06.

    `Repository.list()` re-read and re-parsed every object on every call, so a
    session that searched five times paid the full corpus load five times
    (measured on a 4,075-memory store: 1,040 ms per call, of which 718 ms was
    parsing). Objects are content-addressed, so a SHA-keyed cache can never
    serve stale content — but it must never hand out the instance it keeps,
    because callers mutate what they are given and then re-save it.
    """

    def setup_method(self):
        store.clear_object_cache()

    def teardown_method(self):
        store.clear_object_cache()

    def test_second_read_returns_equal_content(self, tmp_path):
        s = ObjectStore(tmp_path)
        sha = s.write_mnemonic(make_mnemonic(slug='cached-one', rule='first'))
        a = s.read_mnemonic(sha)
        b = s.read_mnemonic(sha)
        assert a.slug == b.slug == 'cached-one'
        assert a.rule == b.rule == 'first'
        assert a.sha == b.sha == sha

    def test_cache_never_hands_out_the_same_instance(self, tmp_path):
        s = ObjectStore(tmp_path)
        sha = s.write_mnemonic(make_mnemonic(slug='distinct-instances'))
        assert s.read_mnemonic(sha) is not s.read_mnemonic(sha)

    def test_mutating_a_result_does_not_poison_the_cache(self, tmp_path):
        s = ObjectStore(tmp_path)
        sha = s.write_mnemonic(make_mnemonic(slug='mutate-me', rule='original'))
        first = s.read_mnemonic(sha)
        first.rule = 'clobbered'
        first.slug = 'renamed'
        first.unverified = True
        second = s.read_mnemonic(sha)
        assert second.rule == 'original'
        assert second.slug == 'mutate-me'
        assert second.unverified is False

    def test_mutating_result_lists_does_not_poison_the_cache(self, tmp_path):
        s = ObjectStore(tmp_path)
        sha = s.write_mnemonic(make_mnemonic(slug='list-fields'))
        first = s.read_mnemonic(sha)
        first.tags.append('injected')
        first.related.append('some-other-slug')
        first.supersedes.append('an-old-slug')
        second = s.read_mnemonic(sha)
        assert second.tags == ['testing']
        assert second.related == []
        assert second.supersedes == []

    def test_editing_a_memory_is_a_new_sha_so_the_cache_misses(self, tmp_path):
        s = ObjectStore(tmp_path)
        sha_a = s.write_mnemonic(make_mnemonic(slug='evolves', rule='before'))
        s.read_mnemonic(sha_a)
        sha_b = s.write_mnemonic(make_mnemonic(slug='evolves', rule='after'))
        assert sha_a != sha_b
        assert s.read_mnemonic(sha_a).rule == 'before'
        assert s.read_mnemonic(sha_b).rule == 'after'

    def test_abbreviated_sha_is_not_cached_under_the_abbreviation(self, tmp_path):
        s = ObjectStore(tmp_path)
        sha = s.write_mnemonic(make_mnemonic(slug='abbrev', rule='full only'))
        s.read_mnemonic(sha[:10])
        assert sha[:10] not in store._OBJECT_CACHE
        assert sha in store._OBJECT_CACHE or s.read_mnemonic(sha).rule == 'full only'

    def test_clear_object_cache_empties_it(self, tmp_path):
        s = ObjectStore(tmp_path)
        sha = s.write_mnemonic(make_mnemonic(slug='clearable'))
        s.read_mnemonic(sha)
        assert store._OBJECT_CACHE
        store.clear_object_cache()
        assert not store._OBJECT_CACHE
        assert s.read_mnemonic(sha).slug == 'clearable'

    def test_repository_list_is_served_from_the_cache(self, tmp_path):
        repo = Repository.init(tmp_path)
        for i in range(5):
            repo.add(make_mnemonic(slug=f'listed-{i}', rule=f'rule {i}'))
        first = {m.slug: m.rule for m in repo.list()}
        second = {m.slug: m.rule for m in repo.list()}
        assert first == second
        assert len(first) == 5
        # and the objects handed out are still independent copies
        a, b = repo.list(), repo.list()
        a[0].rule = 'mutated in place'
        assert b[0].rule != 'mutated in place'
        assert repo.list()[0].rule != 'mutated in place'


class TestCorpusSnapshot:
    """The shared pre-parsed corpus pool added 2026-09-06.

    The in-process cache fixes repeat calls; it does nothing for a NEW process,
    and every Claude session starts one. A cold `list()` on a 4,075-memory
    store measured 1,486 ms because it opened and parsed 4,075 gzip files. The
    pool makes that one read of one file (measured 48 ms). It is keyed by SHA,
    so it needs no invalidation: a row for an edited memory belongs to a SHA
    nobody asks for any more.
    """

    def setup_method(self):
        store.clear_object_cache()

    def teardown_method(self):
        store.clear_object_cache()

    def _repo_with(self, tmp_path, n=4):
        repo = Repository.init(tmp_path)
        for i in range(n):
            repo.add(make_mnemonic(slug=f'pooled-{i}', rule=f'rule {i}'))
        return repo

    def test_cold_list_writes_the_pool(self, tmp_path):
        repo = self._repo_with(tmp_path)
        store.clear_object_cache()
        repo.list()
        assert repo._snapshot_path().is_file()

    def test_pool_serves_a_process_that_cannot_read_the_objects(self, tmp_path):
        """The load path really comes from the pool, not from the object store."""
        repo = self._repo_with(tmp_path)
        store.clear_object_cache()
        repo.list()                      # builds the pool
        store.clear_object_cache()       # a fresh process
        objects = repo.path / 'objects'
        objects.rename(repo.path / 'objects-moved-aside')
        try:
            slugs = sorted(m.slug for m in repo.list())
            assert slugs == ['pooled-0', 'pooled-1', 'pooled-2', 'pooled-3']
        finally:
            (repo.path / 'objects-moved-aside').rename(objects)

    def test_pool_entries_are_still_caller_safe_copies(self, tmp_path):
        repo = self._repo_with(tmp_path)
        store.clear_object_cache()
        repo.list()
        store.clear_object_cache()
        first = repo.list()
        first[0].rule = 'clobbered'
        first[0].tags.append('injected')
        second = {m.slug: m for m in repo.list()}
        assert second[first[0].slug].rule != 'clobbered'
        assert 'injected' not in second[first[0].slug].tags

    def test_a_corrupt_pool_is_ignored_not_fatal(self, tmp_path):
        repo = self._repo_with(tmp_path)
        store.clear_object_cache()
        repo.list()
        repo._snapshot_path().write_text('{ this is not json', encoding='utf-8')
        store.clear_object_cache()
        assert len(repo.list()) == 4

    def test_a_missing_pool_is_ignored_not_fatal(self, tmp_path):
        repo = self._repo_with(tmp_path)
        store.clear_object_cache()
        repo._snapshot_path().unlink(missing_ok=True)
        assert len(repo.list()) == 4

    def test_an_edited_memory_is_picked_up_and_the_pool_is_rewritten(self, tmp_path):
        repo = self._repo_with(tmp_path)
        store.clear_object_cache()
        repo.list()
        repo.add(make_mnemonic(slug='pooled-0', rule='edited after the pool was written'))
        store.clear_object_cache()
        by_slug = {m.slug: m.rule for m in repo.list()}
        assert by_slug['pooled-0'] == 'edited after the pool was written'
        # the rewrite means a later cold process sees the edit without the objects
        store.clear_object_cache()
        objects = repo.path / 'objects'
        objects.rename(repo.path / 'objects-moved-aside')
        try:
            again = {m.slug: m.rule for m in repo.list()}
            assert again['pooled-0'] == 'edited after the pool was written'
        finally:
            (repo.path / 'objects-moved-aside').rename(objects)
