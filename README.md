<p align="center">
  <img src="assets/logo.png" alt="memgit logo" width="120" />
</p>

# memgit — git for AI memory

**Version-controlled, cross-AI context that persists, diffs, rolls back, and syncs like code.**

```bash
# Mac / Linux
pip install memgit

# Mac (Homebrew)
brew tap code4161/tap && brew install memgit

# Windows
choco install memgit

# Any AI tool config (no Python needed)
npx memgit-mcp
```

```bash
memgit init               # auto-detects best location for your setup
memgit setup              # step-by-step: pick which AI tools to register
memgit stats              # see your token savings vs claude.md / other plugins
```

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

**Why such a big difference?** claude.md loads *all* context every session. mem-search loads recent observations. memgit uses BM25 relevance scoring — it loads *only the 8 memories most relevant to the current session*, not everything you've ever recorded.

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

And this is not metaphorical — memgit uses a **content-addressed object store** (SHA-256 blobs) identical to git's architecture. Every memory has a stable SHA. Identical content has identical SHAs. The object store is tamper-evident.

---

## The store IS a git repo

Every memory is a readable `.toon` file under `memories/`. You can push your entire memory set to GitHub with standard git:

```bash
cd ~/.claude/memgit-store
git init
git remote add origin git@github.com:yourteam/ai-memory.git
git add memories/ .memgit/refs/
git commit -m "session memories"
git push
```

Or use the built-in command:

```bash
memgit git init --remote git@github.com:yourteam/ai-memory.git
memgit git push
```

Teammates pull and get your AI's learned rules, preferences, and lessons instantly:

```bash
git clone git@github.com:yourteam/ai-memory.git ~/.claude/memgit-store
memgit setup all
# Their AI now knows everything your AI knows — from session 1
```

You can `grep`, `git blame`, and `git diff` your memories just like code:

```bash
# Search across all memories
grep -rl "database" ~/.claude/memgit-store/memories/

# See who changed what
git log --follow memories/no-db-mock.toon

# What changed this week?
git diff HEAD~7 memories/
```

---

## Install

```bash
pip install memgit
```

Homebrew (after tap published):
```bash
brew tap code4161/tap && brew install memgit
```

npm (for Node-based tools — no Python needed):
```bash
# In any AI tool's MCP config:
{ "command": "npx", "args": ["-y", "memgit-mcp"] }
```

---

## Quickstart (3 minutes)

```bash
# 1. Install and initialize
pip install memgit
memgit init ~/.claude/memgit-store

# 2. Import existing memories (if you use Claude Code)
cd ~/.claude/memgit-store
memgit import claude-code ~/.claude/projects/

# 3. Register with every AI tool on your machine
memgit setup all

# 4. See your token savings
memgit stats

# 5. Push to share with teammates
memgit git init --remote git@github.com:yourteam/ai-memory.git
memgit git push
```

Restart your AI tool — it now searches your memory store at the start of every session.

---

## Scale to 10,000+ sessions

After months of use, your checkpoint history grows. `memgit squash` handles it — like `git rebase --autosquash` but automatic:

```bash
# Keep last 100 checkpoints; squash everything older into one baseline
memgit squash --keep-last 100

# Squash everything older than 30 days
memgit squash --older-than 30

# Preview first
memgit squash --keep-last 100 --dry-run
# → would squash 847 checkpoints (baseline: 2026-04-01) → keep 100 recent ones

# After squash: history is compact, current memories are fully preserved
memgit log --oneline  # clean, readable history
memgit list           # all memories still there
```

The current memory **state is always preserved** — squash only compresses the historical chain. At 10 sessions/day, squash once a month to keep history manageable.

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

The tool descriptions tell the AI **when** to call each one — including "call `search_memories` at the start of every session." This is what makes it default behavior, not opt-in.

---

## Commands

