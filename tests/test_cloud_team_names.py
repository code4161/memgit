"""A teammate who signs up and then joins an invite holds two teams named "personal".

Measured 2026-11-12 against a local API: `memgit cloud link personal/memory`
took the first match, linked the teammate to their own empty repo, and every
sync after that said "up-to-date" while none of the team's memory arrived.
"""
import pytest

pytest.importorskip('nacl')

from memgit.cloud import commands


class _State:
    def __init__(self):
        self.saved = {}
        self.creds = {}

    def cache_keys_allowed(self):
        return True

    def save_creds(self, **kw):
        self.saved.update(kw)


TEAMS = [
    ({'id': '6f963192aaaa'}, b'k1' * 16, 'personal', 'owner'),
    ({'id': '4be4512bbbbb'}, b'k2' * 16, 'personal', 'member'),
    ({'id': '99887766cccc'}, b'k3' * 16, 'acme', 'member'),
]


@pytest.fixture
def teams(monkeypatch):
    monkeypatch.setattr(commands, '_my_teams', lambda cstate, api: TEAMS)


def test_an_ambiguous_team_name_is_refused_with_the_choices(teams, capsys):
    with pytest.raises(SystemExit):
        commands._team_by_name(_State(), None, 'personal')
    out = capsys.readouterr().out
    assert '6f963192' in out and '4be4512b' in out


def test_a_team_can_be_named_by_its_id_prefix(teams):
    team, key = commands._team_by_name(_State(), None, '4be4512b')
    assert team['id'] == '4be4512bbbbb' and key == b'k2' * 16


def test_a_unique_name_still_works(teams):
    team, _ = commands._team_by_name(_State(), None, 'acme')
    assert team['id'] == '99887766cccc'


def test_link_choices_name_a_shared_name_by_id(teams, monkeypatch):
    class Api:
        def team_detail(self, team_id):
            return {'repos': []}
    choices = commands._repo_choices(_State(), Api())
    assert choices == ['6f963192/memory', '4be4512b/memory', 'acme/memory']
