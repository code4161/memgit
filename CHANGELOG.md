# Changelog

## [0.2.0] — 2026-07-02

Session resume, garbage collection, and multi-agent write safety.

### Added
- **`memgit resume`** — a bounded "where we left off" digest: last checkpoints, staged work in flight, recently updated memories, and critical rules. `--plain` for context injection, `--json` for tooling. Measured ~335 tokens regardless of store size (rules clipped, critical list capped at 20).
- **`resume_session` MCP tool** — same digest for AI clients; the authoritative record of last actions, so agents stop guessing session state from open files. Also `GET /resume` on the HTTP server and `resume_session` entries in `llm-tool-definitions.json` / `openapi.json`.
- **`memgit setup hooks`** — installs a Claude Code SessionStart hook that injects `memgit resume --plain` into every new session automatically (`--remove` to uninstall). The model sees your last actions without having to decide to look.
- **`memgit gc`** — mark-and-sweep space reclamation: deletes only provably-unreachable objects (reachable history and staged memories are never touched), trims reflogs, reports bytes freed. `--dry-run`, `--squash-keep N` to compact then sweep. Benchmark: a 2,000-checkpoint store shrank 94% (39.5 MB → 2.2 MB) with `fsck` clean.
- **`memgit merge <thread>`** — three-way merge of another thread into the current one (nearest-common-ancestor based). Enables branch-per-agent workflows: each agent works on its own thread, results merge back. Conflicts resolve to the newest mnemonic; an edit always beats a delete.
- **Store-wide write lock** — git-style lockfile with stale-lock breaking (dead pid or >60 s old) serializes concurrent writers; `MEMGIT_LOCK_TIMEOUT` env tunes the wait. Measured overhead: 0.08 ms per acquire/release.
- **Concurrent-commit auto-merge** — the staging index now records its base checkpoint; if another agent moved HEAD since staging, `commit` three-way merges instead of silently clobbering (trigger `merge`, message notes the auto-merge).
- **`MEMGIT_AUTHOR` env** — per-agent checkpoint attribution in multi-agent jobs.
- **`memgit setup gemini-cli`** — register the MCP server with Gemini CLI (`~/.gemini/settings.json`); also included in `setup all` detection.
- `memgit log --skip N` — history pagination.
- `memgit stats` now reports object count and disk usage.
- **AI-operator surface** — memgit's primary operator is an AI agent, so the store signals its own upkeep: `resume`/`status`/`stats` emit a one-line maintenance hint when history passes 500 checkpoints or 50 MB (naming the exact command to run), and `gc`/`squash`/`stats` grew `--json` flags for terse machine-readable output instead of token-heavy rich tables.

### Changed
- **Squash now archives, never discards** — collapsed checkpoints leave one-line records (sha, time, trigger, author, diff, message) in an append-only `.memgit/logs/archive/<thread>` file that gc never touches. Compaction is lossless-in-substance.
- **History operations scale to long chains** — SHA-prefix resolution uses the object-store fan-out directories instead of walking the whole chain (92.7 ms → 0.08 ms at 2,000 checkpoints), and checkpoint counting uses an incrementally-maintained per-thread cache (92 ms → 0.07 ms; self-heals on any mismatch).
- MCP server instructions and tool descriptions now teach *judgment* ("does this request depend on state you don't have?") instead of keyword triggers; server `instructions` are actually passed in the MCP handshake (previously defined but never sent).

### Fixed
- **`squash` silently discarded staged (uncommitted) memories** — it rebuilt the index from the new HEAD; staged work now survives a squash.
- **`python -m memgit.cli` did nothing** — missing `__main__` guard; this was the documented last-resort fallback for MCP registration, which would have produced a silently-dead server.

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
