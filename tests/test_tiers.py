"""Tests for the company and component tiers.

The directory shapes here are the ones measured on a real tree on 2026-09-20:
a client folder holding six git repos, a workspace holding thirteen
sub-projects, and two container folders holding unrelated clients.
"""

from pathlib import Path

from memgit import tiers as T
from memgit.models import Mnemonic
from memgit.toon import parse_toon, serialize_mnemonic


def _mk(home: Path, rel: str, *markers: str) -> Path:
    d = home / rel
    d.mkdir(parents=True, exist_ok=True)
    for marker in markers or ('CLAUDE.md',):
        (d / marker).write_text('x', encoding='utf-8')
    return d


def _bare(home: Path, rel: str) -> Path:
    d = home / rel
    d.mkdir(parents=True, exist_ok=True)
    return d


# reserved tags

def test_reserved_tags_are_hidden_from_subject_tags():
    tags = ['deploy', 'org:ofo-collective', 'part:fittyme-app', 'retell']
    assert T.visible_tags(tags) == ['deploy', 'retell']
    assert T.is_reserved('org:x') and T.is_reserved('part:x')
    assert not T.is_reserved('deploy')


def test_org_name_is_slugified_so_one_company_is_one_tag():
    """OFO Collective and ofo-collective are the same company written twice."""
    assert T.slugify_org('OFO Collective') == 'ofo-collective'
    assert T.slugify_org('  Masgarti  ') == 'masgarti'
    assert T.slugify_org('OFO Collective') == T.slugify_org('ofo-collective')


def test_setting_an_org_replaces_it_rather_than_appending():
    """Two org tags would leave a memory claiming two companies."""
    tags = T.with_tier_tags(['deploy', 'org:old'], org='OFO Collective')
    assert tags.count('org:ofo-collective') == 1
    assert 'org:old' not in tags
    assert 'deploy' in tags


def test_an_unknown_reserved_tag_survives_a_rewrite():
    """A tier tag from a newer memgit must not be dropped by this one."""
    tags = T.with_tier_tags(['deploy', 'future:thing'], org='Masgarti')
    assert 'future:thing' in tags
    assert 'org:masgarti' in tags


def test_reading_tiers_off_a_memory():
    m = Mnemonic(type_code='lx', slug='s', timestamp=None, rule='r',
                 tags=['org:masgarti', 'part:xovo-pos', 'deploy'])
    assert T.read_org(m) == 'masgarti'
    assert T.read_part(m) == 'xovo-pos'
    assert T.read_org(Mnemonic(type_code='lx', slug='s2',
                               timestamp=None, rule='r')) is None


def test_a_tier_tag_round_trips_through_toon():
    """The whole reason tiers are tags: every shipped version carries them."""
    from datetime import datetime, timezone
    m = Mnemonic(type_code='lx', slug='s', rule='r',
                 timestamp=datetime(2026, 9, 20, tzinfo=timezone.utc),
                 tags=['org:ofo-collective', 'part:aios', 'retell'])
    (back,) = parse_toon(serialize_mnemonic(m))
    assert T.read_org(back) == 'ofo-collective'
    assert T.read_part(back) == 'aios'
    assert T.visible_tags(back.tags) == ['retell']


# project_root: the directly opened component

def test_a_directly_opened_repo_resolves_to_its_project(tmp_path):
    """The measured case: one client folder, six git repos inside it.

    Opening one repo must resolve to the client, not invent a project per
    repo, or the client's history fragments six ways.
    """
    _bare(tmp_path, 'Freelance')
    _mk(tmp_path, 'Freelance/FittyMe', 'CLAUDE.md')
    app = _mk(tmp_path, 'Freelance/FittyMe/fittyme_app', 'README.md', '.git')
    crm = _mk(tmp_path, 'Freelance/FittyMe/fittyme-crm', 'package.json', '.git')

    root, part = T.project_root(app, tmp_path)
    assert root == (tmp_path / 'Freelance/FittyMe').resolve()
    assert T.component_label(root, part) == 'fittyme-app'

    root2, part2 = T.project_root(crm, tmp_path)
    assert root2 == root
    assert T.component_label(root2, part2) == 'fittyme-crm'


def test_a_nested_component_keeps_its_full_path(tmp_path):
    """Thirteen sub-projects, opened two levels down."""
    pb = _mk(tmp_path, 'Personal business', 'CLAUDE.md', '.git')
    _mk(tmp_path, 'Personal business/competitions', 'CLAUDE.md', '.git')
    cd = _mk(tmp_path, 'Personal business/competitions/crunchdao', 'CLAUDE.md')
    root, part = T.project_root(cd, tmp_path)
    assert root == pb.resolve()
    assert T.component_label(root, part) == 'competitions-crunchdao'


def test_the_project_root_itself_has_no_component(tmp_path):
    root_dir = _mk(tmp_path, 'Thing', 'CLAUDE.md')
    root, part = T.project_root(root_dir, tmp_path)
    assert root == root_dir.resolve()
    assert part is None
    assert T.component_label(root, part) is None


def test_a_container_folder_is_not_a_project(tmp_path):
    """A folder that only groups clients attests nothing and owns nothing."""
    _bare(tmp_path, 'Freelance')
    _mk(tmp_path, 'Freelance/BITS', 'CLAUDE.md')
    root, part = T.project_root(tmp_path / 'Freelance', tmp_path)
    assert root is None and part is None


def test_a_path_outside_home_resolves_to_nothing(tmp_path):
    root, part = T.project_root(Path(tmp_path.anchor), tmp_path / 'sub')
    assert root is None and part is None


def test_the_shallowest_attesting_directory_wins(tmp_path):
    """A stray README over a set of clients must not swallow them.

    The walk takes the first attesting directory from the top, so a marker
    appearing on a container folder cannot capture the projects below it any
    more than it already would.
    """
    _mk(tmp_path, 'Clients', 'README.md')
    a = _mk(tmp_path, 'Clients/ClientA', 'CLAUDE.md', '.git')
    root, part = T.project_root(a, tmp_path)
    assert root == (tmp_path / 'Clients').resolve()
    assert T.component_label(root, part) == 'ClientA'


# company_candidate: nominates, never decides

def test_the_parent_folder_is_only_a_candidate(tmp_path):
    _bare(tmp_path, 'OFO collective')
    ivb = _mk(tmp_path, 'OFO collective/InstantVoiceBotWebsite', 'CLAUDE.md')
    assert T.company_candidate(ivb, tmp_path) == 'OFO collective'


def test_a_project_directly_under_home_has_no_candidate(tmp_path):
    """Nothing groups it, so foldering has nothing to say."""
    d = _mk(tmp_path, 'Masgarti-Networking-pro', 'CLAUDE.md')
    assert T.company_candidate(d, tmp_path) is None
