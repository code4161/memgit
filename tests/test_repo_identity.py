"""The same repository checked out at another path is the same project.

Measured 2026-11-12 on 0.15.0 against a local cloud API: memories saved from
~/code/acme-api synced correctly to a teammate at ~/work/acme-api, the same
user's second machine at ~/src/api and a server at /srv/acme-api, and every
default search on all three answered "No results" with advice to bootstrap the
project from scratch. A label is a path; the repository's remote is what the
checkouts share.
"""
import asyncio
from datetime import datetime, timezone

import pytest
from mcp import types

from memgit import mcp_server, project
from memgit.models import Mnemonic
from memgit.project import (detect_project, normalize_remote, repo_identity,
                            same_project_family, scope_filter)
from memgit.repo import Repository
from memgit.scorer import score
from memgit.toon import parse_toon, serialize_mnemonic

NOW = datetime(2026, 11, 12, 5, 0, tzinfo=timezone.utc)


def checkout(root, rel, remote='git@github.com:acme/api.git'):
    d = root / rel
    (d / '.git').mkdir(parents=True)
    cfg = '[core]\n\tbare = false\n'
    if remote:
        cfg += f'[remote "origin"]\n\turl = {remote}\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n'
    (d / '.git' / 'config').write_text(cfg)
    return d


def save(repo, cwd, slug, rule, **kw):
    label = detect_project(cwd)
    m = Mnemonic(type_code=kw.pop('type_code', 'cn'), slug=slug, timestamp=NOW, rule=rule,
                 project=kw.pop('project', label), **kw)
    repo.add(m)
    repo.commit(message=f'save {slug}')
    return label


# ── identity ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('url,ident', [
    ('git@github.com:Acme/API.git', 'github.com/acme/api'),
    ('https://github.com/acme/api', 'github.com/acme/api'),
    ('https://user:tok@github.com/acme/api.git/', 'github.com/acme/api'),
    ('ssh://git@github.com:22/acme/api.git', 'github.com/acme/api'),
    ('git@gitlab.example.com:group/sub/proj.git', 'gitlab.example.com/group/sub/proj'),
    ('/srv/git/api.git', None),
    ('file:///srv/git/api.git', None),
    ('../api', None),
    ('C:\\repos\\api', None),
    ('', None),
])
def test_every_way_of_cloning_gives_one_identity(url, ident):
    assert normalize_remote(url) == ident


def test_identity_is_read_from_the_checkout_and_its_subdirectories(tmp_path):
    d = checkout(tmp_path, 'code/acme-api')
    (d / 'src' / 'pkg').mkdir(parents=True)
    assert repo_identity(d) == 'github.com/acme/api'
    assert repo_identity(d / 'src' / 'pkg') == 'github.com/acme/api/src/pkg'
    assert repo_identity(checkout(tmp_path, 'scratch', remote=None)) is None
    assert repo_identity(tmp_path / 'nowhere') is None


def test_a_worktree_reads_the_main_repository_config(tmp_path):
    main = checkout(tmp_path, 'main')
    wt_git = main / '.git' / 'worktrees' / 'feature'
    wt_git.mkdir(parents=True)
    (wt_git / 'commondir').write_text('../..\n')
    wt = tmp_path / 'feature'
    wt.mkdir()
    (wt / '.git').write_text(f'gitdir: {wt_git}\n')
    assert repo_identity(wt) == 'github.com/acme/api'


# ── scoping ──────────────────────────────────────────────────────────────────

def test_a_memory_saved_in_one_checkout_is_found_from_another(tmp_path):
    repo = Repository.init(tmp_path / 'store')
    alice = checkout(tmp_path, 'code/acme-api')
    bob = checkout(tmp_path, 'work/acme-api')
    a_label = save(repo, alice, 'deploy-uses-blue-green', 'deploys go through the blue-green switch')
    stored = repo.list()
    assert stored[0].extra.get('REPO') == 'github.com/acme/api'

    b_label = detect_project(bob)
    assert a_label != b_label
    pool = repo.list()
    assert [m.slug for m in scope_filter(pool, b_label)] == ['deploy-uses-blue-green']
    hits = score('how do we deploy', pool, top_k=5, scope_project=b_label, boost_project=b_label)
    assert [r.mnemonic.slug for r in hits] == ['deploy-uses-blue-green']
    ctx = repo.resume_context(project=b_label)
    assert not ctx['project_is_new']


