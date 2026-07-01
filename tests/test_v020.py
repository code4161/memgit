"""Tests for v0.2.0: resume, gc, locking, CAS auto-merge, thread merge, history scaling."""

import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from memgit.models import Mnemonic
from memgit.repo import Repository, LockTimeout


def now():
    return datetime.now(timezone.utc)


def mnem(slug, rule='a rule', priority=2, ts=None):
    return Mnemonic(
        type_code='fb', slug=slug, timestamp=ts or now(),
        rule=rule, priority=priority, tags=['t'],
    )


@pytest.fixture
def repo(tmp_path):
    return Repository.init(tmp_path)


# ── Resume ────────────────────────────────────────────────────────────────────

class TestResume:
    def test_resume_context_shape(self, repo):
        # TOON timestamps are minute-granular — space them out for recency order
        repo.add(mnem('rule-one', 'always test', ts=now() - timedelta(hours=2)))
        repo.commit('first work')
        repo.add(mnem('rule-two', 'never skip', priority=3))

        ctx = repo.resume_context()
        assert ctx['thread'] == 'main'
        assert ctx['total_memories'] == 2
        assert ctx['checkpoint_count'] == 2  # root + first work
        assert ctx['checkpoints'][0]['message'] == 'first work'
        # rule-two is staged but not committed
        assert ctx['staged']['new'] == ['rule-two']
        # critical memories always surface
        assert [m['slug'] for m in ctx['critical_memories']] == ['rule-two']
        # recency ordering: newest first
        assert ctx['recent_memories'][0]['slug'] == 'rule-two'

    def test_resume_plain_format(self, repo):
        from memgit.cli import _format_resume_plain
        repo.add(mnem('a-rule', 'do the thing', priority=3))
        repo.commit('did the thing')
        text = _format_resume_plain(repo.resume_context())
        assert '# memgit resume' in text
        assert 'did the thing' in text
        assert 'Critical rules' in text
        assert 'a-rule: do the thing' in text

    def test_resume_bounded(self, repo):
        for i in range(30):
            repo.add(mnem(f'm-{i:02d}'))
            repo.commit(f'ck {i}')
        ctx = repo.resume_context(checkpoints=5, recent=10)
        assert len(ctx['checkpoints']) == 5
        assert len(ctx['recent_memories']) == 10


# ── History scaling ───────────────────────────────────────────────────────────

class TestHistoryScaling:
    def test_chain_info_counts_and_caches(self, repo):
        for i in range(5):
            repo.add(mnem(f's-{i}'))
            repo.commit(f'c{i}')
        count, first_ts = repo.chain_info()
        assert count == 6  # root + 5
        assert first_ts is not None
        # cache file keyed to head
        cached = json.loads(repo._counts_path.read_text())
        assert cached['main']['head'] == repo.head_sha()
        assert cached['main']['count'] == 6

    def test_chain_info_recovers_from_stale_cache(self, repo):
        repo.add(mnem('x'))
        repo.commit('c')
        repo._write_counts({'main': {'head': 'bogus', 'count': 99, 'first_ts': '2020-01-01T00:00Z'}})
        count, _ = repo.chain_info()
        assert count == 2

    def test_resolve_ref_prefix_is_store_based(self, repo):
        repo.add(mnem('x'))
        sha = repo.commit('target')
        assert repo.resolve_ref(sha[:8]) == sha
        assert repo.resolve_ref('HEAD') == sha
        assert repo.resolve_ref('zzzz') is None
        # a mnemonic sha prefix must NOT resolve as a checkpoint
        mnem_sha = repo.get_index()['x']
        assert repo.resolve_ref(mnem_sha[:8]) is None

    def test_log_skip_pagination(self, repo):
        for i in range(5):
            repo.add(mnem(f's-{i}'))
            repo.commit(f'c{i}')
        page1 = repo.log(limit=2)
        page2 = repo.log(limit=2, skip=2)
        assert [c.message for c in page1] == ['c4', 'c3']
        assert [c.message for c in page2] == ['c2', 'c1']

    def test_stats_uses_cache_and_reports_disk(self, repo):
        repo.add(mnem('x'))
        repo.commit('c')
        s = repo.stats()
        assert s['checkpoint_count'] == 2
        assert s['disk_bytes'] > 0
        assert s['object_count'] > 0


# ── GC ────────────────────────────────────────────────────────────────────────

