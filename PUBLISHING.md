# memgit — Distribution Action Plan

**Goal:** `pip install memgit` / `brew install memgit` / `choco install memgit` / `npx memgit-mcp` all work globally.

---

## Priority order

| # | Channel | Audience | Status |
|---|---|---|---|
| 1 | **GitHub repo** | Foundation | ✅ code4161/memgit — live |
| 2 | **PyPI** | All Python devs | ✅ v0.1.2 — `pip install memgit` |
| 3 | **Homebrew tap** | Mac + Linux devs | ✅ `brew tap code4161/tap && brew install memgit` |
| 4 | **Claude Code plugin** | Claude Code users | ✅ code4161/claude-plugins — live |
| 5 | **npm wrapper** | MCP/Node ecosystem | ✅ v0.1.2 live — `npx memgit-mcp` |
| 6 | **Chocolatey** | Windows devs | ✅ workflow ready — pending 1–3 day moderation |
| 7 | **winget** | Windows (Microsoft) | ⬜ later (after Chocolatey is approved) |
| 8 | **Homebrew core** | Wide Mac audience | ⬜ later (after 100+ stars) |

---

## Step 1 — GitHub repo ✅ DONE

Repo live: https://github.com/code4161/memgit (public)
Topics set: ai, mcp, memory, claude, cursor, llm, context, version-control
Logo: `assets/logo.png` committed and shown in README.
Latest commit: v0.1.1 (48 tests passing).

---

## Step 2 — PyPI (pip install memgit) ✅ DONE

**Published:** v0.1.1 live at https://pypi.org/project/memgit/

**How it was set up:**
- PyPI account created as `memgit`
- API token stored as GitHub Actions secret `PYPI_TOKEN` (via `gh secret set`)
- `.github/workflows/publish.yml` — triggers on `v*.*.*` tags, builds with `python -m build`, publishes via `twine upload` using `__token__` auth

**To publish future versions:**
```bash
# 1. Bump version in pyproject.toml
# 2. Commit, then tag and push:
git tag v0.1.2
git push origin v0.1.2
# GitHub Actions fires automatically and publishes to PyPI
```

**Verify:**
```bash
pip install memgit
memgit --version
```

---

## Step 3 — Homebrew tap ✅ DONE

Tap live: https://github.com/code4161/homebrew-tap

**Users install with:**
```bash
brew tap code4161/tap
brew install memgit
```

Formula at `Formula/memgit.rb` — uses PyPI tarball (v0.1.2 sha256 pinned).
To update for a new version: update `url` + `sha256` in `Formula/memgit.rb` and push to `homebrew-tap`.

---

## Step 4 — Claude Code plugin ✅ DONE

Repo live: https://github.com/code4161/claude-plugins

**Users install with:**
```
/plugin marketplace add code4161/claude-plugins
/plugin install memgit@code4161
```

To update: bump `version` in `claude-plugins/marketplace.json` and push.

---

## Step 5 — npm wrapper ✅ WORKFLOW READY — needs Automation token

Workflow at `.github/workflows/npm-publish.yml` fires on every `v*.*.*` tag.

Published v0.1.2. Automation token set as `NPM_TOKEN` secret — future `v*.*.*` tag pushes publish automatically.

**Users can then add to any AI tool config:**
```json
{
  "mcpServers": {
    "memgit": {
      "command": "npx",
      "args": ["-y", "memgit-mcp"]
    }
  }
}
```

---

## Step 6 — Chocolatey ✅ WORKFLOW READY — pending moderation

Workflow at `.github/workflows/choco-publish.yml` fires on every `v*.*.*` tag.
`CHOCOLATEY_API_KEY` is already set as a GitHub Actions secret.

The package was submitted on the next `v*.*.*` tag push. Moderation takes 1–3 days.

**After approval:**
```powershell
choco install memgit
```

---

## Step 7 — winget (winget install memgit) [later]

winget requires a standalone executable (not a pip wrapper). Do this after Chocolatey is live.

**Build a Windows executable first:**
```bash
pip install pyinstaller
pyinstaller --onefile --name memgit memgit/cli.py
# Produces dist/memgit.exe
```

Upload `memgit.exe` to GitHub Releases as `memgit-0.1.0-windows-x64.exe`.

Then:
1. Fork [github.com/microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs)
2. Copy `winget/manifests/` from this repo into the forked repo
3. Fill in the real SHA256 of the exe:
   ```powershell
   Get-FileHash memgit-0.1.0-windows-x64.exe -Algorithm SHA256
   ```
4. Submit PR to `microsoft/winget-pkgs`
5. Wait 1–2 weeks for automated validation + approval

---

## Step 8 — Homebrew core [later, after adoption]

Requirements before submitting:
- The GitHub repo must have **stable tags** (not just `main`)
- **100+ GitHub stars** (unwritten but practical threshold)
- Formula must build cleanly on macOS 13/14/15 (Intel + Apple Silicon) AND Linux x86_64
- No proprietary dependencies

When ready:
```bash
brew tap --repair homebrew/core
brew create --python https://files.pythonhosted.org/packages/source/m/memgit/memgit-0.1.0.tar.gz
# Edit the formula, then:
brew audit --strict --online memgit
brew test memgit
# Submit PR to homebrew/homebrew-core
```

---

## Website checklist (next phase)

The website at `memgit.dev` should cover:

- **Hero:** "Your memory. Every AI." — one-liner install per platform
- **Install tabs:** pip / brew / choco / npx — each with one command
- **AI tools grid:** Claude Code · Claude Desktop · Cursor · Windsurf · Cline · Continue.dev · ChatGPT · Gemini
- **The switching story:** animated diagram showing memory following the user across tools
- **Cross-AI workflow example:** real scenario (Claude in morning → Cursor afternoon → ChatGPT evening)
- **`memgit setup all` demo:** short terminal recording showing auto-detection + registration
- **Docs:** link to INSTALL.md / per-tool setup guides / TOON format reference
- **Open source badge + star count** from GitHub

---

## Quick reference: what users run after everything is live

| Platform | Install | After install |
|---|---|---|
| Mac | `brew tap code4161/tap && brew install memgit` | `memgit setup all` |
| Mac/Linux | `pip install memgit` | `memgit setup all` |
| Windows | `choco install memgit` | `memgit setup all` |
| Windows | `winget install code4161.memgit` | `memgit setup all` |
| Any (npx) | `npx memgit-mcp` in AI tool config | nothing |
| Claude Code | `/plugin marketplace add code4161/claude-plugins` then `/plugin install memgit@code4161` | nothing |

---

## Files in this repo that support distribution

| File | Purpose |
|---|---|
| `LICENSE` | Required by all registries |
| `pyproject.toml` | PyPI metadata + entry point |
| `.github/workflows/publish.yml` | Auto-publish to PyPI on git tag |
| `Formula/memgit.rb` | Homebrew formula (fill sha256 after PyPI publish) |
| `chocolatey/memgit.nuspec` | Chocolatey package metadata |
| `chocolatey/tools/chocolateyInstall.ps1` | Chocolatey install script |
| `npm-wrapper/` | npm package for `npx memgit-mcp` |
| `claude-plugin/` | Claude Code plugin files |
| `winget/manifests/` | winget package manifest (needs exe after pyinstaller) |
| `openapi.json` | OpenAPI spec for GPT Custom Actions |
| `llm-tool-definitions.json` | Tool definitions for GPT/Gemini function calling |
| `INSTALL.md` | End-user install guide (also PyPI readme) |
