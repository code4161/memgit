#!/usr/bin/env node
/**
 * memgit-mcp — npm wrapper for the memgit MCP server.
 * Usage: npx memgit-mcp [--store /path/to/store]
 *
 * On first run, installs memgit into an isolated venv under ~/.memgit-npm-venv
 * and then runs `memgit serve` (stdio MCP transport).
 */

import { execFileSync, spawn } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const VENV = join(homedir(), ".memgit-npm-venv");
const PIP = join(VENV, process.platform === "win32" ? "Scripts/pip" : "bin/pip");
const MEMGIT = join(VENV, process.platform === "win32" ? "Scripts/memgit" : "bin/memgit");

function findPython() {
  for (const cmd of ["python3", "python"]) {
    try {
      const ver = execFileSync(cmd, ["--version"], { encoding: "utf8" }).trim();
      const match = ver.match(/Python (\d+)\.(\d+)/);
      if (match && (parseInt(match[1]) > 3 || (parseInt(match[1]) === 3 && parseInt(match[2]) >= 11))) {
        return cmd;
      }
    } catch {}
  }
  throw new Error("Python 3.11+ not found. Install from https://python.org/downloads");
}

if (!existsSync(MEMGIT)) {
  process.stderr.write("[memgit-mcp] First run: installing memgit...\n");
  const python = findPython();
  if (!existsSync(VENV)) {
    execFileSync(python, ["-m", "venv", VENV], { stdio: "inherit" });
  }
  execFileSync(PIP, ["install", "--upgrade", "memgit"], { stdio: "inherit" });
  process.stderr.write("[memgit-mcp] memgit installed.\n");
}

// Pass all CLI args through to memgit serve
const args = ["serve", ...process.argv.slice(2)];
const child = spawn(MEMGIT, args, { stdio: "inherit" });
child.on("exit", (code) => process.exit(code ?? 0));