def test_a_different_repository_stays_a_different_project(tmp_path):
    repo = Repository.init(tmp_path / 'store')
    api = checkout(tmp_path, 'code/acme-api')
    web = checkout(tmp_path, 'code/acme-web', remote='git@github.com:acme/web.git')
    save(repo, api, 'deploy-uses-blue-green', 'deploys go through the blue-green switch')
    web_label = detect_project(web)
    assert scope_filter(repo.list(), web_label) == []


def test_an_existing_project_joins_up_on_its_next_save(tmp_path):
    """Memories written before identities existed carry no REPO. One new save
    under the same label teaches the label its repository, and every older
    memory under it becomes visible from the other checkouts."""
    repo = Repository.init(tmp_path / 'store')
    alice = checkout(tmp_path, 'code/acme-api')
    label = project.project_label_from_path(alice)
    repo.add(Mnemonic(type_code='pj', slug='old-decision', timestamp=NOW,
                      rule='we chose postgres over mysql', project=label))
    repo.commit(message='old')
    bob_label = detect_project(checkout(tmp_path, 'work/acme-api'))
    assert scope_filter(repo.list(), bob_label) == []

    save(repo, alice, 'new-fact', 'the api runs on port 8080')
    assert {m.slug for m in scope_filter(repo.list(), bob_label)} == {'old-decision', 'new-fact'}


def test_a_forced_project_label_is_not_tied_to_the_cwd_repository(tmp_path, monkeypatch):
    repo = Repository.init(tmp_path / 'store')
    d = checkout(tmp_path, 'code/acme-api')
    monkeypatch.setenv('MEMGIT_PROJECT', 'Freelance-FittyMe')
    save(repo, d, 'forced', 'a memory saved under a forced label')
    assert 'REPO' not in repo.list()[0].extra


def test_an_explicit_other_project_or_global_save_is_not_stamped(tmp_path):
    repo = Repository.init(tmp_path / 'store')
    d = checkout(tmp_path, 'code/acme-api')
    save(repo, d, 'elsewhere', 'filed under another project', project='Other-Project')
    save(repo, d, 'everywhere', 'applies in every project', project=None)
    assert all('REPO' not in m.extra for m in repo.list())


def test_monorepo_sibling_folders_stay_separate_projects(tmp_path):
    """Two project folders inside one repository were never one project by
    label; sharing a remote must not merge them."""
    repo = Repository.init(tmp_path / 'store')
    mono = checkout(tmp_path, 'work', remote='git@github.com:me/workspace.git')
    (mono / 'predico').mkdir()
    (mono / 'upwork').mkdir()
    save(repo, mono / 'predico', 'forecast-gate', 'gate closes at 11h')
    upwork_label = detect_project(mono / 'upwork')
    assert scope_filter(repo.list(), upwork_label) == []
    assert repo.list()[0].extra['REPO'] == 'github.com/me/workspace/predico'


def test_a_dotfiles_home_does_not_fold_every_project_into_one(tmp_path, monkeypatch):
    home = checkout(tmp_path, 'home', remote='git@github.com:me/dotfiles.git')
    monkeypatch.setenv('HOME', str(home))
    repo = Repository.init(tmp_path / 'store')
    (home / 'clients' / 'bits').mkdir(parents=True)
    (home / 'clients' / 'fittyme').mkdir(parents=True)
    save(repo, home / 'clients' / 'bits', 'bits-rule', 'bits client rule')
    assert scope_filter(repo.list(), detect_project(home / 'clients' / 'fittyme')) == []


def test_a_subfolder_of_another_checkout_is_family(tmp_path):
    repo = Repository.init(tmp_path / 'store')
    alice = checkout(tmp_path, 'code/acme-api')
    save(repo, alice, 'root-rule', 'applies to the whole repo')
    bob = checkout(tmp_path, 'work/acme-api')
    (bob / 'src').mkdir()
    sub_label = detect_project(bob / 'src')
    assert [m.slug for m in scope_filter(repo.list(), sub_label)] == ['root-rule']
    assert project.project_affinity(repo.list()[0].project, sub_label) == 1


def test_unrelated_labels_without_identity_stay_apart():
    assert not same_project_family('code-acme-api', 'work-acme-api')


# ── compatibility ────────────────────────────────────────────────────────────

def test_the_repository_survives_a_round_trip_through_any_reader():
    m = Mnemonic(type_code='cn', slug='x', timestamp=NOW, rule='r', project='code-acme-api',
                 extra={'REPO': 'github.com/acme/api'})
    for canonical in (False, True):
        back = parse_toon(serialize_mnemonic(m, canonical=canonical))[0]
        assert back.extra == {'REPO': 'github.com/acme/api'}


