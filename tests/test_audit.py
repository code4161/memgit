"""Tests for the store audit.

Every case here is a shape measured on the live store on 2026-09-20, not an
invented one. The counts are the real counts, because the direction a repair
heals in depends on them and a made-up ratio would not have caught the bug
these tests exist to pin: healing toward the bigger pile keeps the dead label.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest

from memgit import audit as A
from memgit.models import Mnemonic


def _m(slug, project=None, days_ago=0, supersedes=None, related=None):
    return Mnemonic(
        type_code='lx',
        slug=slug,
        timestamp=datetime.now(timezone.utc) - timedelta(days=days_ago),
        rule='r',
        project=project,
        supersedes=supersedes or [],
        related=related or [],
    )


class _Repo:
    def __init__(self, mems):
        self._mems = mems

    def list(self):
        return list(self._mems)


def _p(*parts):
    return os.sep + os.sep.join(parts)


# label_splits

def test_split_heals_toward_the_live_directory_not_the_bigger_pile():
    """The measured case that makes count the wrong signal.

    Downloads-log-report holds 1,819 memories and its directory is gone.
    log-report holds 18 and is where the work runs. Healing by count would
    strand the project a second time.
    """
    counts = {'Downloads-log-report': 1819, 'log-report': 18}
    live = {'log-report': _p('Users', 'hari', 'log-report')}
    (split,) = A.label_splits(counts, live)
    assert split['keep'] == 'log-report'
    assert split['drop'] == 'Downloads-log-report'
    assert split['keep_is_live'] is True


def test_typo_split_heals_toward_the_spelled_label():
    counts = {'masagrti-Networking-pro': 75, 'Masgarti-Networking-pro': 18}
    live = {'Masgarti-Networking-pro': _p('Users', 'hari', 'Masgarti-Networking-pro')}
    (split,) = A.label_splits(counts, live)
    assert split['kind'] == 'typo'
    assert split['keep'] == 'Masgarti-Networking-pro'


def test_short_label_split_heals_toward_the_workspace_label():
    counts = {'FittyMe': 98, 'Freelance-FittyMe': 234}
    live = {'Freelance-FittyMe': _p('Users', 'hari', 'Freelance', 'FittyMe')}
    (split,) = A.label_splits(counts, live)
    assert split['kind'] == 'short-label'
    assert split['keep'] == 'Freelance-FittyMe'


def test_munge_split_heals_toward_the_dash_form_even_when_it_is_smaller():
    """Only the dash form is reachable from both label derivations.

    Claude Code does not keep the _ character, so that form of the label can
    never come from a projects directory name. The filesystem does not get a
    vote here, and neither does the memory count.

    It reports costs_recall False because normalize_label already folds the two
    forms together at comparison time, so nothing is invisible. The pair is a
    tidiness repair, not a scope loss, and counting it as one would overstate
    the damage.
    """
    counts = {'Freelance-logistics_crm': 24, 'Freelance-logistics-crm': 1}
    (split,) = A.label_splits(counts, {})
    assert split['kind'] == 'munge'
    assert split['keep'] == 'Freelance-logistics-crm'
    assert split['costs_recall'] is False


def test_family_pairs_are_not_splits():
    """A component and its project already see each other."""
    counts = {'Personal-business': 1412, 'Personal-business-instagram': 1}
    assert A.label_splits(counts, {}) == []


def test_quarantine_never_participates_in_a_split():
    counts = {A.UNKNOWN_PROJECT: 22, 'Personal-business': 10}
    assert A.label_splits(counts, {}) == []


def test_count_breaks_the_tie_when_both_labels_are_live():
    counts = {'Alpha-thing': 5, 'thing': 9}
    live = {'Alpha-thing': _p('a', 'Alpha', 'thing'), 'thing': _p('a', 'thing')}
    (split,) = A.label_splits(counts, live)
    assert split['keep'] == 'thing'


# stranded_labels

def test_successor_prefers_the_shallowest_copy():
    """Three directories carry the log-report name; only one is the workspace."""
    counts = {'Downloads-log-report': 1819, 'log-report': 18}
    live = {
        'log-report': _p('Users', 'hari', 'log-report'),
        'RECOVERED-2026-08-07-log-report':
            _p('Users', 'hari', 'RECOVERED-2026-08-07', 'log-report'),
    }
    (row,) = [r for r in A.stranded_labels(counts, live)
              if r['label'] == 'Downloads-log-report']
    assert row['successor'] == 'log-report'


def test_successor_ignores_a_directory_with_no_memories():
    """A recovery copy nobody has saved against is not where the work went."""
    counts = {'Personal-business-automation': 1}
    live = {'RECOVERED-Personal-business-automation':
            _p('Users', 'hari', 'RECOVERED', 'Personal-business-automation')}
    (row,) = A.stranded_labels(counts, live)
    assert row['successor'] is None


def test_successor_rejects_a_shared_trailing_segment():
    """Freelance-logistics-crm and Freelance-FittyMe-fittyme-crm are two clients.

    Matching on the last segment alone pairs them, which would file one
    client's memories under another.
    """
    counts = {'Freelance-logistics-crm': 1, 'Freelance-FittyMe-fittyme-crm': 4}
    live = {'Freelance-FittyMe-fittyme-crm':
            _p('Users', 'hari', 'Freelance', 'FittyMe', 'fittyme-crm')}
    (row,) = [r for r in A.stranded_labels(counts, live)
              if r['label'] == 'Freelance-logistics-crm']
    assert row['successor'] is None
    assert row['candidates'] == []


def test_a_live_label_is_never_stranded():
    counts = {'log-report': 18}
    live = {'log-report': _p('Users', 'hari', 'log-report')}
    assert A.stranded_labels(counts, live) == []


# home_labels

def test_home_label_is_reported(tmp_path):
    """16 memories sit under the munged home path and surface nowhere."""
    home = tmp_path / 'Users' / 'hari'
    home.mkdir(parents=True)
    label = A.munge(str(home)).lstrip('-')
    assert A.home_labels({label: 16, 'Real-project': 3}, home) == [
        {'label': label, 'count': 16}]


# dangling_links

def test_dangling_links_split_by_kind():
    mems = [
        _m('a', supersedes=['gone'], related=['b']),
        _m('b', related=['also-gone']),
    ]
    d = A.dangling_links(mems)
    assert d['supersedes'] == [{'from': 'a', 'to': 'gone'}]
    assert d['related'] == [{'from': 'b', 'to': 'also-gone'}]


# save_rate and audit

def test_save_rate_counts_only_the_last_thirty_days_as_recent():
    mems = [_m('a', days_ago=1), _m('b', days_ago=10), _m('c', days_ago=99)]
    r = A.save_rate(mems)
    assert r['total'] == 3
    assert r['last_30d'] == 2


def test_audit_separates_the_three_ways_a_save_misses_its_scope(tmp_path, monkeypatch):
    """One percentage would read as if the store were half unrecoverable.

    A split and a strand are one relabel away; a quarantined memory has no
    provenance to relabel it with. They are different problems.
    """
    home = tmp_path
    (home / 'live').mkdir()
    mems = ([_m(f'q{i}', project=A.UNKNOWN_PROJECT) for i in range(2)]
            + [_m(f's{i}', project='Dead-live') for i in range(5)]
            + [_m(f'k{i}', project='live') for i in range(3)])
    r = A.audit(_Repo(mems), home=home)
    causes = r['save_rate']['misfiled_by_cause']
    assert causes['quarantined'] == 2
    assert causes['split'] == 5
    assert causes['stranded'] == 0
    assert r['save_rate']['recoverable'] == 5
    assert r['save_rate']['landing_rate'] == pytest.approx(0.3, abs=0.01)


def test_audit_writes_nothing_to_the_store(tmp_path):
    """The audit is a read. Nothing it does may touch the object store."""
    mems = [_m('a', project='P')]
    repo = _Repo(mems)
    A.audit(repo, home=tmp_path)
    assert not hasattr(repo, 'add')
    assert [m.slug for m in repo.list()] == ['a']


def test_an_old_form_label_is_not_reported_as_stranded():
    """The regression the fixed binary produced the moment it was installed.

    Detection returns the dash form after the munge fix, so comparing raw
    strings called every label written before it stranded. On the live store
    that added 266 memories across three projects that resolve perfectly well.
    Comparison folds the two forms everywhere, and this was the one place it
    did not.
    """
    counts = {'Freelance-funeral_service': 232}
    live = {'Freelance-funeral-service':
            _p('Users', 'hari', 'Freelance', 'funeral_service')}
    assert A.stranded_labels(counts, live) == []
    assert A._is_live('Freelance-funeral_service', live) is True
