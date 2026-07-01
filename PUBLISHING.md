# memgit — Distribution Action Plan

**Goal:** `pip install memgit` / `brew install memgit` / `choco install memgit` / `npx memgit-mcp` all work globally.

---

## Priority order

| # | Channel | Audience | Effort | Status |
|---|---|---|---|---|
| 1 | **GitHub repo** | Foundation for everything | 10 min | ✅ code4161/memgit — live |
| 2 | **PyPI** | All Python devs, Linux/Mac/Win | 20 min | ✅ v0.1.1 published — `pip install memgit` works |
| 3 | **Homebrew tap** | Mac + Linux devs | 15 min | ⬜ you do this |
| 4 | **Claude Code plugin** | Claude Code users | 10 min | ⬜ you do this |
| 5 | **npm wrapper** | MCP/Cursor/Node ecosystem | 10 min | ⬜ you do this |
| 6 | **Chocolatey** | Windows developers | 30 min | ⬜ you do this |
| 7 | **winget** | Windows via Microsoft | 1–2 weeks approval | ⬜ later |
| 8 | **Homebrew core** | Wide Mac audience | Wait for adoption | ⬜ later (after 100+ stars) |

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

## Step 3 — Homebrew tap (brew install memgit)

**Create the tap repo:**
1. Go to [github.com/new](https://github.com/new)
2. Name: **`homebrew-tap`** (must be this exact name) · Public
3. On your machine:
   ```bash
   mkdir ~/homebrew-tap
   cd ~/homebrew-tap
   git init
   mkdir Formula
   ```

**Generate the formula with correct sha256s** (after PyPI publish):
```bash
# Install homebrew-pypi-poet (generates resource stanzas from PyPI)
pip install homebrew-pypi-poet

# Generate resource blocks for all dependencies
poet memgit > /tmp/resources.txt
cat /tmp/resources.txt
```

4. Copy `Formula/memgit.rb` from this repo into `~/homebrew-tap/Formula/memgit.rb`
5. Replace `REPLACE_WITH_ACTUAL_SHA256_AFTER_TAGGING` with the real sha256:
   ```bash
   curl -sL https://github.com/code4161/memgit/archive/refs/tags/v0.1.0.tar.gz | shasum -a 256
   ```
6. Fill in the resource stanzas from `poet` output
7. Push:
   ```bash
   git add . && git commit -m "add memgit formula" && git push -u origin main
   ```

**Users install with:**
```bash
brew tap code4161/tap
brew install memgit
```

**Test your formula locally first:**
```bash
brew install --build-from-source ~/homebrew-tap/Formula/memgit.rb
brew test memgit
```

---

## Step 4 — Claude Code plugin

This makes memgit discoverable and installable from within Claude Code via `/plugin install memgit@code4161`.

**Create the marketplace repo:**
1. Go to [github.com/new](https://github.com/new)
2. Name: `claude-plugins` · Public

3. Structure:
   ```
   claude-plugins/
     marketplace.json          ← defines available plugins
     plugins/
       memgit/
         CLAUDE.md             ← already in claude-plugin/CLAUDE.md
         .mcp.json             ← already in claude-plugin/.mcp.json
         README.md
   ```

4. `marketplace.json`:
   ```json
   {
     "plugins": [
       {
         "name": "memgit",
         "description": "Git for AI memory — persistent context across Claude, GPT, Cursor and more",
         "version": "0.1.0",
         "path": "plugins/memgit",
         "tags": ["memory", "mcp", "context", "productivity"]
       }
     ]
   }
   ```

5. Copy `claude-plugin/` contents → `plugins/memgit/` in the new repo
6. Push

**Users install with:**
```
/plugin marketplace add code4161/claude-plugins
/plugin install memgit@code4161
```

**Note:** For the official Anthropic marketplace, submit a PR to `anthropics/claude-plugins-community` later (after v1.0 + some adoption). The personal marketplace works immediately.

---

## Step 5 — npm wrapper (npx memgit-mcp)

This lets MCP-aware tools install memgit without knowing about Python at all.

**One-time npm account:**
1. Create account at [npmjs.com/signup](https://www.npmjs.com/signup)
2. Enable 2FA

**Publish:**
```bash
cd "/Users/hari/Personal business/memgit/npm-wrapper"
npm login
npm publish --access public
```

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

Or run directly: `npx memgit-mcp`

**On first run**, npx installs the wrapper, which then auto-installs memgit into `~/.memgit-npm-venv` via pip.

---

## Step 6 — Chocolatey (choco install memgit)

**One-time account:**
1. Create account at [community.chocolatey.org](https://community.chocolatey.org/account/register)
2. Get your API key: Profile → API Keys → Copy

**Build and submit:**
```powershell
# Install Chocolatey tooling (on Windows)
choco install chocolatey-core.extension

# From the repo on Windows:
cd chocolatey
choco pack memgit.nuspec

# Push (replace YOUR_KEY with your API key)
choco push memgit.0.1.0.nupkg --source https://push.chocolatey.org --api-key YOUR_KEY
```

**Moderation:** Takes 1–3 days. You'll get an email when it's approved.

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
