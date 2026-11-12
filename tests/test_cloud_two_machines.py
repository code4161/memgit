"""Two stores syncing through one cloud repo must end up holding the same memory.

Measured 2026-11-11 against the live service: after both machines edited the
same memory in the same minute, every sync on each side made a new merge
checkpoint, each push replaced the other machine's head, and the two stores
disagreed about that memory for good. Nothing tested two machines before this
file; the fake below stands in for the HTTP API and keeps the real encryption,
object verification and ref versioning.
"""
from datetime import datetime, timezone

import pytest

pytest.importorskip("nacl")

from memgit.cloud.client import RefConflict
from memgit.cloud.state import CloudState
from memgit.cloud.sync import SyncEngine
from memgit.models import Mnemonic
from memgit.repo import Repository

KEY = bytes(range(32))
SAME_MINUTE = datetime(2026, 11, 11, 8, 33, tzinfo=timezone.utc)


class FakeCloud:
    def __init__(self):
        self.objects: dict[str, str] = {}
        self.refs: dict[str, dict] = {}

    def list_refs(self, repo_id):
        return list(self.refs.values())

    def put_ref(self, repo_id, ref_id, name_enc, value_enc, expected_version):
        current = self.refs.get(ref_id, {}).get("version", 0)
        if current != expected_version:
            raise RefConflict({"current_version": current})
        self.refs[ref_id] = {"id": ref_id, "name_enc": name_enc,
                             "value_enc": value_enc, "version": current + 1}
        return self.refs[ref_id]

    def missing_objects(self, repo_id, ids):
        return [i for i in ids if i not in self.objects]

    def upload_objects(self, repo_id, objects):
        for o in objects:
            self.objects[o["id"]] = o["data"]
        return len(objects)

    def get_objects(self, repo_id, ids):
        return [{"id": i, "data": self.objects[i]} for i in ids if i in self.objects]


class Machine:
    def __init__(self, tmp_path, name, cloud, monkeypatch):
        monkeypatch.setenv("MEMGIT_NO_AUTOSYNC", "1")
        self.repo = Repository.init(tmp_path / name)
        self.engine = SyncEngine(self.repo, cloud, CloudState(self.repo.path), KEY, "repo")

    def save(self, slug, rule, when=SAME_MINUTE):
        self.repo.add(Mnemonic(type_code="cn", slug=slug, timestamp=when, rule=rule))
        self.repo.commit(message=f"save {slug}")

    def sync(self):
        return self.engine.sync("main")

    def rules(self):
        return {m.slug: m.rule for m in self.repo.list()}


@pytest.fixture
def pair(tmp_path, monkeypatch):
    cloud = FakeCloud()
    a = Machine(tmp_path, "a", cloud, monkeypatch)
    a.sync()
    b = Machine(tmp_path, "b", cloud, monkeypatch)
    b.sync()
    return a, b


def test_a_save_on_one_machine_reaches_the_other(pair):
    a, b = pair
    a.save("deploy-day", "Deploys happen on Tuesday")
    a.sync()
    b.sync()
    assert b.rules() == a.rules() == {"deploy-day": "Deploys happen on Tuesday"}


def test_offline_saves_on_both_machines_are_all_kept(pair):
    a, b = pair
    a.save("only-a", "from a")
    b.save("only-b", "from b")
    a.sync(); b.sync(); a.sync()
    assert a.rules() == b.rules() == {"only-a": "from a", "only-b": "from b"}


def test_the_same_memory_edited_on_both_machines_converges(pair):
    a, b = pair
    a.save("shared", "a's version")
    b.save("shared", "b's version")
    a.sync(); b.sync(); a.sync(); b.sync()
    assert a.rules() == b.rules()
    assert a.repo.head_sha() == b.repo.head_sha()


def test_converged_machines_stop_making_merge_checkpoints(pair):
    a, b = pair
    a.save("shared", "a's version")
    b.save("shared", "b's version")
    a.sync(); b.sync(); a.sync(); b.sync()
    head = a.repo.head_sha()
    for _ in range(3):
        pulled, pushed = a.sync()
        assert (pulled.action, pushed.action) == ("up-to-date", "up-to-date")
        pulled, pushed = b.sync()
        assert (pulled.action, pushed.action) == ("up-to-date", "up-to-date")
    assert a.repo.head_sha() == b.repo.head_sha() == head


def test_the_later_edit_wins_when_the_timestamps_differ(pair):
    a, b = pair
    a.save("shared", "older", when=datetime(2026, 11, 11, 8, 30, tzinfo=timezone.utc))
    b.save("shared", "newer", when=datetime(2026, 11, 11, 8, 40, tzinfo=timezone.utc))
    a.sync(); b.sync(); a.sync(); b.sync()
    assert a.rules() == b.rules() == {"shared": "newer"}


def test_a_delete_on_one_machine_after_they_agree_reaches_the_other(pair):
    a, b = pair
    a.save("keep", "stays")
    a.save("drop", "goes")
    a.sync(); b.sync()
    b.repo.remove("drop")
    b.repo.commit(message="remove drop")
    b.sync(); a.sync()
    assert a.rules() == b.rules() == {"keep": "stays"}


def test_a_pulled_rule_with_triggers_gates_without_a_local_save(pair):
    """Measured 2026-11-12: the gate reads only cache/triggers.json, which a
    commit rebuilt and a fast-forward pull did not."""
    from memgit.gate import read_trigger_cache
    a, b = pair
    a.repo.add(Mnemonic(type_code='cn', slug='no-prod-push', timestamp=SAME_MINUTE, priority=3,
                        rule='never push to prod', triggers=[{'command': 'git push .*prod'}]))
    a.repo.commit(message='rule')
    a.sync()
    b.sync()
    assert [r['slug'] for r in read_trigger_cache(b.repo)] == ['no-prod-push']
