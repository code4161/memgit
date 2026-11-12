"""The memgit cloud offer: decided from local state, shown once per trigger.

Each trigger (memory count, a second machine, an export or a backup) shows at
most once per store, never while the store is logged in to memgit cloud or
linked, and never when switched off by MEMGIT_NO_SYNC_HINT or by
memgit cloud hint off. Nothing here may reach the network.
"""
import json
import socket
from datetime import datetime, timezone

import pytest
from click.testing import CliRunner

from memgit import synchint
from memgit.models import Mnemonic
from memgit.repo import Repository


def _fill(repo, n):
    for i in range(n):
        repo.add(Mnemonic(type_code='lx', slug=f'm{i}', rule=f'lesson {i}',
                          timestamp=datetime.now(timezone.utc), project='P'))
    repo.commit(message='seed', trigger='explicit')


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setenv('MEMGIT_NO_AUTOSYNC', '1')
    monkeypatch.delenv('MEMGIT_NO_SYNC_HINT', raising=False)
    monkeypatch.setattr(socket, 'gethostname', lambda: 'laptop.local')


@pytest.fixture
def repo(tmp_path):
    return Repository.init(tmp_path / 'store')


def _invoke(args, repo, monkeypatch):
    import memgit.cli as cli_mod
    monkeypatch.setattr(cli_mod, '_require_repo', lambda: repo)
    # click 8.2 and later keep stderr apart from stdout by default.
    return CliRunner().invoke(cli_mod.cli, args)


def _digest(repo, monkeypatch):
    res = _invoke(['resume', '--plain'], repo, monkeypatch)
    assert res.exit_code == 0, res.output
    return res.stdout


# ── triggers ────────────────────────────────────────────────────────────────

class TestCountTrigger:
    def test_silent_below_the_first_threshold(self, repo):
        _fill(repo, 49)
        assert synchint.pending(repo.path, 49) is None

    def test_fifty_shows_once_in_the_digest(self, repo, monkeypatch):
        _fill(repo, 50)
        first = _digest(repo, monkeypatch)
        assert '50 memories are on this machine. memgit cloud signup' in first
        assert '(14 days free, no card). Setup tips by email: memgit tips <your email>.' in first
        assert 'memgit cloud signup' not in _digest(repo, monkeypatch)

    def test_two_fifty_shows_after_fifty_has(self, repo):
        synchint.mark_shown(repo.path, 'count-50')
        assert synchint.pending(repo.path, 120) is None
        key, line = synchint.pending(repo.path, 250)
        assert key == 'count-250' and line.startswith('250 memories')

    def test_a_large_store_is_offered_once_not_twice(self, repo):
        key, _ = synchint.pending(repo.path, 400)
        assert key == 'count-250'
        synchint.mark_shown(repo.path, key)
        assert synchint.pending(repo.path, 400) is None


class TestMachineTrigger:
    def test_first_open_records_a_hashed_fingerprint(self, repo):
        assert synchint.pending(repo.path, 3) is None
        data = synchint.read_state(repo.path)
        assert data['machine'] == synchint.machine_fingerprint()
        assert 'laptop' not in json.dumps(data)

    def test_domain_suffix_is_the_same_machine(self, repo, monkeypatch):
        synchint.pending(repo.path, 3)
        monkeypatch.setattr(socket, 'gethostname', lambda: 'LAPTOP')
        assert synchint.pending(repo.path, 3) is None

    def test_a_different_machine_shows_once(self, repo, monkeypatch):
        _fill(repo, 3)
        synchint.pending(repo.path, 3)
        monkeypatch.setattr(socket, 'gethostname', lambda: 'mac-mini')
        out = _digest(repo, monkeypatch)
        assert 'opened on two machines' in out
        assert 'opened on two machines' not in _digest(repo, monkeypatch)


