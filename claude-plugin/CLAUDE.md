# memgit — AI memory plugin for Claude Code

This plugin provides persistent, version-controlled memory across AI sessions.

## What memgit does

memgit stores facts, rules, preferences, and lessons from your sessions in a version-controlled store. At the start of each session, relevant memories are retrieved automatically. When you learn something worth keeping, it gets saved for next time.

## Tools available (via MCP)

- **resume_session** — the "where we left off" digest: last checkpoints, work in flight, critical rules
- **search_memories** — ranked recall of facts/rules/preferences relevant to a topic
- **save_memory** — call this when the user states a preference or you learn something durable
- **get_memory** — fetch full details of a specific memory by slug
- **list_memories** — browse all stored memories
- **get_checkpoint_log** — check sync history

## When to use each tool

Use judgment, not keyword matching. The test is: **does this request depend on state you don't have in context?**

- A request that presupposes shared history — "continue", "the pending tasks", "that bug from before", resuming after a break — cannot be answered from the conversation or open files alone. **resume_session** is the authoritative record of what was actually done last; an open file only shows what the user is looking at.
- Questions that touch past work, prior decisions, or user preferences → **search_memories** before answering. Checking is cheap; guessing wrong is not.
- **Call save_memory** whenever the user corrects you, states a preference, makes a decision, or you learn something that should persist beyond this session — don't wait to be asked.
- **Never re-read markdown memory files** if memgit is available — use search_memories instead (faster, ranked).
- Skip memory calls only when the request is clearly self-contained.

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