class TestGC:
    def _grow(self, repo, n=10):
        for i in range(n):
            repo.add(mnem('same-slug', rule=f'version {i}'))
            repo.commit(f'c{i}')

    def test_gc_noop_when_all_reachable(self, repo):
        self._grow(repo, 5)
        r = repo.gc()
        assert r['objects_deleted'] == 0

    def test_gc_after_squash_frees_space(self, repo):
        self._grow(repo, 10)
        before_objects, _ = repo.disk_usage()
        repo.squash(keep_last=2)
        r = repo.gc()
        assert r['objects_deleted'] > 0
        assert r['bytes_freed'] > 0
        # store still healthy
        assert repo.fsck() == []
        assert repo.get('same-slug').rule == 'version 9'
        after_objects, _ = repo.disk_usage()
        assert after_objects < before_objects

    def test_gc_dry_run_deletes_nothing(self, repo):
        self._grow(repo, 10)
        repo.squash(keep_last=2)
        before = repo.disk_usage()
        r = repo.gc(dry_run=True)
        assert r['objects_deleted'] > 0
        assert repo.disk_usage() == before

    def test_gc_preserves_staged_uncommitted(self, repo):
        self._grow(repo, 5)
        repo.add(mnem('staged-only', 'not yet committed'))
        repo.squash(keep_last=2)
        repo.gc()
        assert repo.get('staged-only').rule == 'not yet committed'

    def test_squash_archives_collapsed_history(self, repo):
        self._grow(repo, 10)
        result = repo.squash(keep_last=2)
        archive = Path(result['archive'])
        assert archive.exists()
        content = archive.read_text()
        # every squashed checkpoint left a one-line record
        assert len(content.strip().splitlines()) == result['squashed']
        assert 'c0' in content

    def test_gc_trims_reflog(self, repo):
        self._grow(repo, 10)
        repo.squash(keep_last=2)
        r = repo.gc(reflog_keep=5)
        assert r['reflog_entries_trimmed'] > 0
        reflog = repo.path / 'logs' / 'threads' / 'main'
        lines = reflog.read_text().strip().splitlines()
        assert len(lines) <= 5


# ── Locking ───────────────────────────────────────────────────────────────────

class TestLocking:
    def test_lock_is_reentrant(self, repo):
        with repo._lock():
            with repo._lock():
                assert repo._lock_path.exists()
        assert not repo._lock_path.exists()

    def test_lock_times_out_when_held_elsewhere(self, repo):
        # Simulate another live process holding the lock (our own pid = alive)
        repo._lock_path.write_text(f'{os.getpid()} {time.time():.0f}\n')
        other = Repository(repo.path)
        with pytest.raises(LockTimeout):
            with other._lock(timeout=0.3):
                pass
        repo._lock_path.unlink()

    def test_stale_lock_from_dead_pid_is_broken(self, repo):
        repo._lock_path.write_text('99999999 123\n')  # dead pid
        with repo._lock(timeout=2):
            pass  # acquired despite pre-existing lockfile
        assert not repo._lock_path.exists()

    def test_concurrent_agents_no_lost_updates(self, tmp_path):
        Repository.init(tmp_path)
        errors = []

        def agent(i):
            try:
                r = Repository(tmp_path / '.memgit')  # own instance, shared store
                r.add(mnem(f'agent-{i}', f'from agent {i}'))
                r.commit(f'agent {i} done')
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=agent, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        final = Repository(tmp_path / '.memgit')
        slugs = {m.slug for m in final.list()}
        assert slugs == {f'agent-{i}' for i in range(8)}
        assert final.fsck() == []


# ── CAS auto-merge ────────────────────────────────────────────────────────────

class TestCASMerge:
    def test_stale_index_base_triggers_auto_merge(self, repo):
        root = repo.head_sha()
        repo.add(mnem('from-agent-a', 'a work'))
        repo.commit('agent a')

        # Simulate agent B whose index was staged against the old root:
        # it knows nothing about from-agent-a.
        b_sha = repo.store.write_mnemonic(mnem('from-agent-b', 'b work'))
        repo._write_index({'from-agent-b': b_sha}, base_sha=root)

        sha = repo.commit('agent b')
        assert sha is not None
        ck = repo.store.read_checkpoint(sha)
        assert 'auto-merged' in ck.message
        assert ck.trigger == 'merge'
        slugs = {m.slug for m in repo.list()}
        assert slugs == {'from-agent-a', 'from-agent-b'}

    def test_conflict_resolves_to_newest(self, repo):
        root = repo.head_sha()
        old = now() - timedelta(hours=1)
        repo.add(mnem('shared', 'older version', ts=old))
        repo.commit('agent a')

        newer_sha = repo.store.write_mnemonic(mnem('shared', 'newer version', ts=now()))
        repo._write_index({'shared': newer_sha}, base_sha=root)
        repo.commit('agent b')
        assert repo.get('shared').rule == 'newer version'

    def test_merge_to_identical_state_is_clean_noop(self, repo):
        root = repo.head_sha()
        m = mnem('same', 'identical')
        repo.add(m)
        repo.commit('agent a')
        sha = repo.store.write_mnemonic(m)
        repo._write_index({'same': sha}, base_sha=root)
        assert repo.commit('agent b') is None
        # index base freshened so status reads clean
        assert repo.get_index_base() == repo.head_sha()


