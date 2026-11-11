#!/usr/bin/env node
/**
 * memgit-mcp — npm wrapper for the memgit MCP server.
 * Usage: npx memgit-mcp [--store /path/to/store]
 *
 * Needs Python 3.11 or newer on PATH. On first run it installs memgit into an
 * isolated venv under ~/.memgit-npm-venv, keeps that install at this wrapper's
 * own version, and then runs `memgit serve` (stdio MCP transport).
 *
 * stdout belongs to the MCP protocol from the first byte. Everything this
 * wrapper or pip prints goes to stderr, or the host reads it as a broken
 * JSON-RPC message and drops the server.
 */

import { execFileSync, spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const WIN = process.platform === "win32";
const VENV = join(homedir(), ".memgit-npm-venv");
const PY = join(VENV, WIN ? "Scripts/python.exe" : "bin/python");
const MEMGIT = join(VENV, WIN ? "Scripts/memgit.exe" : "bin/memgit");
const TO_STDERR = ["ignore", 2, 2];
const WANT = JSON.parse(
  readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "package.json"), "utf8"),
).version;

const log = (msg) => process.stderr.write(`[memgit-mcp] ${msg}\n`);

function findPython() {
  for (const cmd of WIN ? ["py", "python", "python3"] : ["python3", "python"]) {
    try {
      const ver = execFileSync(cmd, ["--version"], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
      const m = ver.match(/Python (\d+)\.(\d+)/);
      if (m && (Number(m[1]) > 3 || (Number(m[1]) === 3 && Number(m[2]) >= 11))) return cmd;
    } catch {}
  }
  log("Python 3.11 or newer was not found on PATH. Install it from https://python.org/downloads and start again.");
  process.exit(1);
}

function installedVersion() {
  try {
    return execFileSync(PY, ["-c", "from importlib.metadata import version; print(version('memgit'))"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return null;
  }
}

function pip(spec) {
  execFileSync(PY, ["-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--upgrade", spec], {
    stdio: TO_STDERR,
  });
}

if (!existsSync(PY)) {
  log("first run: creating a private Python environment");
  execFileSync(findPython(), ["-m", "venv", VENV], { stdio: TO_STDERR });
}

const have = installedVersion();
if (have !== WANT) {
  log(have ? `updating memgit ${have} to ${WANT}` : `installing memgit ${WANT}`);
  try {
    pip(`memgit==${WANT}`);
  } catch {
    // The matching release may not be on PyPI yet, or the machine is offline.
    // Any working install beats refusing to start.
    if (!have) {
      try {
        pip("memgit");
      } catch {
        log("could not install memgit (see the pip output above)");
        process.exit(1);
      }
    } else {
      log(`keeping memgit ${have}`);
    }
  }
}

const child = spawn(MEMGIT, ["serve", ...process.argv.slice(2)], { stdio: "inherit" });
child.on("exit", (code) => process.exit(code ?? 0));
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => child.kill(sig));
