# memgit — install & setup guide

**Git for AI memory.** memgit gives your AI assistants persistent, version-controlled memory that follows you across tools — switch from Claude to GPT to Cursor mid-project and your context is already there.

---

## Install

```bash
pip install memgit
```

Or from source (this repo):

```bash
cd /path/to/memgit
pip install -e .
```

Verify:

```bash
memgit --version
```

---

## Initialize your memory store

```bash
memgit init ~/.claude/memgit-store
cd ~/.claude/memgit-store
memgit sync                      # import your existing Claude Code memories
```

---

## Register with your AI tools

### One command — registers everywhere

```bash
memgit setup all
```

This auto-detects which AI tools are installed on your machine and registers memgit with each one. Safe to re-run — skips tools that aren't installed, never overwrites other settings.

### Register with individual tools

| Tool | Command |
|---|---|
| Claude Code | `memgit setup claude-code` |
| Claude Desktop | `memgit setup claude-desktop` |
| Cursor | `memgit setup cursor` |
| Windsurf | `memgit setup windsurf` |
| Cline / Roo-Code (VS Code) | `memgit setup cline` |
| Continue.dev | `memgit setup continue` |

### Can't run setup? Copy-paste the config

```bash
memgit setup print-config cursor      # prints the JSON to paste
memgit setup print-config claude-code
memgit setup print-config continue
```

After registering, **restart the AI tool** for it to pick up the new MCP server.

---

## Using with GPT (ChatGPT Custom Actions) or Gemini

MCP tools (Claude, Cursor, etc.) connect automatically after `setup`. GPT and Gemini use a different mechanism — they call memgit over HTTP.

**Step 1 — Start the HTTP server:**

```bash
memgit serve --http --port 7474
```

Keep this running in a terminal while you're using GPT or Gemini.

**Step 2 — Register in ChatGPT:**
1. Go to ChatGPT → My GPTs → Create a GPT
2. Add Action → Import from URL: `http://localhost:7474/openapi.json`
3. Save. ChatGPT can now call `search_memories`, `save_memory`, etc.

**Step 3 — Register in Gemini (API / Vertex AI):**
Use the tool definitions from [llm-tool-definitions.json](llm-tool-definitions.json):

```python
import json
defs = json.load(open("llm-tool-definitions.json"))
# Pass defs["tools"] as function declarations to the Gemini API
# Point each tool's endpoint to http://localhost:7474
```

> **Note:** The HTTP server binds to `127.0.0.1` only (localhost). For remote LLM APIs, you'll need a tunnel (e.g. `ngrok http 7474`) or a cloud deployment.

---

## What each tool sees

When any AI tool calls memgit, it gets access to 5 tools:

| Tool | When the AI calls it |
|---|---|
| `search_memories` | Session start, or before answering about past work |
| `get_memory` | To fetch full details of a specific memory |
| `list_memories` | To browse all stored memories |
| `save_memory` | When it learns something worth keeping for next time |
| `get_checkpoint_log` | To check when memories were last synced |

---

## Cross-AI workflow (the core use case)

```
Morning: working with Claude Code on a feature
  → Claude calls search_memories, gets your project rules
  → Claude calls save_memory when it learns your new naming convention

Afternoon: switch to Cursor for refactoring
  → Cursor's memgit sees the same store
  → The naming convention Claude saved is already there

Evening: ask ChatGPT for architecture advice
  → Start memgit serve --http
  → ChatGPT's Custom Action calls search_memories
  → Same context, no re-explaining
```

---

## Config file locations (for manual setup)

If `memgit setup` fails, manually add this to each tool's config file:

```json
{
  "mcpServers": {
    "memgit": {
      "command": "memgit",
      "args": ["serve"]
    }
  }
}
```

| Tool | Config file |
|---|---|
| Claude Code | `~/.claude/settings.json` |
| Claude Desktop (Mac) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Claude Desktop (Linux) | `~/.config/Claude/claude_desktop_config.json` |
| Cursor | `~/.cursor/mcp.json` |
| Windsurf | `~/.windsurf/mcp.json` |
| Cline | `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json` |
| Roo-Code | `~/Library/Application Support/Code/User/globalStorage/rooveterinaryinc.roo-cline/settings/cline_mcp_settings.json` |
| Continue.dev | `~/.continue/config.json` (uses list format — use `memgit setup continue`) |

---

## Auto-sync on session end

memgit can sync your memories automatically when a Claude Code session ends:

```bash
# Add to ~/.claude/settings.json hooks:
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

Or use `memgit setup claude-code` — it sets this up automatically.

---

## Memory store location

By default: `~/.claude/memgit-store/`

To use a different store with any command:

```bash
memgit --store /path/to/store status
memgit serve --store /path/to/store
```

---

## Troubleshooting

**MCP server doesn't appear in the tool list:**
- Did you restart the AI tool after setup?
- Check `memgit serve` works: run it manually and look for errors.
- Try `memgit setup print-config <tool>` and verify the path is correct.

**`memgit: command not found`:**
- `pip install memgit` was run inside a venv — either activate the venv or install globally.
- Run `which memgit` to find the path, then use that full path in the config.

**Store not found error:**
- Run `memgit init ~/.claude/memgit-store` first.
- If using a custom store, pass `--store /path/to/store` to `memgit serve`.
