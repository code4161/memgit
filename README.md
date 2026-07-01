<p align="center">
  <img src="assets/logo.png" alt="memgit logo" width="120" />
</p>

# memgit — git for AI memory

**Your AI assistants forget everything when the session ends. memgit fixes that.**

Version-controlled, cross-AI context that persists, diffs, rolls back, and syncs like code. Switch from Claude to Cursor to ChatGPT mid-project — your context is already there.

[![PyPI](https://img.shields.io/pypi/v/memgit)](https://pypi.org/project/memgit/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-48%20passing-brightgreen)](tests/)

---

## Why not claude.md? Why not mem-search?

You've probably already tried both. Here's why they hit a ceiling:

| Capability | claude.md | mem-search plugin | **memgit** |
|---|---|---|---|
| Loads only relevant context | ❌ loads everything | ⚠️ loads recent observations | ✅ BM25 search — top-k per query |
| Version history | ❌ | ❌ | ✅ full commit log |
| Diff between sessions | ❌ | ❌ | ✅ `memgit diff` |
| Roll back a wrong memory | ❌ manual edit | ❌ | ✅ `memgit checkout` |
| Works in Cursor, Windsurf, GPT | ❌ Claude only | ❌ Claude only | ✅ all via MCP / HTTP |
| Team sync | ❌ copy-paste files | ❌ | ✅ `memgit git push` |
| Scales to 10k+ sessions | ❌ file grows | ❌ search slows | ✅ `memgit squash` |
| Measurable token savings | ❌ | ❌ | ✅ `memgit stats` |
| Export / import standard format | ❌ | ❌ | ✅ TOON + git |

---

## Proof — token savings you can measure

Run this on your own store to see the actual numbers:

```
$ memgit stats

  Total memories:   108   (41 feedback · 23 user · 19 project · 12 reference · 8 convention · 5 lesson)
  Priority:          3 critical · 67 medium · 38 low

  Token cost comparison:
  ┌─────────────────────────────────────┬──────────────────┬───────────────────┬─────────────────────┐
  │ Approach                            │ Tokens/session   │ vs full load      │ $/session (GPT-4o)  │
  ├─────────────────────────────────────┼──────────────────┼───────────────────┼─────────────────────┤
  │ claude.md / dump all memories       │ 12,840           │ 100%  baseline    │ $0.0642             │
  │ mem-search plugin (top-20 obs)      │ 6,100 (est.)     │ ~47%              │ $0.0305             │
  │ memgit search (BM25 top-8)          │ 640              │ 5%  (95% savings) │ $0.0032             │
  └─────────────────────────────────────┴──────────────────┴───────────────────┴─────────────────────┘

  Weekly savings (10 sessions/week):
    Tokens saved:   121,600/week
    Cost saved:     $0.61/week  →  $31.70/year  (at GPT-4o input pricing)
```

**Why such a big difference?** claude.md loads *all* context every session. memgit uses BM25 relevance scoring — it loads *only the 8 memories most relevant to the current session*, not everything you've ever recorded.

---

## The git analogy is literal

memgit's data model maps exactly to git:

| memgit | git |
|---|---|
| `mnemonic` | file |
| `MindState` | tree |
| `checkpoint` | commit |
| `thread` | branch |
| `memgit commit` | `git commit` |
| `memgit diff` | `git diff` |
| `memgit log` | `git log` |
| `memgit squash --keep-last 100` | `git rebase -i --autosquash` |
| `memgit git push` | `git push` |

This is not metaphorical — memgit uses a **content-addressed object store** (SHA-256 blobs) identical to git's architecture. Every memory has a stable SHA. Identical content has identical SHAs. Old state is always recoverable.

---

## The store IS a git repo

Every memory is a readable `.toon` file under `memories/`. Push your entire memory set to GitHub with standard git:

```bash
memgit git init --remote git@github.com:yourteam/ai-memory.git
memgit git push
```

Teammates pull and start with your AI's learned rules from session 1:

```bash
git clone git@github.com:yourteam/ai-memory.git ~/.claude/memgit-store
memgit setup all
```

You can `grep`, `git blame`, and `git diff` your memories just like code:

```bash
grep -rl "database" ~/.claude/memgit-store/memories/
git log --follow memories/no-db-mock.toon
git diff HEAD~7 memories/
```

---

## Install

**Mac / Linux:**
```bash
pip install memgit
```

**Mac (Homebrew):**
```bash
brew tap code4161/tap && brew install memgit
```

**Windows:**
```powershell
choco install memgit
```

**Any AI tool config (no Python needed — npx auto-installs on first run):**
```json
{ "mcpServers": { "memgit": { "command": "npx", "args": ["-y", "memgit-mcp"] } } }
```

---

## Quickstart (3 minutes)

```bash
# 1. Install and initialize
pip install memgit
memgit init               # auto-detects best location (~/.claude/memgit-store etc.)

# 2. Import existing memories (if you use Claude Code)
memgit import claude-code ~/.claude/projects/

# 3. Register with your AI tools (interactive picker)
memgit setup

# 4. See your token savings
memgit stats
```

Restart your AI tool — it now searches your memory store at the start of every session.

---

## Scale to 10,000+ sessions

After months of use, your checkpoint history grows. `memgit squash` handles it:

```bash
memgit squash --keep-last 100    # keep last 100 checkpoints, squash everything older
memgit squash --older-than 30    # squash everything older than 30 days
memgit squash --dry-run          # preview first
```

The current memory **state is always preserved** — squash only compresses the historical chain.

---

## What the AI sees

Once registered via MCP, every AI tool gets 5 tools:

| Tool | When the AI uses it |
|---|---|
| `search_memories` | Start of every session — loads relevant context automatically |
| `get_memory` | When it needs full details of a specific memory |
| `list_memories` | To browse or audit what's stored |
| `save_memory` | When it learns something worth keeping for next time |
| `get_checkpoint_log` | To check when memories were last synced |

The tool descriptions tell the AI **when** to call each one — making it default behavior, not opt-in.

---

## Commands

```bash
# Core (git-like)
memgit init                       # initialize store (auto-detects best path)
memgit add <slug> <rule>          # stage a memory
memgit commit -m "message"        # checkpoint current state
memgit log                        # history
memgit diff [sha1] [sha2]         # what changed
memgit show <slug>                # display a memory
memgit remove <slug>              # remove from active index (history preserved)
memgit status                     # staged changes
memgit search <query>             # BM25 relevance search
memgit squash                     # compress old history

# Scale & proof
memgit stats                      # token savings vs alternatives
memgit lint                       # validate all memories
memgit fsck                       # verify store integrity

# Import / export
memgit sync                       # sync from Claude Code files + commit
memgit import claude-code <path>
memgit import file <path>
memgit export <slug>

# Git sync (team features)
memgit git init [--remote URL]
memgit git push [remote] [branch]
memgit git pull [remote] [branch]
memgit git export
memgit git status

# AI tool registration
memgit setup                      # interactive step-by-step picker
memgit setup all                  # auto-register every detected tool
memgit setup claude-code
memgit setup cursor
memgit setup windsurf
memgit setup cline
memgit setup continue

# Server
memgit serve                      # MCP stdio (Claude Code, Cursor, Windsurf, Cline)
memgit serve --http               # HTTP REST (ChatGPT Custom Actions, Gemini)

# Visualization
memgit graph                      # D3.js interactive relationship map
memgit thread list / switch / create
```

---

## AI tool support

| Tool | Protocol | Command |
|---|---|---|
| **Claude Code** | MCP stdio | `memgit setup claude-code` |
| **Claude Desktop** | MCP stdio | `memgit setup claude-desktop` |
| **Cursor** | MCP stdio | `memgit setup cursor` |
| **Windsurf** | MCP stdio | `memgit setup windsurf` |
| **Cline / Roo-Code** | MCP stdio | `memgit setup cline` |
| **Continue.dev** | MCP stdio | `memgit setup continue` |
| **ChatGPT (Custom Actions)** | HTTP + OpenAPI | `memgit serve --http` → import `http://localhost:7474/openapi.json` |
| **Gemini API** | HTTP function calling | `memgit serve --http` + `llm-tool-definitions.json` |
| **Any MCP tool** | MCP stdio | Add `{"command": "memgit", "args": ["serve"]}` to config |

---

## TOON format — why it's 40–55% more token-efficient

Standard markdown memory file:
```markdown
## Rule: Never mock the database in tests
**Type:** feedback  
**Priority:** medium  
**Why:** We got burned last quarter — mocked tests passed but the prod migration failed.  
**When to apply:** Any time writing tests that touch persistence layers.  
**Tags:** testing, database
```
*~62 tokens*

The same memory in TOON:
```
TOON1|fb|no-db-mock|2026-07-01T10:00Z
#testing #database
RULE:Never mock the database in tests
WHY:Mocked tests passed but prod migration failed last quarter
WHEN:Any persistence test
```
*~35 tokens — 44% fewer for identical content*

At 108 memories: **12,840 tokens (markdown) → 640 tokens (memgit BM25 top-8)**

---

## Architecture

```
~/.claude/memgit-store/
  .memgit/
    objects/     ← SHA-256 content-addressed blobs (gzip compressed)
    refs/threads/main   ← HEAD checkpoint SHA
    TOON_INDEX   ← active slug→sha mapping
    config       ← author, default thread
    logs/        ← ref change audit trail
  memories/      ← flat .toon files (git-trackable, human-readable)
  .git/          ← standard git repo (after `memgit git init`)
```

---

## Contributing

```bash
git clone https://github.com/code4161/memgit.git
cd memgit
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest    # 48 tests, all passing, < 1 second
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Roadmap

- [x] Content-addressed object store (git-identical architecture)
- [x] TOON format (40–55% token reduction vs markdown)
- [x] MCP server — Claude Code, Cursor, Windsurf, Cline, Continue.dev
- [x] HTTP server — ChatGPT Custom Actions, Gemini function calling
- [x] BM25 relevance search (load only what matters)
- [x] `memgit stats` — measured token savings proof
- [x] `memgit squash` — scale to 10k+ sessions
- [x] `memgit git push/pull` — team sync via standard git
- [x] Flat `memories/` directory — grep/diff/blame your memories
- [x] D3.js graph visualization of memory relationships
- [x] PyPI + Homebrew + npm + Chocolatey published (v0.1.2)
- [x] Interactive setup wizard (`memgit setup`)
- [x] Smart `memgit init` (auto-detects tool, no path needed)
- [ ] VS Code extension (Phase 3)
- [ ] JetBrains plugin (Phase 3)
- [ ] Semantic search via embeddings (Phase 4)
- [ ] memgit.dev website (Phase 4)
- [ ] Memory compression / auto-summarization (Phase 5)
- [ ] Team access control + audit trail (Phase 5)
- [ ] Memory marketplace — share reusable context packs (Phase 6)

---

## License

MIT — see [LICENSE](LICENSE).
