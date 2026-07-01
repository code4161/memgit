# memgit — Quick Start

## Install & initialize

```bash
pip install memgit
memgit init          # auto-detects the best store location (e.g. ~/.claude/memgit-store)
memgit setup         # register with your AI tools (interactive picker)
```

## Everyday commands

```bash
# Where did we leave off? (last checkpoints, work in flight, critical rules)
memgit resume

# Auto-inject that digest into every new Claude Code session
memgit setup hooks

# See current state
memgit status

# See history
memgit log --oneline

# See all memories
memgit list

# Show a specific memory (by slug)
memgit show my-rule

# Show in TOON format (compact storage format)
memgit show my-rule --toon

# Add a new memory
memgit add my-new-rule "always do X" --type fb --why "because Y" --when "when doing Z"

# Checkpoint after adding
memgit commit -m "added new rule"

# See what changed since last checkpoint
memgit diff --full

# Search by relevance (BM25)
memgit search "auth pattern"

# Undo a bad change — restore an earlier checkpoint
memgit rollback HEAD~1 --dry-run   # preview
memgit rollback HEAD~1             # apply (history is preserved)

# Import existing Claude Code memory files
memgit import claude-code ~/.claude/projects/

# Multi-agent: merge another thread's memories into the current one
memgit merge agent-1

# Maintenance: compress old history, then reclaim disk
memgit squash --keep-last 100
memgit gc
```

## Memory types

| Code | Meaning        |
|------|---------------|
| `fb` | feedback      |
| `us` | user profile  |
| `pj` | project       |
| `rf` | reference     |
| `cn` | convention    |
| `lx` | lesson        |

## Priority

- `1` = low (background context)
- `2` = medium (default)
- `3` = critical (must always load)

## More

- Full install & AI-tool registration guide: [INSTALL.md](INSTALL.md)
- All commands: `memgit --help`
- Docs: https://memgit.dev/docs
