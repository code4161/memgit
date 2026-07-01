# memgit — Quick Start

## Run it (until alias is set up)

```bash
/Users/hari/Personal\ business/memgit/.venv/bin/memgit --help
```

## Add to shell (run once manually)

```bash
echo 'alias memgit="/Users/hari/Personal\ business/memgit/.venv/bin/memgit"' >> ~/.zshrc
source ~/.zshrc
```

## Your Claude Code memory store

Location: `~/.claude/memgit-store/`

```bash
cd ~/.claude/memgit-store

# See current state
memgit status

# See history
memgit log --oneline

# See all memories
memgit list

# Show a specific memory (by slug)
memgit show ig-creative-rules

# Show in TOON format (token-efficient)
memgit show ig-creative-rules --toon

# Add a new memory
memgit add my-new-rule "always do X" --type fb --why "because Y" --when "when doing Z"

# Checkpoint after adding
memgit commit -m "added new rule"

# See what changed since last checkpoint
memgit diff --full

# Import latest Claude Code files (after manual edits to markdown)
memgit import claude-code

# Re-sync: import from the specific project memory dir
memgit import claude-code ~/.claude/projects/-Users-hari-Personal-business/memory/
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

## Session 2 (next)

Build the MCP server so Claude Code reads memories directly from memgit instead of markdown files.