class TestExportAndBackupTrigger:
    def test_export_hint_goes_to_stderr_and_stdout_is_unchanged(self, repo, monkeypatch):
        _fill(repo, 3)
        res = _invoke(['export', 'm1'], repo, monkeypatch)
        assert res.exit_code == 0
        assert 'memgit cloud signup' not in res.stdout
        assert 'To have these 3 memories on your other machines' in res.stderr
        again = _invoke(['export', 'm1'], repo, monkeypatch)
        assert 'memgit cloud signup' not in again.stderr

    def test_backup_now_shows_it_and_retires_export(self, repo, monkeypatch, tmp_path):
        _fill(repo, 3)
        dest = tmp_path / 'dest'
        dest.mkdir()
        res = _invoke(['backup', 'now', '--to', str(dest)], repo, monkeypatch)
        assert res.exit_code == 0, res.output
        assert 'memgit cloud signup' in res.stdout
        assert synchint.pending(repo.path, 3, 'export') is None

    def test_mcp_resume_session_carries_the_line_once(self, repo, monkeypatch):
        pytest.importorskip('mcp')
        import asyncio
        from mcp import types
        from memgit import mcp_server
        _fill(repo, 60)
        holder = {}

        class Capture(mcp_server.Server):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                holder['s'] = self

        monkeypatch.setattr(mcp_server, 'Server', Capture)
        monkeypatch.setattr(asyncio, 'run', lambda coro: coro.close())
        mcp_server.run_server(repo.path.parent)

        def call():
            req = types.CallToolRequest(method='tools/call', params=types.CallToolRequestParams(
                name='resume_session', arguments={}))
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(
                    holder['s'].request_handlers[types.CallToolRequest](req)).root.content[0].text
            finally:
                loop.close()

        assert '60 memories are on this machine' in call()
        assert 'memgit cloud signup' not in call()


# ── suppression ─────────────────────────────────────────────────────────────

class TestSuppression:
    def test_env_switch(self, repo, monkeypatch):
        monkeypatch.setenv('MEMGIT_NO_SYNC_HINT', '1')
        assert synchint.pending(repo.path, 300) is None
        assert synchint.pending(repo.path, 300, 'export') is None

    def test_off_command_and_back_on(self, repo, monkeypatch):
        _fill(repo, 50)
        res = _invoke(['cloud', 'hint', 'off'], repo, monkeypatch)
        assert res.exit_code == 0, res.output
        assert 'memgit cloud signup' not in _digest(repo, monkeypatch)
        assert 'off' in _invoke(['cloud', 'hint'], repo, monkeypatch).stdout
        _invoke(['cloud', 'hint', 'on'], repo, monkeypatch)
        assert 'memgit cloud signup' in _digest(repo, monkeypatch)

    def test_logged_in_store_never_sees_it(self, repo):
        from memgit.cloud.state import CloudState
        CloudState(repo.path).save_creds(email='a@example.com', refresh='r')
        assert synchint.pending(repo.path, 300) is None
        assert synchint.pending(repo.path, 300, 'backup') is None

    def test_linked_store_never_sees_it(self, repo):
        from memgit.cloud.state import CloudState
        CloudState(repo.path).save_state(team_id='t', repo_id='r')
        assert synchint.pending(repo.path, 300) is None

    def test_unreadable_cloud_state_means_silence(self, repo, monkeypatch):
        from memgit.cloud import state
        monkeypatch.setattr(state.CloudState, 'link',
                            lambda self: (_ for _ in ()).throw(OSError('denied')))
        assert synchint.pending(repo.path, 300) is None

    def test_digest_cut_at_budget_does_not_use_up_the_showing(self, repo, monkeypatch):
        import memgit.cli as cli_mod
        _fill(repo, 50)
        monkeypatch.setattr(cli_mod, '_format_resume_plain', lambda ctx: 'cut')
        _digest(repo, monkeypatch)
        assert synchint.pending(repo.path, 50) is not None

    def test_the_state_lives_inside_the_store(self, repo):
        synchint.mark_shown(repo.path, 'count-50')
        assert (repo.path / synchint.STATE_FILE).is_file()
