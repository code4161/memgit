# Changelog

## [0.1.0] — 2026-07-01

### Added
- Core content-addressed object store with SHA-256 content hashing
- TOON (Token-Optimised Object Notation) format — 40% more token-efficient than JSON
- Repository layer: `add`, `commit`, `diff`, `log`, `list`, `remove`, `fsck`, `thread`
- MCP stdio server with 5 tools: `search_memories`, `get_memory`, `list_memories`, `save_memory`, `get_checkpoint_log`
- HTTP server (FastAPI) for ChatGPT Custom Actions and Gemini function calling
- OpenAPI 3.1 spec (`openapi.json`) for GPT integration
- Provider-agnostic tool definitions (`llm-tool-definitions.json`) for any LLM
- BM25 relevance scoring for memory search
- Claude Code memory file importer (`memgit import claude-code`)
- Auto-sync hook integration (`memgit setup claude-code` installs Stop hook)
- `memgit setup all` — auto-detects and registers with all installed AI tools
- Per-tool setup: Claude Code, Claude Desktop, Cursor, Windsurf, Cline, Roo-Code, Continue.dev
- Abbreviated SHA resolution (git-style 8-char short refs in `diff`)
- Interactive D3.js graph visualization of memory relationships (`memgit graph`)
- Multi-platform distribution: PyPI, Homebrew formula, Chocolatey, npm wrapper, winget manifest
- GitHub Actions workflow for automated PyPI publish on git tag
- 27-test suite with 100% pass rate

### Fixed
- Abbreviated SHA resolution in `diff` command (FileNotFoundError on short refs)
- Lint rule length raised from 200 → 400 chars to match real Claude Code memory sizes
- Slug regex relaxed to allow underscores (`^[a-z0-9_-]+$`) matching importer output
