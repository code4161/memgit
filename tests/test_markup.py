"""save_memory values that carry tool-call markup.

Every fixture shape below is one measured on 2026-10-07 in a live store, where
748 of 3,025 save_memory calls arrived with the parameters after one field
swallowed into it. The save path must refuse each of them, the read and
injection surfaces must not serve the markup back, and doctor must split a
stored one back into its fields.
"""
import asyncio
import json
from datetime import datetime, timezone

import pytest
from click.testing import CliRunner
from mcp import types

from memgit import markup
from memgit.models import Mnemonic
from memgit.repo import Repository

P = '<parameter name="{}">'
END = '</parameter>'

#: (field, damaged value, parameters it swallowed), one per measured shape.
SHAPES = [
    ('rule', 'X is true.</rule>\n' + P.format('why') + 'because Y', ['why']),
    ('rule', 'X is true.</rule>\n' + P.format('type_code') + 'pj', ['type_code']),
    ('rule', 'X is true.</rule>\n' + P.format('why') + 'because Y</why>\n'
     + P.format('when') + 'always', ['why', 'when']),
    ('body', 'Long detail here.</body>\n', []),
    ('rule', 'X is true.' + END + '\n' + P.format('why') + 'because Y', ['why']),
    ('why', 'because Y' + END + '\n' + P.format('when') + 'always', ['when']),
    ('rule', 'X is true.</rule>\n' + P.format('why') + 'Y' + END + '\n'
     + P.format('when') + 'W' + END + '\n' + P.format('body') + 'B' + END
     + '\n' + P.format('tags') + '["a", "b"]', ['why', 'when', 'body', 'tags']),
    ('why', 'because Y</why>\n' + P.format('when') + 'always' + END + '\n'
     + P.format('tags') + '["a"]', ['when', 'tags']),
    # the start of the next tool call, and namespaced markup
    ('rule', 'X is true.' + END + '\n</invoke>\n<invoke name="ToolSearch">', []),
    ('rule', 'X.</ns:parameter>\n<ns:parameter name="why">Y', ['why']),
    # an unclosed fence in prose must not hide the damage after it
    ('rule', 'Outline renders ```mermaid blocks.' + END + '\n'
     + P.format('why') + 'Y', ['why']),
]


@pytest.fixture
def server(tmp_path, monkeypatch):
    """The real MCP server with its handlers registered, never run on stdio."""
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
        req = types.CallToolRequest(
            method='tools/call',
            params=types.CallToolRequestParams(name='save_memory',
                                               arguments=arguments))
        loop = asyncio.new_event_loop()
        try:
            res = loop.run_until_complete(
                srv.request_handlers[types.CallToolRequest](req)).root
        finally:
            loop.close()
        return res.isError, res.content[0].text

    call.repo = lambda: Repository(store / '.memgit')
    return call


@pytest.fixture
def repo(tmp_path):
    store = tmp_path / 'r'
    store.mkdir()
    return Repository.init(store)


class TestDetector:
    @pytest.mark.parametrize('field,value,lost', SHAPES)
    def test_every_measured_shape_is_markup(self, field, value, lost):
        assert markup.has_markup(value)
        assert [p for p in markup.swallowed_params(value) if p != field] == lost

    @pytest.mark.parametrize('text', [
        'Quote it in code: `</rule><parameter name="why">` is the defect.',
        'Inject the script before </body> in the template, then reload.',
        'The closing tag </rule> is prose here and continues afterwards.',
        '```\n</rule>\n<parameter name="why">x\n```',
        'Plain text with <b>html</b> and a <div> or two.',
        '',
    ])
    def test_prose_and_quoted_markup_are_not(self, text):
        assert not markup.has_markup(text)

    def test_clean_for_context_cuts_at_the_damage(self):
        assert markup.clean_for_context(SHAPES[0][1]) == 'X is true.'
        assert markup.clean_for_context('fine') == 'fine'
        assert markup.clean_for_context(None) == ''


class TestSaveRefuses:
    @pytest.mark.parametrize('field,value,lost', SHAPES)
    def test_damaged_save_is_refused_and_nothing_is_stored(
            self, server, field, value, lost):
        args = {'slug': 'damaged', 'rule': 'a clean rule', 'type_code': 'pj'}
        args[field] = value
        is_error, text = server(args)
        assert is_error
        assert 'refused' in text and f"'{field}'" in text
        for p in lost:
            assert p in text
        assert server.repo().get('damaged') is None

    def test_markup_inside_a_tag_is_refused(self, server):
        is_error, _ = server({'slug': 's', 'rule': 'r', 'type_code': 'pj',
                              'tags': ['ok', 'x</tags>\n' + P.format('why')]})
        assert is_error

    def test_quoted_markup_saves(self, server):
        is_error, text = server({
            'slug': 'lesson', 'type_code': 'lx', 'tags': ['memgit'],
            'rule': 'A save leaked `</rule><parameter name="why">` into rule.'})
        assert not is_error
        assert json.loads(text)['status'] == 'ok'


