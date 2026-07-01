# Contributing to memgit

## Setup

```bash
git clone https://github.com/code4161/memgit.git
cd memgit
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Add dev dependencies to `pyproject.toml` if you need more than `pytest`.

## Running tests

```bash
pytest              # all 27 tests, under 1 second
pytest -v           # verbose
pytest tests/test_toon.py  # one module
```

## Project structure

```
memgit/
  cli.py          ← Click command definitions
  repo.py         ← Repository: add/commit/diff/log/list
  store.py        ← ObjectStore: content-addressed SHA blobs
  toon.py         ← TOON format parser/serializer
  models.py       ← Mnemonic, MindState, Checkpoint dataclasses
  mcp_server.py   ← stdio MCP server (5 tools)
  http_server.py  ← FastAPI HTTP server for GPT/Gemini
  scorer.py       ← BM25 relevance scoring
  importer.py     ← Claude Code memory file importer
  graph.py        ← D3.js graph generator

tests/
  test_store_repo.py  ← ObjectStore + Repository unit tests
  test_toon.py        ← TOON parse/serialize roundtrip tests
```

## Architecture notes

- **No database** — the object store is just files, like git. Content-addressed by SHA-256.
- **TOON_INDEX** is a cache (recoverable from the object store via `memgit fsck --rebuild`).
- **Threads** are cheap — they just point to different checkpoints.
- **MCP stdio** is the primary integration path; HTTP is a shim for tools that don't support MCP.

## What to work on

Open issues on GitHub. Good first contributions:
- Additional AI tool support (new `memgit setup <tool>` targets)
- Semantic search (embeddings-based, not just BM25)
- Memory summarization / compression for large stores
- Windows path handling improvements

## Submitting a PR

1. Fork, branch off `main`
2. Write a test for the change
3. `pytest` must pass 100%
4. Open PR — describe what and why, not just what
