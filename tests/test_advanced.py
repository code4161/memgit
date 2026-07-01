"""Tests for squash, stats, flat export, and token counting."""

import pytest
from datetime import datetime, timezone
from pathlib import Path

from memgit.models import Mnemonic
from memgit.repo import Repository
from memgit.tokens import count_tokens, all_memories_tokens, memory_tokens


def now():
    return datetime.now(timezone.utc)


def make_mnemonic(slug='test-rule', rule='do not break things', type_code='fb', priority=2):
    return Mnemonic(
        type_code=type_code,
        slug=slug,
        timestamp=now(),
        rule=rule,
        why='stability',
        tags=['testing'],
        priority=priority,
    )


# ── Token counting ─────────────────────────────────────────────────────────────

class TestTokenCounting:
    def test_empty_string(self):
        assert count_tokens('') == 0

    def test_single_word(self):
        assert count_tokens('hello') >= 1

    def test_longer_text_is_more_tokens(self):
        short = count_tokens('one two three')
        long = count_tokens('one two three four five six seven eight nine ten')
        assert long > short

    def test_memory_tokens_positive(self):
        m = make_mnemonic(rule='Never mock the database in tests')
        assert memory_tokens(m) > 0

    def test_all_memories_tokens_sums(self):
        mnems = [make_mnemonic(f'rule-{i}', f'rule number {i} says do something') for i in range(5)]
        total = all_memories_tokens(mnems)
        individual = sum(memory_tokens(m) for m in mnems)
        assert total == individual


# ── Stats ──────────────────────────────────────────────────────────────────────

class TestStats:
    @pytest.fixture
    def repo_with_memories(self, tmp_path):
        repo = Repository.init(tmp_path)
        for i in range(10):
            priority = 3 if i == 0 else (2 if i < 7 else 1)
            m = make_mnemonic(
                slug=f'memory-{i}',
                rule=f'Rule {i}: always do the right thing in context {i}',
                type_code=['fb', 'us', 'pj', 'rf', 'cn', 'lx'][i % 6],
                priority=priority,
            )
            repo.add(m)
        repo.commit('add ten memories')
        return repo

    def test_stats_returns_correct_total(self, repo_with_memories):
        s = repo_with_memories.stats()
        assert s['total'] == 10

    def test_stats_full_tokens_positive(self, repo_with_memories):
        s = repo_with_memories.stats()
        assert s['full_tokens'] > 0

    def test_stats_search_fewer_than_full(self, repo_with_memories):
        s = repo_with_memories.stats()
        # Search top-8 should cost less than full load of 10
        assert s['avg_search_tokens'] <= s['full_tokens']

    def test_stats_reduction_percent(self, repo_with_memories):
        s = repo_with_memories.stats()
        assert 0 <= s['reduction_pct'] <= 100

    def test_stats_checkpoint_count(self, repo_with_memories):
        s = repo_with_memories.stats()
        assert s['checkpoint_count'] >= 1

    def test_stats_empty_store(self, tmp_path):
        repo = Repository.init(tmp_path)
        s = repo.stats()
        assert s.get('total', 0) == 0


# ── Squash ────────────────────────────────────────────────────────────────────

class TestSquash:
    @pytest.fixture
    def repo_with_history(self, tmp_path):
        repo = Repository.init(tmp_path)
        # Create 10 checkpoints
        for i in range(10):
            repo.add(make_mnemonic(slug=f'rule-{i}', rule=f'rule {i}'))
            repo.commit(f'checkpoint {i}')
        return repo

    def test_squash_dry_run_no_change(self, repo_with_history):
        before = len(repo_with_history.log(limit=100))
        result = repo_with_history.squash(keep_last=5, dry_run=True)
        after = len(repo_with_history.log(limit=100))
        assert after == before  # dry run must not change anything
        assert result['dry_run'] is True
        assert result['squashed'] > 0

    def test_squash_reduces_history(self, repo_with_history):
        before = len(repo_with_history.log(limit=100))
        result = repo_with_history.squash(keep_last=5, dry_run=False)
        after = len(repo_with_history.log(limit=100))
        assert result['squashed'] > 0
        assert after < before

    def test_squash_preserves_memories(self, repo_with_history):
        # All 10 memories should still be accessible after squash
        result = repo_with_history.squash(keep_last=3, dry_run=False)
        assert repo_with_history.get('rule-0') is not None
        assert repo_with_history.get('rule-9') is not None

    def test_squash_keep_last_respects_limit(self, repo_with_history):
        repo_with_history.squash(keep_last=4, dry_run=False)
        remaining = len(repo_with_history.log(limit=100))
        # Should have at most keep_last + 1 (the baseline) checkpoints
        assert remaining <= 5

    def test_squash_noop_on_small_history(self, tmp_path):
        repo = Repository.init(tmp_path)
        repo.add(make_mnemonic())
        repo.commit('only one')
        result = repo.squash(keep_last=5)
        assert result['squashed'] == 0


# ── Flat memories/ export ─────────────────────────────────────────────────────

class TestFlatExport:
    @pytest.fixture
    def repo_with_memories(self, tmp_path):
        repo = Repository.init(tmp_path)
        repo.add(make_mnemonic('no-db-mock', 'Never mock the database', 'lx'))
        repo.add(make_mnemonic('terse-responses', 'Keep responses short', 'fb'))
        repo.commit('initial memories')
        return repo

    def test_write_flat_creates_files(self, repo_with_memories):
        repo_with_memories.write_flat()
        mdir = repo_with_memories.memories_dir
        files = list(mdir.glob('*.toon'))
        assert len(files) == 2

    def test_flat_files_named_by_slug(self, repo_with_memories):
        repo_with_memories.write_flat()
        mdir = repo_with_memories.memories_dir
        slugs = {f.stem for f in mdir.glob('*.toon')}
        assert 'no-db-mock' in slugs
        assert 'terse-responses' in slugs

    def test_flat_file_readable(self, repo_with_memories):
        repo_with_memories.write_flat()
        mdir = repo_with_memories.memories_dir
        content = (mdir / 'no-db-mock.toon').read_text()
        assert 'Never mock the database' in content

    def test_import_flat_roundtrip(self, repo_with_memories, tmp_path):
        # Export from source repo
        repo_with_memories.write_flat()
        src_mdir = repo_with_memories.memories_dir

        # Create a new repo and import from the flat files
        dest = tmp_path / 'dest-store'
        dest.mkdir()
        dest_repo = Repository.init(dest)
        # Copy flat files to dest
        dest_mdir = dest_repo.memories_dir
        for f in src_mdir.glob('*.toon'):
            (dest_mdir / f.name).write_text(f.read_text())
        count = dest_repo.import_flat()

        assert count == 2
        assert dest_repo.get('no-db-mock') is not None
        assert dest_repo.get('terse-responses') is not None

    def test_write_flat_removes_deleted_memories(self, repo_with_memories):
        repo_with_memories.write_flat()
        repo_with_memories.remove('no-db-mock')
        repo_with_memories.commit('removed')
        repo_with_memories.write_flat()
        mdir = repo_with_memories.memories_dir
        slugs = {f.stem for f in mdir.glob('*.toon')}
        assert 'no-db-mock' not in slugs
        assert 'terse-responses' in slugs
