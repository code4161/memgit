import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";
import { MemgitDaemonClient, Memory } from "./daemonClient";
import {
  MemoryTreeProvider,
  MemoryItem,
  CheckpointTreeProvider,
} from "./memoryTreeProvider";

let statusBarItem: vscode.StatusBarItem;
let refreshTimer: ReturnType<typeof setInterval> | undefined;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  const config = vscode.workspace.getConfiguration("memgit");
  const port: number = config.get("daemonPort", 7474);
  const client = new MemgitDaemonClient(port);

  // ── Tree providers ──────────────────────────────────────────────────────────
  const memoryProvider = new MemoryTreeProvider(client);
  const historyProvider = new CheckpointTreeProvider(client);

  vscode.window.registerTreeDataProvider("memgitExplorer", memoryProvider);
  vscode.window.registerTreeDataProvider("memgitLog", historyProvider);

  // ── Status bar ──────────────────────────────────────────────────────────────
  statusBarItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100
  );
  statusBarItem.command = "memgit.searchMemory";
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);

  // ── Commands ────────────────────────────────────────────────────────────────

  context.subscriptions.push(
    vscode.commands.registerCommand("memgit.refresh", async () => {
      await loadAll(client, memoryProvider, historyProvider, statusBarItem);
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("memgit.showLog", async () => {
      await historyProvider.load();
      await vscode.commands.executeCommand("memgitLog.focus");
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("memgit.searchMemory", async () => {
      const query = await vscode.window.showInputBox({
        prompt: "Search memories",
        placeHolder: "e.g. auth pattern, trading rules, ig pipeline",
      });
      if (!query) return;

      let results: Memory[];
      try {
        results = await client.searchMemories(query);
      } catch {
        vscode.window.showErrorMessage("memgit: daemon not reachable. Run `memgit serve --http`");
        return;
      }

      if (!results.length) {
        vscode.window.showInformationMessage(`No memories found for: ${query}`);
        return;
      }

      const picks = results.map((m) => ({
        label: m.slug,
        description: `[${m.type}] p${m.priority}`,
        detail: m.rule,
        memory: m,
      }));

      const picked = await vscode.window.showQuickPick(picks, {
        matchOnDescription: true,
        matchOnDetail: true,
        placeHolder: `${results.length} results for "${query}"`,
      });

      if (picked) showMemoryDocument(picked.memory, context);
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("memgit.saveMemory", async () => {
      const slug = await vscode.window.showInputBox({
        prompt: "Memory slug (kebab-case identifier)",
        placeHolder: "e.g. auth-pattern",
        validateInput: (v) =>
          /^[a-z0-9][a-z0-9-]*$/.test(v) ? undefined : "Use lowercase letters, numbers, hyphens",
      });
      if (!slug) return;

      const rule = await vscode.window.showInputBox({
        prompt: "Memory rule / content",
        placeHolder: "The concise fact or rule to remember",
      });
      if (!rule) return;

      const priorityPick = await vscode.window.showQuickPick(
        [
          { label: "2 — Normal", value: 2, description: "Injected when relevant" },
          { label: "3 — Critical", value: 3, description: "Always injected" },
          { label: "1 — Low", value: 1, description: "Only on explicit search" },
        ],
        { placeHolder: "Select priority" }
      );
      if (!priorityPick) return;

      try {
        await client.saveMemory(slug, rule, priorityPick.value);
        vscode.window.showInformationMessage(`memgit: saved "${slug}"`);
        await loadAll(client, memoryProvider, historyProvider, statusBarItem);
      } catch {
        vscode.window.showErrorMessage("memgit: failed to save — is the daemon running?");
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("memgit.viewMemory", async (item: MemoryItem) => {
      if (item?.memory) showMemoryDocument(item.memory, context);
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("memgit.deleteMemory", async (item: MemoryItem) => {
      if (!item?.memory) return;
      const confirm = await vscode.window.showWarningMessage(
        `Forget memory "${item.memory.slug}"?`,
        { modal: true },
        "Forget"
      );
      if (confirm !== "Forget") return;
      try {
        // Mark as superseded by saving with priority 0 convention; daemon will handle
        await client.saveMemory(item.memory.slug, `[superseded] ${item.memory.rule}`, 0);
        vscode.window.showInformationMessage(`memgit: forgot "${item.memory.slug}"`);
        await loadAll(client, memoryProvider, historyProvider, statusBarItem);
      } catch {
        vscode.window.showErrorMessage("memgit: failed to forget — is the daemon running?");
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("memgit.injectToCursorRules", async () => {
      const folder = vscode.workspace.workspaceFolders?.[0];
      if (!folder) {
        vscode.window.showWarningMessage("memgit: no workspace folder open");
        return;
      }
      try {
        await injectToCursorRules(folder.uri.fsPath, client);
        vscode.window.showInformationMessage("memgit: injected into .cursorrules");
      } catch (err) {
        vscode.window.showErrorMessage(`memgit: inject failed — ${err}`);
      }
    })
  );

  // ── Language Model Tools (Copilot / Cursor AI) ──────────────────────────────
  if ("lm" in vscode && typeof (vscode as any).lm?.registerTool === "function") {
    const lm = (vscode as any).lm;

    context.subscriptions.push(
      lm.registerTool("memgit_write", {
        invoke: async (request: any) => {
          const { slug, rule, priority = 2 } = request.input as {
            slug: string;
            rule: string;
            priority?: number;
          };
          await client.saveMemory(slug, rule, priority);
          await loadAll(client, memoryProvider, historyProvider, statusBarItem);
          return new (vscode as any).LanguageModelToolResult([
            new (vscode as any).LanguageModelTextPart(`Memory saved: ${slug}`),
          ]);
        },
      })
    );

    context.subscriptions.push(
      lm.registerTool("memgit_query", {
        invoke: async (request: any) => {
          const { query, limit = 5 } = request.input as {
            query: string;
            limit?: number;
          };
          const results = await client.searchMemories(query, limit);
          const text = results
            .map((m) => `[${m.slug}] ${m.rule}`)
            .join("\n") || "No memories found.";
          return new (vscode as any).LanguageModelToolResult([
            new (vscode as any).LanguageModelTextPart(text),
          ]);
        },
      })
    );

    context.subscriptions.push(
      lm.registerTool("memgit_forget", {
        invoke: async (request: any) => {
          const { slug } = request.input as { slug: string };
          const existing = await client.getMemory(slug);
          if (!existing) {
            return new (vscode as any).LanguageModelToolResult([
              new (vscode as any).LanguageModelTextPart(`Memory not found: ${slug}`),
            ]);
          }
          await client.saveMemory(slug, `[superseded] ${existing.rule}`, 0);
          await loadAll(client, memoryProvider, historyProvider, statusBarItem);
          return new (vscode as any).LanguageModelToolResult([
            new (vscode as any).LanguageModelTextPart(`Memory forgotten: ${slug}`),
          ]);
        },
      })
    );
  }

  // ── Auto-inject on startup ──────────────────────────────────────────────────
  const injectOnStart: boolean = config.get("injectOnStart", true);
  if (injectOnStart) {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (folder) {
      try {
        await injectToCursorRules(folder.uri.fsPath, client);
      } catch {
        // daemon may not be running yet — silent fail
      }
    }
  }

  // ── Initial load ────────────────────────────────────────────────────────────
  await loadAll(client, memoryProvider, historyProvider, statusBarItem);

  // ── Auto-refresh ────────────────────────────────────────────────────────────
  const intervalSec: number = config.get("autoRefreshInterval", 30);
  if (intervalSec > 0) {
    refreshTimer = setInterval(async () => {
      await loadAll(client, memoryProvider, historyProvider, statusBarItem);
    }, intervalSec * 1000);
    context.subscriptions.push({ dispose: () => clearInterval(refreshTimer) });
  }
}

export function deactivate(): void {
  if (refreshTimer) clearInterval(refreshTimer);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

async function loadAll(
  client: MemgitDaemonClient,
  memoryProvider: MemoryTreeProvider,
  historyProvider: CheckpointTreeProvider,
  bar: vscode.StatusBarItem
): Promise<void> {
  const online = await client.isReachable();
  if (online) {
    await Promise.all([memoryProvider.load(), historyProvider.load()]);
    const memories = memoryProvider.getMemories();
    bar.text = `$(database) memgit: ${memories.length} memories`;
    bar.tooltip = "Click to search memories";
    bar.backgroundColor = undefined;
  } else {
    bar.text = `$(database) memgit: offline`;
    bar.tooltip = "memgit daemon not running — run `memgit serve --http`";
    bar.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
    memoryProvider.refresh();
    historyProvider.refresh();
  }
}

function showMemoryDocument(memory: Memory, context: vscode.ExtensionContext): void {
  const panel = vscode.window.createWebviewPanel(
    "memgitMemory",
    `memgit: ${memory.slug}`,
    vscode.ViewColumn.Beside,
    { enableScripts: false }
  );
  panel.webview.html = buildMemoryHtml(memory);
  context.subscriptions.push(panel);
}

function buildMemoryHtml(m: Memory): string {
  const priorityLabel = m.priority === 3 ? "Critical (!3)" : m.priority === 2 ? "Normal (!2)" : "Low (!1)";
  const tags = m.tags?.length ? m.tags.join(", ") : "—";
  const why = m.why ? `<p><strong>Why:</strong> ${escHtml(m.why)}</p>` : "";
  const when = m.when ? `<p><strong>When:</strong> ${escHtml(m.when)}</p>` : "";

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 20px; max-width: 640px; }
  h1 { font-size: 1.2em; color: var(--vscode-textLink-foreground); }
  .rule { background: var(--vscode-textBlockQuote-background); border-left: 4px solid var(--vscode-textLink-foreground); padding: 12px 16px; border-radius: 4px; margin: 12px 0; font-size: 1em; white-space: pre-wrap; }
  .meta { font-size: 0.85em; color: var(--vscode-descriptionForeground); margin-top: 16px; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; background: var(--vscode-badge-background); color: var(--vscode-badge-foreground); margin-right: 4px; font-size: 0.8em; }
</style>
</head>
<body>
<h1>${escHtml(m.slug)}</h1>
<div>
  <span class="badge">${escHtml(m.type)}</span>
  <span class="badge">${escHtml(priorityLabel)}</span>
  ${(m.tags ?? []).map((t) => `<span class="badge">${escHtml(t)}</span>`).join("")}
</div>
<div class="rule">${escHtml(m.rule)}</div>
${why}
${when}
<div class="meta">
  <p><strong>Slug:</strong> ${escHtml(m.slug)}</p>
  <p><strong>Type:</strong> ${escHtml(m.type)}</p>
  <p><strong>Priority:</strong> ${m.priority}</p>
  <p><strong>Tags:</strong> ${escHtml(tags)}</p>
</div>
</body>
</html>`;
}

function escHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

async function injectToCursorRules(
  workspaceRoot: string,
  client: MemgitDaemonClient
): Promise<void> {
  let memories: import("./daemonClient").Memory[];
  try {
    memories = await client.listMemories(2); // priority >= 2
  } catch {
    return; // daemon offline — skip silently
  }

  const toonBlock = memories
    .map((m) => {
      const ts = m.when ?? new Date().toISOString().slice(0, 16) + "Z";
      return `TOON1|${m.type}|${m.slug}|${ts}\nRULE:${m.rule}`;
    })
    .join("\n\n");

  const marker_start = "<!-- MEMGIT_START -->";
  const marker_end = "<!-- MEMGIT_END -->";

  const candidateFiles = [".cursorrules", ".windsurfrules"];
  for (const filename of candidateFiles) {
    const filePath = path.join(workspaceRoot, filename);
    let existing = "";
    if (fs.existsSync(filePath)) {
      existing = fs.readFileSync(filePath, "utf8");
    }

    const injectedBlock = `${marker_start}\n# memgit — auto-managed memory block, do not edit\n${toonBlock}\n${marker_end}`;

    let newContent: string;
    if (existing.includes(marker_start)) {
      newContent = existing.replace(
        new RegExp(`${marker_start}[\\s\\S]*?${marker_end}`),
        injectedBlock
      );
    } else {
      newContent = injectedBlock + (existing ? "\n\n" + existing : "");
    }

    fs.writeFileSync(filePath, newContent, "utf8");
  }
}