class TestSaveEchoes:
    def test_clean_save_reports_what_was_stored(self, server):
        _, text = server({'slug': 'a', 'rule': 'r', 'type_code': 'pj',
                          'priority': 2, 'why': 'w', 'when': 'n',
                          'body': 'b', 'tags': ['t']})
        out = json.loads(text)
        assert out['stored'] == {'rule_chars': 1, 'why_chars': 1,
                                 'when_chars': 1, 'body_chars': 1, 'tags': 1}
        assert 'defaulted' not in out and 'warnings' not in out

    def test_missing_type_and_fields_are_named(self, server):
        out = json.loads(server({'slug': 'b', 'rule': 'r'})[1])
        assert out['type'] == 'fb'
        assert out['defaulted'] == ['type_code', 'priority']
        assert out['stored']['empty'] == ['why', 'when', 'body', 'tags']
        assert any("stored as 'fb'" in w for w in out['warnings'])

    def test_unknown_argument_is_warned(self, server):
        out = json.loads(server({'slug': 'c', 'rule': 'r', 'type_code': 'pj',
                                 'memory_type': 'pj'})[1])
        assert any('memory_type' in w for w in out['warnings'])

    def test_long_rule_is_warned(self, server):
        out = json.loads(server({'slug': 'd', 'rule': 'x' * 401,
                                 'type_code': 'pj'})[1])
        assert any('401 characters' in w for w in out['warnings'])


def _stored(repo, **kw):
    base = dict(type_code='fb', slug='m', rule='r', priority=2,
                timestamp=datetime(2026, 9, 20, tzinfo=timezone.utc),
                project='proj')
    base.update(kw)
    m = Mnemonic(**base)
    repo.add(m)
    repo.commit(message='seed', trigger='explicit')
    return m


class TestRepair:
    def test_splits_fields_lists_and_type(self, repo):
        rule = ('FINAL timesheet: 43.0 hours.</rule>\n' + P.format('type_code')
                + 'pj' + END + '\n' + P.format('why') + 'rebuilt' + END + '\n'
                + P.format('tags') + '["ofo", "timesheet"]' + END + '\n'
                + P.format('supersedes') + '["old-sheet"]')
        _stored(repo, rule=rule, tags=['kept'])
        rep = markup.repair(repo.get('m'))
        f = rep.fixed
        assert f.rule == 'FINAL timesheet: 43.0 hours.'
        assert f.type_code == 'pj' and rep.type_changed == ('fb', 'pj')
        assert f.why == 'rebuilt'
        assert f.tags == ['kept', 'ofo', 'timesheet']
        assert f.supersedes == ['old-sheet']
        assert f.timestamp == datetime(2026, 9, 20, tzinfo=timezone.utc)

    def test_drops_the_next_tool_call(self, repo):
        _stored(repo, rule='X.' + END + '\n</invoke>\n<invoke name="Bash">'
                + P.format('command') + 'ls')
        f = markup.repair(repo.get('m')).fixed
        assert f.rule == 'X.' and f.why is None

    def test_stray_body_closer(self, repo):
        _stored(repo, body='Detail.</body>\n')
        assert markup.repair(repo.get('m')).fixed.body == 'Detail.'

    def test_clean_memory_is_left_alone(self, repo):
        _stored(repo, rule='Quoting `</rule>` is fine.')
        assert markup.repair(repo.get('m')) is None

    def test_doctor_dry_run_then_apply(self, repo, tmp_path, monkeypatch):
        from memgit.cli import cli
        _stored(repo, rule='X.</rule>\n' + P.format('why') + 'Y')
        monkeypatch.chdir(tmp_path / 'r')
        monkeypatch.setenv('MEMGIT_STORE', str(tmp_path / 'r'))
        r = CliRunner().invoke(cli, ['doctor'])
        assert '1 memories carry tool-call markup' in r.output
        r = CliRunner().invoke(cli, ['doctor', '--repair-markup'])
        assert 'would repair 1' in r.output
        assert repo.get('m').rule.startswith('X.</rule>')
        r = CliRunner().invoke(cli, ['doctor', '--repair-markup', '--yes'])
        assert 'repaired 1' in r.output, r.output
        m = repo.get('m')
        assert (m.rule, m.why) == ('X.', 'Y')


class TestContextNeverServesMarkup:
    def test_resume_digest_and_recall_are_clean(self, repo):
        damaged = 'Always X.</rule>\n' + P.format('why') + 'Y'
        _stored(repo, slug='crit', rule=damaged, priority=3)
        _stored(repo, slug='trk', rule=damaged, type_code='tr')
        ctx = repo.resume_context(project='proj')
        blob = json.dumps(ctx, default=str)
        assert '<parameter' not in blob and '</rule>' not in blob
        assert 'Always X.' in blob
