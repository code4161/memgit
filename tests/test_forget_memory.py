"""forget_memory: the MCP path for removing a memory that nothing replaces.

Glama's tool review (2026-11-11) named the gap: agents could supersede or demote a
memory but had no way to remove one. The CLI has had memgit remove; agents did not.
"""
import asyncio
import json

from mcp import types

from memgit import mcp_server


def _server(store, monkeypatch):
    holder = {}

    class Capture(mcp_server.Server):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            holder['s'] = self

    monkeypatch.setattr(mcp_server, 'Server', Capture)
    monkeypatch.setattr(asyncio, 'run', lambda coro: coro.close())
    monkeypatch.setenv('MEMGIT_PROJECT', 'proj')
    monkeypatch.setenv('MEMGIT_NO_AUTOSYNC', '1')
    mcp_server.run_server(store)
    srv = holder['s']

    def run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def call(name, arguments):
        req = types.CallToolRequest(method='tools/call', params=types.CallToolRequestParams(
            name=name, arguments=arguments))
        return run(srv.request_handlers[types.CallToolRequest](req)).root.content[0].text

    def tools():
        req = types.ListToolsRequest(method='tools/list')
        return run(srv.request_handlers[types.ListToolsRequest](req)).root.tools

    return call, tools


def test_forget_is_listed_with_a_required_slug(tmp_path, monkeypatch):
    _, tools = _server(tmp_path / 'store', monkeypatch)
    t = {x.name: x for x in tools()}
    assert 'forget_memory' in t
    assert t['forget_memory'].inputSchema['required'] == ['slug']


def test_forget_removes_from_recall_records_a_checkpoint_and_returns_the_memory(tmp_path, monkeypatch):
    call, _ = _server(tmp_path / 'store', monkeypatch)
    call('save_memory', {'slug': 'old-build-cmd', 'rule': 'build with make legacy', 'type_code': 'cn'})
    assert 'old-build-cmd' in call('search_memories', {'query': 'make legacy'})

    out = json.loads(call('forget_memory', {'slug': 'old-build-cmd', 'reason': 'makefile removed'}))
    assert out['status'] == 'ok' and out['action'] == 'forgotten'
    assert out['forgotten']['rule'] == 'build with make legacy'
    assert out['checkpoint']

    assert 'old-build-cmd' not in call('search_memories', {'query': 'make legacy'})
    assert 'no memory' in call('get_memory', {'slug': 'old-build-cmd'}).lower() or \
        'not found' in call('get_memory', {'slug': 'old-build-cmd'}).lower()
    log = call('get_checkpoint_log', {'limit': 3})
    assert 'forget: old-build-cmd (makefile removed)' in log


def test_forget_can_be_undone_by_saving_the_returned_memory(tmp_path, monkeypatch):
    call, _ = _server(tmp_path / 'store', monkeypatch)
    call('save_memory', {'slug': 'keep-me', 'rule': 'deploy on tuesdays', 'type_code': 'pj'})
    out = json.loads(call('forget_memory', {'slug': 'keep-me'}))
    call('save_memory', {'slug': 'keep-me', 'rule': out['forgotten']['rule'],
                         'type_code': out['forgotten']['type']})
    assert 'keep-me' in call('search_memories', {'query': 'deploy tuesdays'})


def test_critical_memory_needs_confirm(tmp_path, monkeypatch):
    call, _ = _server(tmp_path / 'store', monkeypatch)
    call('save_memory', {'slug': 'never-push-main', 'rule': 'never push to main',
                         'type_code': 'fb', 'priority': 3})
    refused = json.loads(call('forget_memory', {'slug': 'never-push-main'}))
    assert refused['status'] == 'refused'
    assert 'never-push-main' in call('search_memories', {'query': 'push main'})

    done = json.loads(call('forget_memory', {'slug': 'never-push-main', 'confirm': True}))
    assert done['status'] == 'ok'
    assert 'never-push-main' not in call('search_memories', {'query': 'push main'})


def test_unknown_slug_is_an_error_and_changes_nothing(tmp_path, monkeypatch):
    call, _ = _server(tmp_path / 'store', monkeypatch)
    call('save_memory', {'slug': 'a-fact', 'rule': 'a fact', 'type_code': 'pj'})
    before = call('get_checkpoint_log', {'limit': 5})
    assert 'no memory' in call('forget_memory', {'slug': 'missing'}).lower()
    assert call('get_checkpoint_log', {'limit': 5}) == before