# ── Thread merge (branch-per-agent) ───────────────────────────────────────────

class TestThreadMerge:
    def test_merge_disjoint_threads(self, repo):
        repo.add(mnem('base-fact'))
        repo.commit('base')

        repo.thread_create('agent-1')
        repo.thread_switch('agent-1')
        repo.add(mnem('agent1-finding', 'found by agent 1'))
        repo.commit('agent 1 work')

        repo.thread_switch('main')
        repo.add(mnem('main-fact', 'meanwhile on main'))
        repo.commit('main work')

        sha, conflicts, diff = repo.merge_thread('agent-1')
        assert sha is not None
        assert conflicts == []
        slugs = {m.slug for m in repo.list()}
        assert slugs == {'base-fact', 'agent1-finding', 'main-fact'}
        assert 'agent1-finding' in diff.added

    def test_merge_conflict_newest_wins(self, repo):
        old = now() - timedelta(hours=1)
        repo.add(mnem('hot-slug', 'original', ts=old - timedelta(hours=1)))
        repo.commit('base')

        repo.thread_create('agent-1')
        repo.thread_switch('agent-1')
        repo.add(mnem('hot-slug', 'agent version (newer)', ts=now()))
        repo.commit('agent edit')

        repo.thread_switch('main')
        repo.add(mnem('hot-slug', 'main version (older)', ts=old))
        repo.commit('main edit')

        sha, conflicts, _ = repo.merge_thread('agent-1')
        assert conflicts == ['hot-slug']
        assert repo.get('hot-slug').rule == 'agent version (newer)'

    def test_merge_up_to_date(self, repo):
        repo.add(mnem('x'))
        repo.commit('c')
        repo.thread_create('agent-1')
        sha, conflicts, _ = repo.merge_thread('agent-1')
        assert sha is None  # identical states → nothing to merge

    def test_merge_missing_thread_raises(self, repo):
        with pytest.raises(ValueError):
            repo.merge_thread('no-such-thread')

    def test_edit_beats_delete(self, repo):
        repo.add(mnem('keep-me', 'v1'))
        repo.commit('base')

        repo.thread_create('agent-1')
        repo.thread_switch('agent-1')
        repo.add(mnem('keep-me', 'v2 edited', ts=now()))
        repo.commit('agent edits')

        repo.thread_switch('main')
        repo.remove('keep-me')
        repo.commit('main deletes')

        repo.merge_thread('agent-1')
        assert repo.get('keep-me').rule == 'v2 edited'


# ── AI-operator surface ───────────────────────────────────────────────────────

class TestAIOperator:
    def test_maintenance_hint_absent_when_healthy(self, repo):
        repo.add(mnem('x'))
        repo.commit('c')
        assert repo.maintenance_hint() is None
        assert repo.resume_context()['maintenance'] is None

    def test_maintenance_hint_on_long_history(self, repo, monkeypatch):
        monkeypatch.setattr(Repository, 'MAINTENANCE_CHECKPOINTS', 5)
        for i in range(8):
            repo.add(mnem('x', rule=f'v{i}'))
            repo.commit(f'c{i}')
        hint = repo.maintenance_hint()
        assert hint and 'memgit gc' in hint
        # and it reaches the AI through the resume digest
        from memgit.cli import _format_resume_plain
        assert 'Maintenance needed' in _format_resume_plain(repo.resume_context())

    def test_gc_json_output(self, repo, monkeypatch):
        from click.testing import CliRunner
        from memgit.cli import cli as cli_root
        repo.add(mnem('x'))
        repo.commit('c')
        monkeypatch.chdir(repo.path.parent)  # so Repository.find() hits THIS store
        result = CliRunner().invoke(cli_root, ['gc', '--dry-run', '--json'])
        # command must emit exactly one JSON object
        data = json.loads(result.output)
        assert data['dry_run'] is True
        assert 'objects_deleted' in data


# ── Agent identity ────────────────────────────────────────────────────────────

class TestAgentIdentity:
    def test_memgit_author_env(self, repo, monkeypatch):
        monkeypatch.setenv('MEMGIT_AUTHOR', 'researcher-7')
        repo.add(mnem('x'))
        sha = repo.commit('by agent')
        assert repo.store.read_checkpoint(sha).author == 'researcher-7'
