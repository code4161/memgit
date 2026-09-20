"""Tests for company resolution.

The shapes here are the ones measured on a real tree on 2026-09-20. Two of
them are the cases that broke the first two versions of this resolver, and
both broke it in the expensive direction: a folder that groups six unrelated
clients was assigned as their company, which puts one client's record inside
another client's scope.
"""

from datetime import datetime, timezone
from pathlib import Path

from memgit import org
from memgit.models import Mnemonic


def _proj(home: Path, rel: str, prose: str = '', repo: str = '') -> Path:
    d = home / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / 'CLAUDE.md').write_text(prose or 'a project', encoding='utf-8')
    if repo:
        (d / '.git').mkdir(exist_ok=True)
        (d / '.git' / 'config').write_text(repo, encoding='utf-8')
    return d


def _mem(rule='r', tags=None):
    return Mnemonic(type_code='lx', slug='s', rule=rule, tags=tags or [],
                    timestamp=datetime(2026, 9, 20, tzinfo=timezone.utc))


# name matching

def test_a_name_quoted_inside_a_path_does_not_attest():
    """Every project documents where it lives, so the folder name is in the text.

    This is what made two container folders read as companies: each child said
    it lived in ~/Freelance/... and that counted as the child attesting
    Freelance.
    """
    text = 'Reconstructed after the rollback wiped ~/Freelance/FittyMe.'
    assert org.name_in_text('Freelance', text) is True
    assert org.name_in_text('Freelance', text, mask_paths=True) is False


def test_a_name_in_a_sentence_still_attests():
    text = 'This work is delivered for Masgarti under a retainer.'
    assert org.name_in_text('Masgarti', text, mask_paths=True) is True


def test_a_name_does_not_match_inside_a_longer_word():
    assert not org.name_in_text('Masgarti', 'MasgartiFIT is a product')


def test_a_domain_attests_a_two_word_company():
    """The punctuation-stripped form is what links a company to its domain."""
    assert org.name_in_text('OFO Collective', 'https://www.ofocollective.com')


def test_a_git_remote_is_not_path_masked():
    """In a git config the path IS the identity, unlike in prose."""
    cfg = '[remote "origin"]\n\turl = git@github.com:masgarti/xovo-pos.git\n'
    assert org.name_in_text('masgarti', cfg) is True
    assert org.name_in_text('masgarti', cfg, mask_paths=True) is False


# container detection

def test_a_folder_holding_unrelated_clients_is_a_container(tmp_path):
    """Measured: 1 of 6 children attested Freelance, in a sentence about
    freelance work. One child is not agreement."""
    f = tmp_path / 'Freelance'
    _proj(tmp_path, 'Freelance/BITS', prose='some freelance work here')
    for name in ('FittyMe', 'funeral_service', 'logistics_crm',
                 'finance_app', 'smartproperty'):
        _proj(tmp_path, f'Freelance/{name}', prose='a client project')
    assert org.folder_is_container(f) is True


def test_a_folder_whose_children_agree_is_a_company(tmp_path):
    """Measured: 4 of 4 children attested Masgarti."""
    f = tmp_path / 'Masgarti'
    for name in ('xovo-pos', 'Masgarti-FIT', 'Spaces', 'AI-Business'):
        _proj(tmp_path, f'Masgarti/{name}',
              repo='url = git@github.com:masgarti/x.git')
    assert org.folder_is_container(f) is False


def test_a_folder_with_one_attesting_child_is_a_company(tmp_path):
    """Measured: OFO collective held exactly one project, and it attested."""
    f = tmp_path / 'OFO collective'
    _proj(tmp_path, 'OFO collective/InstantVoiceBotWebsite',
          prose='Built with OFO Collective, alongside the team.')
    assert org.folder_is_container(f) is False


def test_an_empty_folder_is_a_container(tmp_path):
    f = tmp_path / 'Empty'
    f.mkdir()
    assert org.folder_is_container(f) is True


# resolve

