"""Rules that fire on actions, and a digest that reaches the model.

Every fixture here is shaped on the 2026-10-23 client incident: two priority-3
rules ("work only on staging, never branch"; "data fixes ship as scripts, a
.sql file is for schema only") were broken by a `git worktree add -b` Bash
call and a Write of `scripts/*.sql`, while the session-start digest that held
them was over the host's inline limit and listed critical rules by slug.
"""
import asyncio
import io
import json
from datetime import datetime, timedelta, timezone

import pytest
from mcp import types

from memgit import gate
from memgit.models import Mnemonic
from memgit.repo import Repository
from memgit.toon import parse_toon, serialize_mnemonic


def parse(text):
    return parse_toon(text)[0]

BRANCH_TRIG = {'command': r'git (checkout|switch) -b |git branch [^-]|git worktree add',
               'cwd': 'api|web'}
SQL_TRIG = {'path': 'api/scripts/*.sql'}


def _mk(slug, rule='r', priority=2, type_code='fb', project='proj', tags=None,
        triggers=None, ts=None, body=None, when=None):
    return Mnemonic(type_code=type_code, slug=slug,
                    timestamp=ts or datetime.now(timezone.utc), rule=rule,
                    priority=priority, tags=tags or ['t'], project=project,
                    triggers=triggers or [], body=body, when=when)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv('MEMGIT_PROJECT', 'proj')
    store = tmp_path / 'r'
    store.mkdir()
    return Repository.init(store)


def _run(monkeypatch, capsys, fn, payload, repo):
    import memgit.hooks as hooks_mod
    monkeypatch.setattr(hooks_mod, '_find_repo', lambda: repo)
    monkeypatch.setattr('sys.stdin', io.StringIO(json.dumps(payload)))
    rc = fn()
    return rc, capsys.readouterr().out


def _seed_rules(repo):
    repo.add(_mk('staging-only', 'Work ONLY on staging. NEVER create feature '
                 'branches or worktrees.', priority=3, triggers=[BRANCH_TRIG]))
    repo.add(_mk('data-fixes-are-scripts', 'A .sql file is only for schema; data '
                 'fixes ship as scripts/*.ts.', priority=3, triggers=[SQL_TRIG]))
    repo.add(_mk('prefer-rebase', 'Prefer rebase over merge here.', priority=2,
                 triggers=[{'command': r'git merge '}]))
    repo.commit(message='seed')


# ── format ────────────────────────────────────────────────────────────────────

