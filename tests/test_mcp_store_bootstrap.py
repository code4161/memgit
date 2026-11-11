"""A host that starts memgit through npx has no CLI on PATH to run `memgit init`.

Measured 2026-10-30: a newcomer's first tool call answered "store not found,
run memgit init", an instruction they could not follow. The server now creates
the store itself.
"""
import asyncio

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


def test_first_tool_call_creates_the_store(tmp_path, monkeypatch):
    store = tmp_path / 'fresh-store'
    call = _server(store, monkeypatch)
    saved = call('save_memory', {
        'slug': 'first-memory', 'rule': 'the store made itself', 'type_code': 'pj'})
    assert 'store not found' not in saved
    assert (store / '.memgit').is_dir()
    assert 'first-memory' in call('search_memories', {'query': 'store made itself'})


def test_an_unreadable_working_directory_is_not_a_crash(tmp_path, monkeypatch):
    """A service account started from another user's home could not run any command."""
    import os
    from pathlib import Path
    from memgit.repo import Repository

    store = tmp_path / 'store'
    Repository.init(store)
    monkeypatch.setenv('MEMGIT_STORE', str(store))
    real = Path.is_dir

    def denied(self):
        if self.name == '.memgit' and store not in self.parents:
            raise PermissionError(13, 'Permission denied', str(self))
        return real(self)

    monkeypatch.setattr(Path, 'is_dir', denied)
    found = Repository.find(tmp_path / 'somewhere' / 'else')
    assert found is not None and found.path == store / '.memgit'