```bash
# Core (git-like)
memgit init <dir>             # initialize store
memgit add <slug> <rule>      # stage a memory
memgit commit -m "message"    # checkpoint current state
memgit log                    # history
memgit diff [sha1] [sha2]     # what changed
memgit show <slug>            # display a memory
memgit remove <slug>          # remove from active index (history preserved)
memgit status                 # staged changes
memgit search <query>         # BM25 relevance search
memgit squash                 # compress old history

# Scale & proof
memgit stats                  # token savings vs alternatives
memgit lint                   # validate all memories
memgit fsck                   # verify store integrity

# Import / export
memgit sync                   # sync from Claude Code files + commit
memgit import claude-code <path>
memgit import file <path>
memgit export <slug>

# Git sync (team features)
memgit git init [--remote URL]   # initialize git in the store
memgit git push [remote] [branch]
memgit git pull [remote] [branch]
memgit git export                # write flat memories/ files
memgit git status                # changes since last git commit

# AI tool registration
memgit setup all
memgit setup claude-code
memgit setup cursor
memgit setup windsurf
memgit setup cline
memgit setup continue
memgit setup print-config <tool>

# Server
memgit serve                  # MCP stdio (Claude Code, Cursor, Windsurf, Cline)
memgit serve --http           # HTTP REST (ChatGPT Custom Actions, Gemini)

# Visualization
memgit graph                  # D3.js interactive relationship map
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

## Default in every session — no manual steps

`memgit setup claude-code` installs a Stop hook that auto-syncs memories when you end a session:

```json
// ~/.claude/settings.json (added automatically)
{
  "hooks": {
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "cd ~/.claude/memgit-store && memgit sync 2>/dev/null || true",
        "async": true
      }]
    }]
  }
}
```

And the MCP server's `search_memories` description tells every AI: *"call this at the start of every session."* This is enforced in the tool schema — the AI sees it as a required step, not an option.

---

## TOON format — why it's 40–55% more token-efficient

Standard markdown memory file (what claude.md uses):

```markdown
## Rule: Never mock the database in tests
**Type:** feedback  
**Priority:** medium  
**Why:** We got burned last quarter — mocked tests passed but the prod migration failed.  
**When to apply:** Any time writing tests that touch persistence layers.  
**Tags:** testing, database
```
*Token count: ~62*

The same memory in TOON:

```
TOON1|fb|no-db-mock|2026-07-01T10:00Z
#testing #database
RULE:Never mock the database in tests
WHY:Mocked tests passed but prod migration failed last quarter
WHEN:Any persistence test
```
*Token count: ~35*  **→ 44% fewer tokens for identical content**

At 108 memories: **12,840 tokens (markdown) → 7,100 tokens (TOON) → 640 tokens (memgit search top-8)**

---

## The business case — agent memory is the next asset class

Source code is version-controlled because it's a company's primary asset. In 2026, **agent memory is equally valuable**:

- Every AI session produces learned rules, discovered preferences, fixed mistakes
- Today: these vanish when the session ends, or accumulate in unversioned markdown files
- Tomorrow: teams will track, audit, merge, and ship their AI context as carefully as they ship code

memgit is the git layer for that transition. Built for the moment when "what did the AI know when it made that decision?" becomes as important as "who wrote that line of code?"

---

## Team workflow

```
# Day 1: Set up shared memory
memgit git init --remote git@github.com:acme/ai-memory.git
memgit git push

# Every session: memories auto-sync via Stop hook
[session ends] → memgit sync → new checkpoint created

# Weekly: push to share with team
memgit git push

# New teammate joins:
git clone git@github.com:acme/ai-memory.git ~/.claude/memgit-store
memgit setup all
# Their AI starts with 6 months of team-learned context — Day 1
```

---

## Architecture

```
~/.claude/memgit-store/
  .memgit/
    objects/     ← SHA-256 content-addressed blobs (gzip compressed)
    refs/threads/main   ← HEAD checkpoint SHA
    TOON_INDEX   ← active slug→sha mapping (cache, recoverable via fsck)
    config       ← author, default thread
    logs/        ← ref change audit trail
  memories/      ← flat .toon files (git-trackable, human-readable)
    no-db-mock.toon
    trading-rules.toon
    ...
  .git/          ← standard git repo (after `memgit git init`)
  .gitignore     ← excludes .memgit/objects/ (binary blobs)
```

The object store is **content-addressed**: same memory content = same SHA = stored once. Modifying a memory creates a new object and a new checkpoint pointing to it. Old state is always recoverable.

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
- [x] Multi-platform distribution (PyPI, Homebrew, npm, Chocolatey, winget)
- [x] PyPI published (v0.1.1)
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
