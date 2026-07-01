"""Tests for `memgit setup` MCP registration paths."""

import json
from pathlib import Path

import pytest

from memgit import cli as cli_mod
from memgit.cli import (
    _all_targets,
    _cleanup_legacy_claude_code,
    _patch_mcp_servers,
)


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    return tmp_path


def test_claude_code_target_is_claude_json(fake_home):
    """Claude Code loads MCP servers from ~/.claude.json, NOT ~/.claude/settings.json."""
    targets = {label: (config, detect) for label, config, _, detect in _all_targets()}
    config, detect = targets['Claude Code']
    assert config == fake_home / '.claude.json'
    assert detect == fake_home / '.claude'


def test_patch_registers_and_is_idempotent(fake_home):
    config = fake_home / '.claude.json'
    assert _patch_mcp_servers(config) == 'registered'
    data = json.loads(config.read_text())
    assert 'memgit' in data['mcpServers']
    assert data['mcpServers']['memgit']['args'][-1] == 'serve'
    assert _patch_mcp_servers(config) == 'already registered'


def test_patch_preserves_existing_state(fake_home):
    """~/.claude.json holds all Claude Code user state — never drop other keys."""
    config = fake_home / '.claude.json'
    config.write_text(json.dumps({'projects': {'/x': {}}, 'mcpServers': {'other': {'command': 'x'}}}))
    _patch_mcp_servers(config)
    data = json.loads(config.read_text())
    assert data['projects'] == {'/x': {}}
    assert set(data['mcpServers']) == {'other', 'memgit'}


def test_patch_refuses_to_clobber_invalid_json(fake_home):
    config = fake_home / '.claude.json'
    config.write_text('{not json')
    with pytest.raises(RuntimeError, match='not valid JSON'):
        _patch_mcp_servers(config)
    assert config.read_text() == '{not json'


def test_cleanup_removes_legacy_entry(fake_home):
    legacy = fake_home / '.claude' / 'settings.json'
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({'theme': 'dark', 'mcpServers': {'memgit': {'command': 'memgit'}}}))
    _cleanup_legacy_claude_code()
    data = json.loads(legacy.read_text())
    assert data['theme'] == 'dark'
    assert 'mcpServers' not in data


def test_cleanup_keeps_other_servers(fake_home):
    legacy = fake_home / '.claude' / 'settings.json'
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({'mcpServers': {'memgit': {}, 'other': {'command': 'x'}}}))
    _cleanup_legacy_claude_code()
    data = json.loads(legacy.read_text())
    assert set(data['mcpServers']) == {'other'}


def test_cleanup_noop_without_legacy_file(fake_home):
    _cleanup_legacy_claude_code()  # must not raise or create files
    assert not (fake_home / '.claude' / 'settings.json').exists()
