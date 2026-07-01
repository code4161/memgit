# Changelog

## [0.1.5] — 2026-07-02

### Fixed
- **`memgit setup claude-code` registered the MCP server in the wrong file** — it wrote `mcpServers` to `~/.claude/settings.json`, which Claude Code ignores; MCP tools never loaded. Now writes to `~/.claude.json` (user scope) and removes the stale legacy entry automatically. Affects every Claude Code registration made with ≤0.1.4 — re-run `memgit setup claude-code` to fix.
- `memgit setup` no longer overwrites a config file it cannot parse — invalid JSON now aborts with an error instead of silently replacing the file (critical for `~/.claude.json`, which holds all Claude Code user state)
- `memgit setup` / `memgit setup all` detect Claude Code via `~/.claude/` instead of misfiring on the home directory

### Added
- Setup registration test suite (7 tests: correct target file, idempotency, state preservation, invalid-JSON guard, legacy cleanup)

## [0.1.4] — 2026-07-02

### Added
- `memgit rollback <ref>` — restore state to a checkpoint (`HEAD~N` or SHA prefix), git-revert style: creates a new checkpoint, history preserved; `--dry-run` and `-y` flags
- `Repository.resolve_ref()` — resolves `HEAD`, `HEAD~n`, and abbreviated checkpoint SHAs
- Store auto-detect fallback: CLI and MCP server now find the store from any directory (walk-up first, then `~/.claude/memgit-store`, `~/.cursor/memgit-store`, `~/.windsurf/memgit-store`, `~/.memgit-store`)
- Optional exact token counting via tiktoken: `pip install "memgit[tokens]"`

### Fixed
- Priority 1 (low) memories were silently stored as priority 2 — the serializer only emitted the priority flag for priority 3; now round-trips all priorities (with tests)
- `memgit stats` no longer prints an estimated "mem-search plugin" comparison row (the figure was fabricated, not measured)
- `memgit stats` search-cost estimate is now deterministic (top-8 × average memory size) instead of simulated canned queries that under-filled results and inflated savings
- GPT-4o input price corrected to $2.50/M tokens (was $5/M) — all $ savings figures in stats, README, and memgit.dev halved accordingly
- TOON efficiency claims corrected: ~5–10% leaner than markdown with a real tokenizer (the 95% savings figure is from BM25 top-k retrieval, not the format)
- README/docs no longer reference a nonexistent `memgit checkout`; docs pages match actual CLI flags and setup behavior
- USAGE.md rewritten as a generic quick start (previously contained machine-specific paths)

## [0.1.3] — 2026-07-01

### Added
- VS Code extension published to the Marketplace (`code416-memgit.memgit`), with LICENSE and icon
- Daemon HTTP API for IDE integrations (`memgit daemon`)

### Notes
- 0.1.3 is a VS Code–extension-only release; PyPI/npm/Homebrew remain at 0.1.2.

## [0.1.2] — 2026-07-01

### Added
- Smart `memgit init` — auto-detects Claude Code / Cursor / Windsurf and picks the store path, no argument needed
- Interactive setup wizard (`memgit setup`)
- Auto version from package metadata
- npm wrapper `memgit-mcp` published (run the MCP server via `npx memgit-mcp`)
- Homebrew tap `code4161/tap` with formula pinned to the PyPI sdist

## [0.1.1] — 2026-07-01

### Added
- First public PyPI release (0.1.0 was never uploaded to PyPI)

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
