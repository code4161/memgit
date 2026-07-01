# memgit — AI memory plugin for Claude Code

This plugin provides persistent, version-controlled memory across AI sessions.

## What memgit does

memgit stores facts, rules, preferences, and lessons from your sessions in a version-controlled store. At the start of each session, relevant memories are retrieved automatically. When you learn something worth keeping, it gets saved for next time.

## Tools available (via MCP)

- **search_memories** — call this at session start to retrieve relevant context
- **save_memory** — call this when the user states a preference or you learn something durable
- **get_memory** — fetch full details of a specific memory by slug
- **list_memories** — browse all stored memories
- **get_checkpoint_log** — check sync history

## When to use each tool

- **Always call search_memories** at the start of a session before answering questions about past work or applying preferences
- **Call save_memory** whenever the user corrects you, states a preference, makes a decision, or you learn something that should persist beyond this session
- **Never re-read markdown memory files** if memgit is available — use search_memories instead (faster, ranked)

## Memory types

| Code | Use for |
|---|---|
| `fb` | User corrections, preferences, how they like to work |
| `us` | Who the user is — role, expertise, goals |
| `pj` | Active projects, decisions, deadlines |
| `rf` | Links to external systems, docs, tools |
| `cn` | Code conventions, architecture rules |
| `lx` | Lessons learned, post-mortems |

## Priority

- `1` = background context (loaded when relevant)
- `2` = medium (default — loaded when relevant)  
- `3` = critical (loaded in every session, always)
