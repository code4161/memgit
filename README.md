<p align="center">
  <img src="assets/logo.png" alt="memgit logo" width="120" />
</p>

# memgit — git for AI memory

**Your AI assistants forget everything when the session ends. memgit fixes that.**

Version-controlled, cross-AI context that persists, diffs, rolls back, and syncs like code. Switch from Claude to Cursor to ChatGPT mid-project — your context is already there.

[![PyPI](https://img.shields.io/pypi/v/memgit)](https://pypi.org/project/memgit/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-294%20passing-brightgreen)](tests/)

---

## Why not claude.md? Why not mem-search?

You've probably already tried both. Here's why they hit a ceiling:

| Capability | claude.md | mem-search plugin | **memgit** |
|---|---|---|---|
| Loads only relevant context | ❌ loads everything | ⚠️ loads recent observations | ✅ BM25 search — top-k per query |
| Project-aware across a multi-repo life | ❌ per-file | ❌ | ✅ memories carry a `project`; the current workspace ranks first |
| Adopt on an existing codebase | ❌ starts blank | ❌ starts blank | ✅ `memgit onboard` — seed the store from the repo in one pass |
| Version history | ❌ | ❌ | ✅ full commit log |
| Diff between sessions | ❌ | ❌ | ✅ `memgit diff` |
| Roll back a wrong memory | ❌ manual edit | ❌ | ✅ `memgit rollback` |
| Works in Cursor, Windsurf, GPT | ❌ Claude only | ❌ Claude only | ✅ all via MCP / HTTP |
| Team sync | ❌ copy-paste files | ❌ | ✅ `memgit git push` |
| Scales to 10k+ sessions | ❌ file grows | ❌ search slows | ✅ `memgit squash` |
| Measurable token savings | ❌ | ❌ | ✅ `memgit stats` |
| Export / import standard format | ❌ | ❌ | ✅ TOON + git |

---

## Proof — context costs you can measure

Run this on your own store to see the actual numbers (measured where possible; estimates labeled):

```
$ memgit stats

  Total memories:   108   (41 feedback · 23 user · 19 project · 12 reference · 8 convention · 5 lesson)
  Priority:          3 critical · 67 medium · 38 low

  Context footprint  (measured where possible; estimates labeled)

  Surface                                             Tokens
  Full store (every memory as context)                12,840
  Resume digest  (measured render)                       540
  Recall block  (estimate: top-3 rules ≈ chars/4)        ~60

  per-session injected ≈ 600 tokens (estimate) vs 12,840 tokens if the full store were loaded
```

**Why such a big difference?** claude.md loads *all* context every session. memgit injects a bounded resume digest plus BM25-matched recall — *only what is relevant to this session*, not everything you've ever recorded. The digest is measured by actually rendering it, and the store total is the real corpus size; nothing here is a simulated benchmark.

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
# or
pip install memgit
```
(The Chocolatey package is live on community.chocolatey.org; newly pushed versions can take a few days to clear moderation — `pip install memgit` always has the latest.)

**Any AI tool config (no Python needed — npx auto-installs on first run):**
```json
{ "mcpServers": { "memgit": { "command": "npx", "args": ["-y", "memgit-mcp"] } } }
```

---

## Quickstart (3 minutes)

```bash
# 1. Install and initialize
pip install memgit
memgit init               # auto-detects the best location, finds your existing
                          # Claude Code memories, and offers to import them

# 2. Register with your AI tools (interactive picker)
memgit setup

# 3. See your token savings
memgit stats
```

`init` walks you through it — no paths to hunt down. (Importing later is one command with no arguments: `memgit sync` auto-finds `~/.claude/projects/*/memory`.)

Restart your AI tool — it now searches your memory store at the start of every session.

---

## Adopting memgit mid-project

Memory tools have a cold-start problem: install one halfway through a project and it knows *nothing* — there's no initial point, and context only trickles in from future sessions. memgit solves this with a one-time seeding pass:

```bash
cd your-project
memgit onboard          # mines the repo, prints the bootstrap brief
```

`onboard` first extracts a **repo digest** deterministically — git history (recent commit subjects, hot files/directories by churn, authors, branch, tags), detected stack from manifests, and the docs worth reading — using bounded, read-only probes that stay near-instant even on huge repositories. The brief then tells your AI agent exactly what to do with it: read only the listed files (no tree crawling), extract 10–20 durable facts (purpose, architecture, conventions, current state, gotchas), save each as a typed memory, and checkpoint the seed set. Paste it into a session — or don't: if the AI searches memory in a project that has none, the MCP server itself replies with the bootstrap instructions instead of a bare "no results."

Memories are **project-scoped, filter-by-default** (v0.7.0): each carries the workspace it belongs to, and searches, recall injections, and the resume digest (recent memories, checkpoints, depth hints) are **filtered** to the current project's family plus explicitly-global memories — another project's content never leaks in. Widen deliberately with `memgit search --all-projects` / `all_projects: true` (every hit then carries its `project` label), or hard-filter one project with `--project`. A memory with no project is **explicitly global** (applies everywhere): save one with `memgit add --global` or `project: ""`. A save whose project *cannot be determined* is never silently global — it's quarantined under `_unknown` (visible in `list` as `[?project]`, flagged by `lint`, surfaced nowhere) until you relabel it with `memgit doctor --relabel`.

---

## Resume where you left off

Ask an AI "can we proceed on the pending tasks?" in a fresh session and it will guess from whatever file happens to be open. `memgit resume` replaces the guess with the record:

```bash
memgit resume            # last checkpoints, work in flight, recent + critical memories
memgit resume --plain    # plain text, for piping into an AI context
memgit resume --json     # for tooling
```

Wire it into Claude Code so memory becomes **automatic** — no tool call, no judgment required:

```bash
memgit setup hooks       # installs all five hooks (~/.claude/settings.json)
```

| Hook | What it enforces |
|---|---|
| `SessionStart` | every session opens with the resume digest in context — status board, checkpoints, critical rules, memory index |
| `UserPromptSubmit` | each prompt is BM25-matched against the store; relevant memories are injected, ending with a "+N more on '<topic>'" depth hint when more exists (silent when nothing clears the relevance bar; never repeats within a session) — `--no-recall` to skip |
| `PostToolUse` | reading a file whose path matches a memory tag surfaces a one-line hint ("6 memories tagged 'x' relate to this path") — tagmap cache only, capped 3/session, `--no-ctx-recall` to skip |
| `Stop` (guard) | a session that did real work but saved nothing gets ONE nudge to save durable facts before finishing — `--no-guard` to skip |
| `Stop` (sync) | markdown memories are checkpointed asynchronously at session end |

Why hooks and not just good tool descriptions? We measured it: across 166 real sessions, hook-injected context was delivered in **100%** of them while voluntary memory-tool calls happened in **6%**. What a hook enforces happens.

The resume digest is deliberately bounded (~350 tokens measured on a 500-memory store): rules are clipped, the critical list is capped, and full text is one `get_memory` call away.

---

## Scale to 10,000+ sessions

After months of use, your checkpoint history grows. Squash compresses it, gc reclaims the disk:

```bash
memgit squash --keep-last 100    # keep last 100 checkpoints, squash everything older
memgit squash --older-than 30    # squash everything older than 30 days
memgit squash --dry-run          # preview first

memgit gc                        # delete unreachable objects, trim reflogs
memgit gc --dry-run              # preview
memgit gc --squash-keep 200      # compact history, then sweep
```

The current memory **state is always preserved** — and squash is lossless-in-substance: every collapsed checkpoint leaves a one-line record (time, author, diff, message) in an append-only archive under `.memgit/logs/archive/` that gc never touches. Benchmark on a 2,000-checkpoint store: **94% smaller** (39.5 MB → 2.2 MB), `fsck` clean. History operations stay O(1) as the chain grows (SHA resolution and checkpoint counting measured at ~0.08 ms at 2,000 checkpoints).

---

## Multiple agents, one memory

All writes go through a git-style store lock (0.08 ms overhead), so concurrent agents can't corrupt the store or lose each other's updates. Two patterns:

**Shared thread** — agents write concurrently; if one commits while another has work staged, the second commit auto-merges (three-way, against the recorded base) instead of clobbering. Set `MEMGIT_AUTHOR=agent-name` so each checkpoint says who did it.

**Thread per agent** — isolate, then integrate:

```bash
memgit thread create agent-1     # branch off for each agent
# ... agents work on their own threads ...
memgit merge agent-1             # three-way merge back (common-ancestor based)
```

Conflicts (same memory changed on both sides) resolve to the newest version; an edit always beats a delete. Both histories are preserved.

---

## What the AI sees

Once registered via MCP, every AI tool gets 6 tools:

| Tool | When the AI uses it |
|---|---|
| `resume_session` | When the request depends on prior state — "continue", "the pending tasks", session start |
| `search_memories` | Before answering anything that touches past work or preferences |
| `get_memory` | When it needs full details of a specific memory |
| `list_memories` | To browse or audit what's stored |
| `save_memory` | When it learns something worth keeping for next time |
| `get_checkpoint_log` | To check when memories were last synced |

The tool descriptions teach the AI **judgment** — "does this request depend on state you don't have in context?" — rather than keyword triggers. Measured cost of the whole tool surface: ~1,150 tokens once per session; a `resume_session` reply is ~335.

---

## Core operating guide (v0.5.0)

A project's hardest onboarding problem isn't *what* it does — it's *how to work in it*: which skill to invoke, which command to run, which tool to reach for. That lives in a `CLAUDE.md` or a skills folder the AI host may or may not be configured to read. memgit carries it for you.

`memgit core seed` distills a compact operating guide from the project's existing skills + rule files. `memgit core sync` writes it into **every AI host's own rules surface** as a dedicated, memgit-owned file — `.claude/rules/memgit.md`, `.cursor/rules/memgit.mdc`, `.windsurf/rules/memgit.md`, `.clinerules/`, `.roo/rules/`, `.continue/rules/` — and marker-delimited blocks in the shared `GEMINI.md` (Gemini CLI auto-loads only that file) and Codex's `AGENTS.md`. It's **additive only** — memgit never touches your own config or content — and injected at session start, so any tool knows how to work in the project even when its native setup is missing.

And it **learns**: a sidecar usage ledger tracks which memories actually get recalled, and the most-used ones are auto-promoted as pointers into the guide over time (budget-capped, decaying, and always subordinate to the repo's own rules — it never restates or overrides them). Drifted? `memgit core heal` rebuilds it.

---

## Depth advertisement, trackers & supersession (v0.6.0)

Measured across 289 real sessions: injected recall reached ~59% of them, but only **6.8%** ever ran an active search — the injected top-3 reads as "memory consulted", so the model never learns there's a queryable store behind it. 0.6.0 makes the passive layer advertise what the active layer knows:

- **Memory index** — the resume digest ends with tag→count pairs (`8a8f4ec (6) · instagram (5)`) and the exact call to go deeper. Counts are truthful: superseded memories are excluded, and every advertised topic is guaranteed to return search results.
- **"+N more" recall hints** — when the per-prompt recall block has more on-topic memories behind it, it says so, with the one call to get them.
- **Context-triggered recall** — a `PostToolUse` hook: reading a file whose path matches a memory tag surfaces `memgit: 6 memories tagged 'x' relate to this path`. Reads only a commit-time tagmap cache (never the store), capped 3/session.
- **Trackers (`tr`)** — one memory per in-flight entity (`<entity>-status`), updated by re-saving the same slug. They render as a **status board** at the top of every session: memgit is the authority for entity status; files may lag.
- **Supersession** — a correction names what it replaces (`supersedes=[old-slug]`) instead of a "CORRECTED:" prefix. Superseded memories vanish from search/recall/resume (history preserved; `list` still shows them marked ⊘), so injected context is never stale.

---

## Commands

```bash
# Core (git-like)
memgit init                       # initialize store (auto-detects best path)
memgit onboard                    # bootstrap brief for an existing codebase
memgit add <slug> <rule>          # stage a memory (--body detail, --project scope, --global everywhere, --supersedes old-slug)
memgit commit -m "message"        # checkpoint current state
memgit log                        # history
memgit diff [sha1] [sha2]         # what changed
memgit show <slug>                # display a memory
memgit remove <slug>              # remove from active index (history preserved)
memgit status                     # staged changes
memgit search <query>             # BM25 search, scoped to this project + global (--all-projects to widen)
memgit rollback <ref>             # restore state to a checkpoint (HEAD~N or SHA)
memgit resume                     # where we left off — session-start digest
memgit merge <thread>             # three-way merge a thread into the current one
memgit remove <slug>              # (aliases: delete, rm, del) — mistypes get a "did you mean?"

# Core operating guide — per-project, always-on, cross-host
memgit core seed                  # draft a guide from this project's skills + rule files
memgit core sync                  # deliver it into each AI host's own rules file (additive)
memgit core show / edit           # view / curate the guide
memgit core heal                  # self-repair a guide that has drifted

# Scale & proof
memgit squash                     # compress old history (archives what it collapses)
memgit gc                         # reclaim disk: sweep unreachable objects + stale session caches
memgit stats                      # measured context costs + disk usage
memgit doctor                     # hygiene report: quarantined/_unknown memories, stale caches, orphaned usage
memgit doctor --relabel map.json  # bulk re-project memories ({"slug": "Label" | ""}); one checkpoint
memgit lint                       # validate all memories (flags unknown provenance)
memgit fsck                       # verify store integrity

# Import / export
memgit sync                       # sync from Claude Code files + commit (auto-finds them)
memgit import claude-code [path]  # path optional — defaults to ~/.claude/projects/*/memory
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
memgit setup gemini-cli
memgit setup hooks                # Claude Code hooks: resume at start, per-prompt recall,
                                  # capture guard + auto-sync at stop (--no-recall / --no-guard)

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

## TOON format — compact, readable, diffable

Standard markdown memory file:
```markdown
## Rule: Never mock the database in tests
**Type:** feedback  
**Priority:** medium  
**Why:** We got burned last quarter — mocked tests passed but the prod migration failed.  
**When to apply:** Any time writing tests that touch persistence layers.  
**Tags:** testing, database
```

The same memory in TOON:
```
TOON1|fb|no-db-mock|2026-07-01T10:00Z
#testing #database
PROJ:my-app
RULE:Never mock the database in tests
WHY:Mocked tests passed but prod migration failed last quarter
WHEN:Any persistence test
BODY:Full long-form detail lives here, losslessly (newlines escaped).\nSearch returns the compact RULE; get_memory returns everything.
```

Measured with a real tokenizer, TOON is ~5–10% leaner than equivalent markdown — a nice bonus, not the headline. **The headline saving is retrieval**: memgit loads the top-8 relevant memories per query instead of everything.

At 108 memories: **12,840 tokens (dump everything) → 640 tokens (memgit BM25 top-8)**

For exact token counts in `memgit stats`, install the optional tokenizer: `pip install "memgit[tokens]"`.

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
pytest    # 245 tests, all passing, < 5 seconds
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Roadmap

- [x] Content-addressed object store (git-identical architecture)
- [x] TOON format (compact line-oriented memory format)
- [x] MCP server — Claude Code, Cursor, Windsurf, Cline, Continue.dev
- [x] HTTP server — ChatGPT Custom Actions, Gemini function calling
- [x] BM25 relevance search (load only what matters)
- [x] `memgit stats` — measured token savings proof
- [x] `memgit squash` — scale to 10k+ sessions
- [x] `memgit git push/pull` — team sync via standard git
- [x] Flat `memories/` directory — grep/diff/blame your memories
- [x] D3.js graph visualization of memory relationships
- [x] `memgit resume` + SessionStart hook — sessions start with "where we left off"
- [x] Guardrail hooks — per-prompt auto-recall + end-of-session capture guard (v0.4.0)
- [x] Core operating guide — per-project, always-on, cross-host, self-improving (v0.5.0)
- [x] `memgit gc` — space reclamation (mark-and-sweep, lossless squash archive)
- [x] Multi-agent write safety — store lock, auto-merge commits, `memgit merge`
- [x] PyPI + Homebrew (tap) + npm published (v0.1.5)
- [x] Chocolatey — live on community.chocolatey.org (`choco install memgit`)
- [x] Interactive setup wizard (`memgit setup`)
- [x] Smart `memgit init` (auto-detects tool, no path needed)
- [x] Lossless memories — full `body` alongside the compact rule (v0.3.0)
- [x] Project-scoped memories + `memgit onboard` mid-project bootstrap (v0.3.0)
- [x] VS Code extension (v0.1.5, Marketplace: code416-memgit.memgit)
- [ ] JetBrains plugin (Phase 3)
- [ ] Semantic search via embeddings (Phase 4)
- [x] memgit.dev website (live)
- [ ] Memory compression / auto-summarization (Phase 5)
- [ ] Team access control + audit trail (Phase 5)
- [ ] Memory marketplace — share reusable context packs (Phase 6)

---

## License

MIT — see [LICENSE](LICENSE).