def test_a_memory_without_a_repository_serializes_exactly_as_before():
    m = Mnemonic(type_code='cn', slug='x', timestamp=NOW, rule='r', project='p')
    assert 'REPO' not in serialize_mnemonic(m, canonical=True)


# ── what an agent is told when its label holds nothing ───────────────────────

def _mcp(store, monkeypatch, project_label):
    holder = {}

    class Capture(mcp_server.Server):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            holder['s'] = self

    monkeypatch.setattr(mcp_server, 'Server', Capture)
    monkeypatch.setattr(asyncio, 'run', lambda coro: coro.close())
    monkeypatch.setenv('MEMGIT_PROJECT', project_label)
    monkeypatch.setenv('MEMGIT_NO_AUTOSYNC', '1')
    mcp_server.run_server(store)
    srv = holder['s']

    def call(name, arguments):
        req = types.CallToolRequest(method='tools/call', params=types.CallToolRequestParams(
            name=name, arguments=arguments))
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                srv.request_handlers[types.CallToolRequest](req)).root.content[0].text
        finally:
            loop.close()
    return call


def test_an_empty_scoped_search_shows_the_matches_under_other_labels(tmp_path, monkeypatch):
    """Measured 2026-11-12: a server agent got "No results ... Bootstrap it now"
    for 201 of 201 searches while its store held 607 memories under another label."""
    store = tmp_path / 'store'
    repo = Repository.init(store)
    repo.add(Mnemonic(type_code='rf', slug='food-photo-counts', timestamp=NOW,
                      rule='meal plates logged come from meals with image_url',
                      project='Freelance-FittyMe'))
    repo.commit(message='seed')
    call = _mcp(store, monkeypatch, 'home-prreview-ws')
    out = call('search_memories', {'query': 'how many meal plates were logged'})
    assert 'food-photo-counts' in out
    assert "'Freelance-FittyMe'" in out
    assert 'MEMGIT_PROJECT' in out
    assert 'Bootstrap' not in out


def test_an_empty_store_still_gets_the_bootstrap_advice(tmp_path, monkeypatch):
    call = _mcp(tmp_path / 'store', monkeypatch, 'brand-new')
    out = call('search_memories', {'query': 'anything at all'})
    assert 'No results found' in out
    assert 'Bootstrap' in out


def test_resume_names_the_labels_the_store_does_hold(tmp_path, monkeypatch):
    store = tmp_path / 'store'
    repo = Repository.init(store)
    repo.add(Mnemonic(type_code='cn', slug='a', timestamp=NOW, rule='rule a',
                      project='Freelance-FittyMe'))
    repo.commit(message='seed')
    call = _mcp(store, monkeypatch, 'home-prreview-ws')
    out = call('resume_session', {})
    assert 'Freelance-FittyMe (1)' in out
    assert 'do not re-create' in out


# ── a failing sync is visible to the agent ───────────────────────────────────

def _cloud_files(repo, state, last):
    import json
    d = repo.path / 'cloud'
    d.mkdir(exist_ok=True)
    (d / 'state.json').write_text(json.dumps(state))
    (d / 'autosync-last.json').write_text(json.dumps(last))


def test_the_digest_says_when_the_last_cloud_sync_failed(tmp_path):
    from memgit.cli import _format_resume_plain
    repo = Repository.init(tmp_path / 'store')
    _cloud_files(repo, {'autosync': True, 'team_id': 't', 'repo_id': 'r'},
                 {'at': '2026-11-12T05:00:00+00:00', 'ok': False,
                  'error': 'subscription required\n  upgrade: https://app.memgit.dev/billing'})
    text = _format_resume_plain(repo.resume_context())
    assert '## Cloud sync is failing' in text
    assert 'subscription required' in text


@pytest.mark.parametrize('state,last', [
    ({'autosync': True}, {'at': 'x', 'ok': True}),
    ({'autosync': False}, {'at': 'x', 'ok': False, 'error': 'e'}),
])
def test_the_digest_is_quiet_when_sync_is_fine_or_off(tmp_path, state, last):
    from memgit.cli import _format_resume_plain
    repo = Repository.init(tmp_path / 'store')
    _cloud_files(repo, state, last)
    assert 'Cloud sync is failing' not in _format_resume_plain(repo.resume_context())
