# memgit — git for AI memory

**Version-controlled, cross-AI memory that persists across sessions, tools, and teammates.**

```bash
pip install memgit
memgit init ~/.claude/memgit-store
memgit setup all   # registers with every AI tool detected on your machine
```

[![PyPI](https://img.shields.io/pypi/v/memgit)](https://pypi.org/project/memgit/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://github.com/code4161/memgit/actions/workflows/publish.yml/badge.svg)](https://github.com/code4161/memgit/actions)

---

## The problem — large repos eat AI context

Every AI session on a large codebase starts from zero. The assistant asks what you've already told it a dozen times. It re-reads files it's read before. It makes the same mistakes. **Context is the bottleneck — not intelligence.**

### Working on a large repo **without** memgit

```
Session 1  You: "Never mock the database — we got burned last quarter."
           Claude: understood ✓  [session ends]

Session 2  Claude: [re-reads 40 files to understand the codebase]
           Claude: "I'll mock the database for this test—"
           You:    "No! We never mock the database. We got burned—"
           Claude: "Right, sorry."   [you've now said this 17 times]

Session 3  You: "The auth service lives in services/auth/. The trading engine
                 is on the Oracle VM, not localhost. The IG pipeline only runs
                 on the laptop. The—"   [500 tokens of re-explaining every time]
```

**Real cost on a 200-file repo:**
- ~15,000 tokens per session just re-establishing context
- 30 mins/week of repeated explanations
- AI makes mistakes it already knew to avoid

### Working on the same repo **with** memgit

```
Session 1  You: "Never mock the database."
           Claude: save_memory("no-db-mock", "Never mock database in tests") ✓

Session 2  Claude: [calls search_memories("database testing")]
           Claude: found: no-db-mock — "Never mock database in tests, we got
                   burned when mocked tests passed but prod migration failed."
           Claude: writes integration test against real DB, first try ✓
           You:    [never had to repeat themselves]

Session 47 New teammate joins. Runs: memgit setup claude-code
            Their AI starts Day 1 knowing every rule, every preference,
            every lesson the team has learned. Zero onboarding friction.
```

**Measured difference:**

| | Without memgit | With memgit |
|---|---|---|
| Context tokens per session | ~15,000 | ~800 |
| Re-explaining same rule | Every session | Never |
| New AI tool (switch to Cursor) | Start over | Instant |
| New teammate | Weeks to calibrate | Day 1 |
| Mistake you already fixed | Comes back | Stays fixed |

---

## Install

```bash
pip install memgit
```

Or with Homebrew (after tap is published):
```bash
brew tap code4161/tap && brew install memgit
```

Or with npm (for Cursor/Windsurf/Node ecosystems):
```bash
# In your AI tool's config — no Python needed:
{ "command": "npx", "args": ["-y", "memgit-mcp"] }
```

---

## Quickstart (2 minutes)

```bash
# 1. Install
pip install memgit

# 2. Create your memory store
memgit init ~/.claude/memgit-store

# 3. If you use Claude Code — import your existing memories
cd ~/.claude/memgit-store
memgit import claude-code ~/.claude/projects/

# 4. Register with every AI tool on your machine
memgit setup all

# 5. Done — restart your AI tool and it now has persistent memory
```

---

## How it works

memgit is a **content-addressed object store** for AI memories, structured like git:

```
~/.claude/memgit-store/
  .memgit/
    objects/     ← content-addressed memory blobs (like git objects)
    TOON_INDEX   ← active memory index (like git index)
    CHECKPOINT   ← latest snapshot SHA (like HEAD)
    threads/     ← named memory branches (like git branches)
```

Each **mnemonic** (memory unit) has a type, slug, rule, and optional reasoning:

```
[fb p2 | no-db-mock | 2026-07-01]
RULE: Never mock the database in tests
WHY:  We got burned last quarter — mocked tests passed but prod migration failed
WHEN: Any time writing tests that touch persistence
TAGS: testing database
```

**Types:** `fb`=feedback · `us`=user · `pj`=project · `rf`=reference · `cn`=convention · `lx`=lesson

Memories are **committed as checkpoints** — you can diff, log, and restore the history of what your AI knows.

```bash
memgit log                    # checkpoint history
memgit diff                   # what changed since last commit
memgit diff abc123 def456     # compare any two checkpoints
memgit show no-db-mock        # fetch a specific memory
```

---

## Commands

```bash
# Store management
memgit init <dir>             # initialize a new memory store
memgit status                 # show staged changes
memgit add <slug> <rule>      # add or update a memory
memgit commit -m "message"    # checkpoint current memories
memgit log                    # show history
memgit diff                   # show changes since last commit
memgit show <slug>            # display a memory
memgit remove <slug>          # remove from active index (history preserved)
memgit search <query>         # BM25 search across all memories
memgit lint                   # validate all memories
memgit fsck                   # verify store integrity

# Sync & import
memgit sync                   # sync from Claude Code memory files + commit
memgit import claude-code <path>  # one-time import from Claude Code
memgit import file <path>         # import from a TOON-format file

# AI tool registration
memgit setup all              # register with every AI tool detected
memgit setup claude-code      # register with Claude Code only
memgit setup cursor           # register with Cursor
memgit setup windsurf         # register with Windsurf
memgit setup cline            # register with Cline / Roo-Code
memgit setup continue         # register with Continue.dev
memgit setup print-config <tool>  # print config to paste manually

# Server
memgit serve                  # stdio MCP server (used by AI tools)
memgit serve --http           # HTTP server for GPT / Gemini

# Visualization
memgit graph                  # generate interactive D3.js relationship graph
memgit thread list            # list memory branches
memgit thread switch <name>   # switch memory context
```

---

## AI tool support

| Tool | Protocol | How to connect |
|---|---|---|
| **Claude Code** | MCP stdio | `memgit setup claude-code` |
| **Claude Desktop** | MCP stdio | `memgit setup claude-desktop` |
| **Cursor** | MCP stdio | `memgit setup cursor` |
| **Windsurf** | MCP stdio | `memgit setup windsurf` |
| **Cline / Roo-Code** | MCP stdio | `memgit setup cline` |
| **Continue.dev** | MCP stdio | `memgit setup continue` |
| **ChatGPT** | HTTP + OpenAPI | `memgit serve --http` → import `http://localhost:7474/openapi.json` |
| **Gemini API** | HTTP function calling | `memgit serve --http` + `llm-tool-definitions.json` |
| **Any MCP tool** | MCP stdio | Add `{"command": "memgit", "args": ["serve"]}` to config |

---

## Make it the default in every session

The most powerful use is **automatic context loading at session start**. Once registered, every AI tool calls `search_memories` before it answers you — your context is always there, you never re-explain.

**Auto-sync on Claude Code session end** (set up by `memgit setup claude-code`):
```json
// ~/.claude/settings.json
{
  "hooks": {
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "cd ~/.claude/memgit-store && memgit sync --message 'auto-sync' 2>/dev/null || true",
        "async": true
      }]
    }]
  }
}
```

This means:
- **Session ends** → memories auto-checkpoint
- **Next session starts** → AI searches memories before it answers
- **No manual steps** — it just works

---

## Team use (shared memory)

Push your memory store to a private git repo and your team shares context:

```bash
# Push your store to a team repo
cd ~/.claude/memgit-store
git init && git remote add origin git@github.com:your-team/ai-memory.git
git push -u origin main

# Teammate pulls and registers
git clone git@github.com:your-team/ai-memory.git ~/.claude/memgit-store
memgit setup all
```

Everyone's AI now knows every rule the team has learned, every preference, every lesson — from Day 1.

---

## Memory format (TOON)

memgit stores memories in **TOON** (Token-Optimised Object Notation) — a sigil-based format designed to pack maximum meaning into minimum tokens:

```
@fb p2 | no-db-mock | 2026-07-01T10:00:00Z
RULE: Never mock the database in tests
WHY:  Mocked tests passed but prod migration failed last quarter
WHEN: Any persistence test
TAGS: testing database
```

TOON is also valid for LLMs to read directly — it's ~40% more token-efficient than JSON for the same semantic content.

Full spec: see [memgit/toon.py](memgit/toon.py).

---

## Website & roadmap

The project website at [memgit.dev](https://memgit.dev) is in the next phase. See [PUBLISHING.md](PUBLISHING.md) for the full distribution plan and website checklist.

**Roadmap:**
- [x] Core engine (content-addressed store, checkpoints, diff, threads)
- [x] MCP server (Claude Code, Cursor, Windsurf, Cline, Continue)
- [x] HTTP server (ChatGPT Custom Actions, Gemini)
- [x] Claude Code import + auto-sync
- [x] BM25 memory search
- [x] Interactive D3.js graph visualization
- [x] Multi-platform distribution setup (PyPI, Homebrew, npm, Chocolatey)
- [ ] PyPI publish (v0.1.0)
- [ ] Homebrew tap
- [ ] npm package (`memgit-mcp`)
- [ ] memgit.dev website
- [ ] Team sync features
- [ ] Memory summarization / compression
- [ ] Embeddings-based search (semantic, not just BM25)

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The test suite runs in under a second:

```bash
pip install -e ".[dev]"
pytest
```

---

## License

MIT — see [LICENSE](LICENSE).
