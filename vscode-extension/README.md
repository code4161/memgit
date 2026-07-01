# memgit for VS Code

Version-controlled AI memory for Claude Code, Cursor, Windsurf, and Copilot Chat.

## Prerequisites

Install memgit and start the daemon:

```bash
pip install memgit
memgit init
memgit daemon start
```

The extension connects to the daemon at `localhost:7474`.

## Features

- **Memory Explorer** — sidebar tree showing your memories grouped by priority
- **History** — checkpoint log with timestamps and diff counts
- **Search** — fuzzy keyword search over all memories (`Cmd+Shift+P` → `memgit: Search`)
- **Save** — write a new memory from any editor (`Cmd+Shift+P` → `memgit: Save Memory`)
- **Cursor/Windsurf injection** — auto-injects your top memories into `.cursorrules` / `.windsurfrules`
- **Copilot/Cursor AI tools** — registers `memgit_write`, `memgit_query`, `memgit_forget` as LM tools

## Getting started

1. Install the extension from the VS Code Marketplace
2. `pip install memgit && memgit init`
3. `memgit daemon start` (runs in a terminal)
4. Open a project — the AI Memory sidebar appears

## Configuration

| Setting | Default | Description |
|---|---|---|
| `memgit.daemonPort` | `7474` | Port the daemon runs on |
| `memgit.autoRefreshInterval` | `30` | Refresh interval in seconds (0 = off) |
| `memgit.injectOnStart` | `true` | Auto-inject into `.cursorrules` / `.windsurfrules` |
