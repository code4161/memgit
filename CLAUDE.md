# memgit core — operating guide

Git for AI memory: Python CLI + MCP server + hooks + VS Code extension
(repo `code4161/memgit`, public). The live store on this machine is
`~/.claude/memgit-store/`; the installed tool runs from the system Python 3.13
site-packages — **this checkout is not the live tool**.

## Rules

- **Release via the `memgit-maintenance` skill** — tag push auto-publishes PyPI/npm/choco;
  brew tap, `vsce publish` and the Claude plugin are manual, and README/docs must move in
  the same release. The 2026-08-05 audit traced nearly every live defect to ONE unreleased
  commit: a merged feature is dead until released and installed.
- **Autonomy is a design constraint** (`memgit-autonomous-durability`): a maintenance task
  requiring a human command will never happen. Backup is automatic end-of-session; memgit
  never invents a git remote.
- **MCP registry search matches NAME ONLY** (`mcp-registry-search-is-name-only…`) — naming
  decisions are distribution decisions and effectively permanent.
- Dogfooding findings become memories (project `Personal-business`) AND GitHub issues —
  the store this tool manages is also its best test fixture.
- Pricing/billing decisions: `memgit-cloud-billing-august-cash` + MEMGIT_NEXT_STEPS
  gates. No money on memgit-cloud until the free test converts.

Doc: [MEMGIT_NEXT_STEPS.md](MEMGIT_NEXT_STEPS.md). Group map: [../CLAUDE.md](../CLAUDE.md).

## 🔴 CORE RULE — no conflicting or stale memory (workspace-wide, 2026-08-31)

`save_memory` is not append-only in effect: a stale memory competes with its own
correction and can OUTRANK it in search. Before every save — `search_memories` on the
QUANTITY, and if an existing memory states a different value, **re-save that one or pass
`supersedes`**. Correct the `rule` line, not just the body (search and digests render the
rule). If a correction inverts a finding, the **slug** changes too. `lx` lessons carry no
operational directives ("do not arm") — those expire with state, and state lives in the
`tr` tracker. `save_memory` on an existing slug REPLACES: always resend the full body.
Close the loop — re-search what you wrote and read the top hit.

Full doctrine: [root CLAUDE.md §1a](../../CLAUDE.md).
