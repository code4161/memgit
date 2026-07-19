"""Shared test isolation — NO test may ever touch the live memgit store.

`default_store_candidates()` consults MEMGIT_STORE first (and, when set,
exclusively), so pointing it at a per-test tmp path guarantees that every
fallback-discovery surface — `Repository.find`, the hooks' `_find_repo`, the
MCP/HTTP servers' `_default_store` — resolves inside the sandbox and can
never reach `~/.claude/memgit-store`. Detection envs from the invoking shell
(a developer running pytest inside an AI host exports CLAUDE_PROJECT_DIR)
are stripped so project-detection tests see a clean environment.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv('MEMGIT_STORE', str(tmp_path / 'isolated-store'))
    monkeypatch.delenv('MEMGIT_PROJECT', raising=False)
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
