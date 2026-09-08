"""The uncommitted guard: sync ships checkpoints, so staged-only memory is invisible.

Measured 2026-09-06 on two clean containers: `memgit add` then `memgit cloud push`
answered "created (2 objects up)" while shipping none of the user's memory, and the
receiving machine reported an empty store that `fsck` called OK. Nothing errored,
so it reads as "sync is broken" rather than "you have not committed".
"""
from datetime import datetime, timezone

import pytest

from memgit.models import Mnemonic
from memgit.repo import Repository

NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)


def _repo(tmp_path) -> Repository:
    return Repository.init(tmp_path / "store")


def _m(slug: str, rule: str) -> Mnemonic:
    return Mnemonic(type_code="pj", slug=slug, timestamp=NOW, rule=rule)


def test_uncommitted_slugs_empty_on_a_clean_store(tmp_path):
    repo = _repo(tmp_path)
    assert repo.uncommitted_slugs() == []


def test_add_alone_leaves_the_slug_uncommitted(tmp_path):
    repo = _repo(tmp_path)
    repo.add(_m("staged-only", "never reached the cloud"))
    assert repo.uncommitted_slugs() == ["staged-only"]


def test_commit_clears_it(tmp_path):
    repo = _repo(tmp_path)
    repo.add(_m("staged-only", "never reached the cloud"))
    repo.commit(message="now it is a checkpoint")
    assert repo.uncommitted_slugs() == []


def test_a_modified_memory_counts_as_uncommitted_again(tmp_path):
    repo = _repo(tmp_path)
    repo.add(_m("drifts", "first value"))
    repo.commit(message="first")
    assert repo.uncommitted_slugs() == []
    repo.add(_m("drifts", "second value"))
    assert repo.uncommitted_slugs() == ["drifts"]


def test_guard_exits_when_memories_are_staged_only(tmp_path):
    from memgit.cloud.commands import _guard_uncommitted
    repo = _repo(tmp_path)
    repo.add(_m("staged-only", "never reached the cloud"))
    with pytest.raises(SystemExit) as e:
        _guard_uncommitted(repo, repo.current_thread(), allow=False)
    assert e.value.code == 1


def test_guard_allows_an_explicit_override(tmp_path):
    from memgit.cloud.commands import _guard_uncommitted
    repo = _repo(tmp_path)
    repo.add(_m("staged-only", "never reached the cloud"))
    _guard_uncommitted(repo, repo.current_thread(), allow=True)  # must not raise