def test_a_container_name_is_vetoed_as_a_candidate_entirely(tmp_path):
    """Dropping only the folder EVIDENCE is not enough.

    Freelance is attested in one client's prose and in two memory rule lines,
    which is two inside classes and qualifies on the general rule. The
    container verdict has to veto the name itself.
    """
    _proj(tmp_path, 'Freelance/BITS', prose='some freelance work here')
    root = _proj(tmp_path, 'Freelance/FittyMe', prose='a client project')
    for name in ('funeral_service', 'logistics_crm', 'finance_app', 'more'):
        _proj(tmp_path, f'Freelance/{name}', prose='a client project')
    mems = [_mem('freelance delivery notes'), _mem('freelance invoice flow')]
    v = org.resolve(root, mems, home=tmp_path)
    assert v['state'] == 'container'
    assert v['container'] == 'Freelance'
    assert v['org'] is None


def test_a_company_is_assigned_with_its_evidence(tmp_path):
    _proj(tmp_path, 'Masgarti/other', repo='url = github.com/masgarti/y.git')
    root = _proj(tmp_path, 'Masgarti/xovo-pos',
                 prose='Delivered for Masgarti.',
                 repo='url = git@github.com:masgarti/xovo-pos.git')
    v = org.resolve(root, [], home=tmp_path)
    assert v['state'] == 'assigned'
    assert v['org'] == 'Masgarti'
    assert v['slug'] == 'masgarti'
    assert 'folder' in v['why'] and 'prose' in v['why']


def test_two_companies_attested_assigns_nothing(tmp_path):
    """Measured: one project name was claimed by a client of one company and a
    component of another. Picking either crosses two companies' scopes."""
    _proj(tmp_path, 'Acme/other', prose='Acme Industries work')
    root = _proj(tmp_path, 'Acme/hermes', prose='Acme Industries work')
    mems = [_mem('hermes runs for Globex', tags=['org:globex'])]
    v = org.resolve(root, mems, declared='Globex', home=tmp_path)
    assert v['state'] == 'conflicted'
    assert v['org'] is None
    assert v['candidates'] == ['Acme', 'Globex']


def test_one_evidence_class_is_never_enough(tmp_path):
    """A folder name alone must never assign, whatever else is true."""
    _proj(tmp_path, 'Vendor/a', prose='Vendor group work')
    root = _proj(tmp_path, 'Vendor/b', prose='unrelated notes')
    v = org.resolve(root, [], home=tmp_path)
    assert v['state'] in ('container', 'standalone')
    assert v['org'] is None


def test_a_short_folder_name_is_never_a_candidate(tmp_path):
    """A folder named AI held three unrelated organisations, and those two
    letters appear in an ordinary sentence in every one of their documents."""
    _proj(tmp_path, 'AI/GraySwan', prose='authorised AI red-teaming work')
    root = _proj(tmp_path, 'AI/Aligneer', prose='AI assistance is allowed')
    v = org.resolve(root, [], home=tmp_path)
    assert v['org'] is None


def test_a_declared_name_bypasses_the_length_floor(tmp_path):
    """Someone naming a company takes responsibility for it."""
    root = _proj(tmp_path, 'x/IBM', prose='IBM engagement notes')
    v = org.resolve(root, [_mem('IBM rollout', tags=['org:ibm'])],
                    declared='IBM', home=tmp_path)
    assert v['state'] == 'assigned'
    assert v['org'] == 'IBM'


def test_an_existing_org_tag_carries_the_company_forward(tmp_path):
    """A project whose folder says nothing keeps the company it was given."""
    root = _proj(tmp_path, 'Masgarti-Networking-pro',
                 prose='Delivered for Masgarti.')
    v = org.resolve(root, [_mem('networking rollout', tags=['org:masgarti'])],
                    home=tmp_path)
    assert v['state'] == 'assigned'
    assert v['org'] == 'masgarti'


def test_a_project_with_no_candidate_is_unresolved(tmp_path):
    root = _proj(tmp_path, 'Standalone', prose='just a project')
    v = org.resolve(root, [], home=tmp_path)
    assert v['state'] == 'unresolved'
    assert v['org'] is None