class TestFormat:
    def test_triggers_round_trip(self):
        m = _mk('a', triggers=[BRANCH_TRIG, SQL_TRIG])
        back = parse(serialize_mnemonic(m))
        assert back.triggers == [BRANCH_TRIG, SQL_TRIG]
        assert not back.extra

    def test_no_triggers_leaves_the_hash_unchanged(self):
        m = _mk('a', ts=datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert 'TRIG' not in serialize_mnemonic(m, canonical=True)

    def test_unreadable_trig_is_kept_verbatim(self):
        text = serialize_mnemonic(_mk('a')) + '\nTRIG:not json'
        back = parse(text)
        assert back.triggers == [] and back.extra['TRIG'] == 'not json'


# ── validation ────────────────────────────────────────────────────────────────

class TestValidate:
    def test_clean(self):
        trig, problems = gate.validate_triggers([BRANCH_TRIG, SQL_TRIG])
        assert problems == [] and trig == [BRANCH_TRIG, SQL_TRIG]

    @pytest.mark.parametrize('bad', [
        [{'tool': 'Bash'}],                 # would fire on every call
        [{'command': '(unclosed'}],         # not a regex
        [{'command': 'x', 'colour': 'red'}],
        'not a list',
        [{'command': 1}],
    ])
    def test_refused(self, bad):
        assert gate.validate_triggers(bad)[1]


# ── matching ──────────────────────────────────────────────────────────────────

class TestMatch:
    @pytest.mark.parametrize('tool,inp,cwd,hit', [
        ('Bash', {'command': 'git worktree add -b fix/timeout ../api-wt staging'},
         '/Users/h/acme/api', True),
        ('Bash', {'command': 'cd api && git checkout -b fix/x'},
         '/Users/h/acme', True),          # cwd matched via the command
        ('Bash', {'command': 'git switch staging'}, '/x/api', False),
        ('Bash', {'command': 'git checkout -b fix/x'}, '/x/other-repo', False),
        ('Write', {'file_path': '/x/api/scripts/fix-dates-1970.sql'}, '/x', True),
        ('Write', {'file_path': '/x/api/scripts/fix-dates.ts'}, '/x', False),
        ('Edit', {'file_path': '/x/api/scripts/a.sql'}, '/x', True),
        ('Read', {'file_path': '/x/api/scripts/a.sql'}, '/x', False),
    ])
    def test_incident_shapes(self, tool, inp, cwd, hit):
        rows = [{'slug': 's', 'project': '', 'priority': 3, 'type': 'fb', 'rule': 'r',
                 'triggers': [BRANCH_TRIG, SQL_TRIG]}]
        assert bool(gate.matching_rules(rows, tool, inp, cwd, 'proj')) is hit

    def test_scoped_to_project(self):
        rows = [{'slug': 's', 'project': 'other', 'priority': 3, 'type': 'fb',
                 'rule': 'r', 'triggers': [SQL_TRIG]}]
        inp = {'file_path': '/x/api/scripts/a.sql'}
        assert gate.matching_rules(rows, 'Write', inp, '/x', 'proj') == []
        assert gate.matching_rules(rows, 'Write', inp, '/x', 'other')


# ── PreToolUse hook ───────────────────────────────────────────────────────────

class TestGateHook:
    def test_cache_written_at_commit(self, repo):
        _seed_rules(repo)
        slugs = {r['slug'] for r in gate.read_trigger_cache(repo)}
        assert slugs == {'staging-only', 'data-fixes-are-scripts', 'prefer-rebase'}

    def test_critical_rule_denies(self, repo, monkeypatch, capsys):
        from memgit.hooks import action_gate
        _seed_rules(repo)
        rc, out = _run(monkeypatch, capsys, action_gate, {
            'tool_name': 'Write', 'session_id': 's1', 'cwd': '/x',
            'tool_input': {'file_path': '/x/api/scripts/fix.sql',
                           'content': 'UPDATE ...'}}, repo)
        hso = json.loads(out)['hookSpecificOutput']
        assert hso['permissionDecision'] == 'deny'
        assert 'data-fixes-are-scripts' in hso['permissionDecisionReason']
        assert gate.DENY_MARK in hso['permissionDecisionReason']
        assert gate.read_log(repo, 's1')[0]['decision'] == 'deny'

    def test_lower_priority_adds_context_once(self, repo, monkeypatch, capsys):
        from memgit.hooks import action_gate
        _seed_rules(repo)
        payload = {'tool_name': 'Bash', 'session_id': 's2', 'cwd': '/x',
                   'tool_input': {'command': 'git merge main'}}
        rc, out = _run(monkeypatch, capsys, action_gate, payload, repo)
        hso = json.loads(out)['hookSpecificOutput']
        assert 'permissionDecision' not in hso
        assert 'prefer-rebase' in hso['additionalContext']
        rc, out = _run(monkeypatch, capsys, action_gate, payload, repo)
        assert out == ''

    def test_silent_when_nothing_matches(self, repo, monkeypatch, capsys):
        from memgit.hooks import action_gate
        _seed_rules(repo)
        rc, out = _run(monkeypatch, capsys, action_gate, {
            'tool_name': 'Bash', 'cwd': '/x', 'tool_input': {'command': 'ls'}}, repo)
        assert (rc, out) == (0, '')

    def test_override_lets_the_call_through_and_is_logged(self, repo, monkeypatch, capsys):
        from memgit.hooks import action_gate
        _seed_rules(repo)
        gate.allow(repo, 'staging-only', 5)
        rc, out = _run(monkeypatch, capsys, action_gate, {
            'tool_name': 'Bash', 'session_id': 's3', 'cwd': '/x/api',
            'tool_input': {'command': 'git checkout -b fix/y'}}, repo)
        hso = json.loads(out)['hookSpecificOutput']
        assert 'permissionDecision' not in hso
        assert 'override' in hso['additionalContext']
        assert gate.read_log(repo, 's3')[0]['decision'] == 'override'

    def test_override_expires(self, repo):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        gate.allow(repo, 'staging-only', 5, now=past)
        assert not gate.allowed(repo, 'staging-only')

    def test_broken_cache_is_silent(self, repo, monkeypatch, capsys):
        from memgit.hooks import action_gate
        (repo.path / 'cache').mkdir(exist_ok=True)
        (repo.path / 'cache' / 'triggers.json').write_text('{broken')
        rc, out = _run(monkeypatch, capsys, action_gate, {
            'tool_name': 'Bash', 'tool_input': {'command': 'git worktree add x'}}, repo)
        assert (rc, out) == (0, '')

    def test_metrics_count_denials(self, repo, monkeypatch, capsys):
        from memgit.hooks import action_gate
        from memgit.metrics import summary
        _seed_rules(repo)
        _run(monkeypatch, capsys, action_gate, {
            'tool_name': 'Write', 'cwd': '/x',
            'tool_input': {'file_path': '/x/api/scripts/a.sql'}}, repo)
        assert summary(repo)['gate']['denied'] == 1


# ── Stop replay ───────────────────────────────────────────────────────────────

def _transcript(tmp_path, calls, refused_ids=()):
    lines = []
    for i, (name, inp) in enumerate(calls):
        tid = f'tu{i}'
        lines.append(json.dumps({'type': 'assistant', 'cwd': '/x/api',
                                 'message': {'content': [{'type': 'tool_use', 'id': tid,
                                                          'name': name, 'input': inp}]}}))
        result = (f'{gate.DENY_MARK}: refused' if tid in refused_ids else 'ok')
        lines.append(json.dumps({'type': 'user', 'message': {'content': [
            {'type': 'tool_result', 'tool_use_id': tid, 'content': result}]}}))
    p = tmp_path / 't.jsonl'
    p.write_text('\n'.join(lines))
    return p


class TestCompliance:
    def test_ungated_violation_blocks_once(self, repo, tmp_path, monkeypatch, capsys):
        from memgit.hooks import stop_guard
        _seed_rules(repo)
        t = _transcript(tmp_path, [
            ('Bash', {'command': 'git worktree add -b fix/timeout ../wt staging'}),
            ('mcp__memgit__save_memory', {'slug': 'x'})])
        payload = {'transcript_path': str(t), 'session_id': 'c1', 'cwd': '/x'}
        rc, out = _run(monkeypatch, capsys, stop_guard, payload, repo)
        reason = json.loads(out)['reason']
        assert 'compliance' in reason and 'staging-only' in reason
        assert 'git worktree add' in reason
        assert 'saved no memories' not in reason      # capture was fine
        rc, out = _run(monkeypatch, capsys, stop_guard, payload, repo)
        assert out == ''

    def test_refused_call_is_not_a_violation(self, repo, tmp_path, monkeypatch, capsys):
        from memgit.hooks import stop_guard
        _seed_rules(repo)
        t = _transcript(tmp_path, [
            ('Write', {'file_path': '/x/api/scripts/a.sql', 'content': 'x'})],
            refused_ids={'tu0'})
        rc, out = _run(monkeypatch, capsys, stop_guard,
                       {'transcript_path': str(t), 'session_id': 'c2'}, repo)
        assert out == ''

    def test_logged_override_is_not_a_violation(self, repo, tmp_path, monkeypatch, capsys):
        from memgit.hooks import stop_guard
        _seed_rules(repo)
        inp = {'command': 'git checkout -b fix/z'}
        gate.log_decision(repo, 'c3', gate.call_signature('Bash', inp),
                          ['staging-only'], 'override')
        t = _transcript(tmp_path, [('Bash', inp)])
        rc, out = _run(monkeypatch, capsys, stop_guard,
                       {'transcript_path': str(t), 'session_id': 'c3'}, repo)
        assert out == ''


# ── save_memory ───────────────────────────────────────────────────────────────

@pytest.fixture
def save(tmp_path, monkeypatch):
    from memgit import mcp_server
    store = tmp_path / 'store'
    store.mkdir()
    Repository.init(store)
    holder = {}

    class Capture(mcp_server.Server):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            holder['s'] = self

    monkeypatch.setattr(mcp_server, 'Server', Capture)
    monkeypatch.setattr(asyncio, 'run', lambda coro: coro.close())
    monkeypatch.setenv('MEMGIT_PROJECT', 'proj')
    mcp_server.run_server(store)
    srv = holder['s']

    def call(arguments):
        req = types.CallToolRequest(method='tools/call', params=types.CallToolRequestParams(
            name='save_memory', arguments=arguments))
        loop = asyncio.new_event_loop()
        try:
            res = loop.run_until_complete(srv.request_handlers[types.CallToolRequest](req)).root
        finally:
            loop.close()
        text = res.content[0].text
        return res.isError, (text if res.isError else json.loads(text))

    call.repo = lambda: Repository(store / '.memgit')
    return call


class TestSave:
    def test_stores_and_keeps_triggers(self, save):
        err, out = save({'slug': 'g', 'rule': 'Never branch.', 'type_code': 'fb',
                         'priority': 3, 'triggers': [BRANCH_TRIG]})
        assert not err and out['triggers'] == 1
        err, out = save({'slug': 'g', 'rule': 'Never branch, ever.', 'type_code': 'fb',
                         'priority': 3})
        assert out.get('triggers_kept') is True
        assert save.repo().get('g').triggers == [BRANCH_TRIG]
        err, out = save({'slug': 'g', 'rule': 'Never branch.', 'type_code': 'fb',
                         'priority': 3, 'triggers': []})
        assert save.repo().get('g').triggers == []
        assert out.get('untriggered') is True

    def test_bad_trigger_refuses_the_save(self, save):
        err, text = save({'slug': 'g', 'rule': 'x', 'triggers': [{'tool': 'Bash'}]})
        assert err and 'command or a path' in text
        assert save.repo().get('g') is None

    def test_untriggered_critical_rule_is_flagged(self, save):
        err, out = save({'slug': 'g', 'rule': 'Always do X.', 'type_code': 'fb',
                         'priority': 3})
        assert out['untriggered'] is True
        assert any('no triggers' in w for w in out['warnings'])

    def test_nearest_rule_names_the_rule_it_replaces(self, save):
        # Shaped on the measured pair: the older rule shares only a few words.
        save({'slug': 'prefer-sql', 'type_code': 'fb', 'tags': ['acme'],
              'rule': "For a one-off prod data cleanup (e.g. delete a single test "
                      "comment), don't build a UI/API feature; identify the exact row "
                      "via read-only SQL and hand the user SELECT+DELETE SQL to run "
                      "themselves."})
        for i, r in enumerate(['Deploy the backend from the staging branch only.',
                               'Worker logs live under /var/log/worker.',
                               'Mobile push fires only for phone-origin turns.']):
            save({'slug': f'other-{i}', 'type_code': 'fb', 'tags': ['acme'], 'rule': r})
        new_rule = ('In the api repo, a .sql file is ONLY for table/schema changes '
                    '(migrations). Any data fix, repair or backfill ships as a '
                    '`scripts/*.ts` script, dry run by default, `--apply`, and a '
                    'ledger + `--revert` where the change is reversible.')
        err, out = save({'slug': 'scripts-not-sql', 'type_code': 'fb', 'priority': 3,
                         'tags': ['acme'], 'rule': new_rule})
        assert out.get('nearest_rule') == 'prefer-sql'
        err, out = save({'slug': 'scripts-not-sql', 'type_code': 'fb', 'priority': 3,
                         'tags': ['acme'], 'supersedes': ['prefer-sql'],
                         'rule': new_rule})
        assert out.get('nearest_rule') != 'prefer-sql'


# ── digest ────────────────────────────────────────────────────────────────────

def _big_store(repo, n_crit=168):
    base = datetime(2026, 8, 1, tzinfo=timezone.utc)
    for i in range(n_crit):
        repo.add(_mk(f'a-critical-{i:03d}', 'Critical rule text ' * 12, priority=3,
                     type_code='lx', ts=base + timedelta(hours=i)))
    repo.add(_mk('acme-work-on-staging', 'Work ONLY on staging.', priority=3,
                 ts=base + timedelta(days=20)))
    repo.add(_mk('acme-sql-only-for-schema', 'Data fixes are scripts.', priority=3,
                 ts=base + timedelta(days=21)))
    for i in range(8):
        repo.add(_mk(f'thing-{i}-status', 'state ' * 40, type_code='tr',
                     ts=base + timedelta(days=30, hours=i)))
    from memgit.delivery import AUTO_START, AUTO_END
    guide = ('# Core guide\n' + ('- a navigation line that is fairly long ' * 3 + '\n') * 60
             + f'\n{AUTO_START}\n## Frequently relevant\n' + '- [x] pointer\n' * 15
             + f'{AUTO_END}\n')
    repo.add(_mk('core-proj', 'core', type_code='co', body=guide))
    repo.commit(message='seed')


class TestDigest:
    def test_never_over_the_host_limit(self, repo):
        from memgit.cli import (HOST_INLINE_LIMIT_CHARS, RESUME_BUDGET_CHARS,
                                _format_resume_plain, _host_len)
        _big_store(repo)
        ctx = repo.resume_context(project='proj')
        text = _format_resume_plain(ctx)
        assert _host_len(text) <= RESUME_BUDGET_CHARS < HOST_INLINE_LIMIT_CHARS
        assert '## Critical rules' in text

    def test_critical_rules_ranked_and_before_the_status_board(self, repo):
        from memgit.cli import _format_resume_plain
        _big_store(repo)
        ctx = repo.resume_context(project='proj')
        slugs = [m['slug'] for m in ctx['critical_memories']]
        # behaviour rules (fb) first, newest first — not alphabetical
        assert slugs[:2] == ['acme-sql-only-for-schema', 'acme-work-on-staging']
        text = _format_resume_plain(ctx)
        assert text.index('## Critical rules') < text.index('## Status board')
        assert 'acme-work-on-staging' in text and 'acme-sql-only-for-schema' in text

    def test_emoji_counted_as_the_host_counts_them(self):
        from memgit.cli import _host_len
        assert _host_len('🔴') == 2 and _host_len('ab') == 2

    def test_small_store_untouched(self, repo):
        from memgit.cli import _format_resume_plain, _render_resume_plain
        repo.add(_mk('r1', 'one rule', priority=3))
        repo.commit(message='seed')
        ctx = repo.resume_context(project='proj')
        assert _format_resume_plain(ctx) == _render_resume_plain(ctx)


# ── drift ─────────────────────────────────────────────────────────────────────

class TestDrift:
    def test_finds_the_contradicting_passage(self, tmp_path):
        from memgit.drift import find_drift, rule_files
        root = tmp_path / 'acme'
        root.mkdir()
        (root / 'CLAUDE.md').write_text(
            '# Rules\n\n'
            '5. **The live branch is `staging`, not `main`.** Always branch from\n'
            '   staging and open the PR against it.\n'
            '- Worker logs live on the box under /var/log/worker.\n'
            '- For a one-off prod data cleanup, hand the user SELECT + DELETE SQL.\n'
            '<!-- MEMGIT:BEGIN -->\n- Work ONLY on staging, never create branches.\n'
            '<!-- MEMGIT:END -->\n')
        rules = [_mk('staging-only', 'Work ONLY on staging. NEVER create feature '
                     'branches or worktrees.', priority=3, project='proj'),
                 _mk('mobile-push', 'Mobile push fires only for phone-origin turns.',
                     priority=3, project='proj')]
        files = rule_files(root, stop=tmp_path)
        pairs = find_drift(rules, files, 'proj')
        hits = [(d.slug, d.passage.line) for d in pairs]
        assert ('staging-only', 3) in hits
        # the memgit-managed block is never compared with memgit itself
        assert all(d.passage.line < 7 for d in pairs)
