"""The store lock must actually exclude, including between threads of one process.

Measured 2026-09-06: 3/120 concurrent runs silently lost a memory. The object was
written and readable, but the slug was absent from BOTH TOON_INDEX and HEAD's
MindState, no exception was raised, and fsck() reported clean.

Root cause: acquisition is os.open(O_CREAT|O_EXCL) followed by os.write of the
owner token, and between those two calls the lockfile exists with ZERO BYTES. The
stale-lock breaker read that empty file, computed pid = 0, skipped its liveness
check because `pid > 0` was false, and fell through to `not pid_alive` — deleting
a lock that was alive. Two writers then ran the read-modify-write of TOON_INDEX at
once and one memory was dropped.
"""
import threading
from datetime import datetime, timezone

from memgit.models import Mnemonic
from memgit.repo import Repository

NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)


def test_an_unstamped_lockfile_is_never_treated_as_stale(tmp_path):
    """A zero-byte lockfile is a lock being born, not an abandoned one."""
    repo = Repository.init(tmp_path / "store")
    lp = repo._lock_path
    lp.write_text("")           # exactly the O_EXCL-then-write window

    repo._try_break_stale_lock()

    assert lp.exists(), "an unstamped lock was broken — this is the lost-update bug"


def test_a_lock_held_by_a_dead_process_is_broken(tmp_path):
    """The breaker must still do its job when the owner is genuinely gone."""
    repo = Repository.init(tmp_path / "store")
    lp = repo._lock_path
    # PID 1 exists; a pid that cannot exist is what we need. 2**22 is above the
    # Linux default pid_max and macOS's, so os.kill raises ProcessLookupError.
    lp.write_text(f"{2**22} deadbeef 0\n")

    repo._try_break_stale_lock()

    assert not lp.exists(), "a lock owned by a dead process was not broken"


def test_release_does_not_drop_a_lock_someone_else_now_holds(tmp_path):
    """Releasing must be ownership-checked, or one broken lock cascades."""
    repo = Repository.init(tmp_path / "store")
    lp = repo._lock_path

    with repo._lock():
        # Simulate: our lock was broken and another writer took it.
        lp.write_text("99999 someoneelse 0\n")

    assert lp.exists(), "release deleted a lock belonging to another holder"
    assert "someoneelse" in lp.read_text()
    lp.unlink()


def test_concurrent_add_commit_never_loses_a_memory(tmp_path):
    """The end-to-end property: eight writers, eight memories, none lost."""
    store = Repository.init(tmp_path / "store").path
    n_writers = 8
    errors: list[str] = []

    def writer(n: int) -> None:
        try:
            # A fresh Repository per operation, exactly as mcp_server.save_memory does.
            Repository(store).add(
                Mnemonic(type_code="pj", slug=f"agent-{n}", timestamp=NOW, rule=f"fact {n}"))
            Repository(store).commit(message=f"agent {n}")
        except Exception as e:                      # pragma: no cover - diagnostic
            errors.append(f"agent-{n}: {type(e).__name__}: {e}")

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(n_writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    repo = Repository(store)
    want = {f"agent-{n}" for n in range(n_writers)}
    assert errors == []
    assert want - set(repo.get_index()) == set(), "memories missing from TOON_INDEX"
    assert want - set(repo._mindstate_map(repo.head_sha())) == set(), \
        "memories missing from HEAD's MindState"
