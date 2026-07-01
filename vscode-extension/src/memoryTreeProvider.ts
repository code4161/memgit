import * as vscode from "vscode";
import { MemgitDaemonClient, Memory, Checkpoint } from "./daemonClient";

// ── Memory Explorer (sidebar) ─────────────────────────────────────────────────

type GroupKey = "critical" | "recent" | "all";

export class MemoryItem extends vscode.TreeItem {
  constructor(
    public readonly memory: Memory,
    collapsible = vscode.TreeItemCollapsibleState.None
  ) {
    super(memory.slug, collapsible);
    this.contextValue = "memory";
    this.tooltip = memory.rule;
    this.description = this.buildDescription(memory);
    this.iconPath = this.priorityIcon(memory.priority);
  }

  private buildDescription(m: Memory): string {
    const parts: string[] = [`[${m.type}]`];
    const preview = m.rule.length > 55 ? m.rule.slice(0, 52) + "…" : m.rule;
    parts.push(preview);
    return parts.join(" ");
  }

  private priorityIcon(priority: number): vscode.ThemeIcon {
    if (priority === 3) return new vscode.ThemeIcon("star-full", new vscode.ThemeColor("charts.yellow"));
    if (priority === 2) return new vscode.ThemeIcon("circle-filled", new vscode.ThemeColor("charts.blue"));
    return new vscode.ThemeIcon("circle-outline");
  }
}

class GroupItem extends vscode.TreeItem {
  constructor(
    public readonly key: GroupKey,
    label: string,
    public readonly children: MemoryItem[]
  ) {
    super(label, vscode.TreeItemCollapsibleState.Expanded);
    this.contextValue = "group";
    this.description = `${children.length}`;
    this.iconPath = groupIcon(key);
  }
}

function groupIcon(key: GroupKey): vscode.ThemeIcon {
  if (key === "critical") return new vscode.ThemeIcon("star");
  if (key === "recent") return new vscode.ThemeIcon("clock");
  return new vscode.ThemeIcon("list-unordered");
}

type TreeNode = GroupItem | MemoryItem;

export class MemoryTreeProvider
  implements vscode.TreeDataProvider<TreeNode>
{
  private _onDidChangeTreeData = new vscode.EventEmitter<TreeNode | undefined | void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private memories: Memory[] = [];
  private daemonOnline = false;

  constructor(private readonly client: MemgitDaemonClient) {}

  refresh(): void {
    this._onDidChangeTreeData.fire();
  }

  async load(): Promise<void> {
    try {
      this.memories = await this.client.listMemories();
      this.daemonOnline = true;
    } catch {
      this.memories = [];
      this.daemonOnline = false;
    }
    this.refresh();
  }

  getTreeItem(element: TreeNode): vscode.TreeItem {
    return element;
  }

  getChildren(element?: TreeNode): TreeNode[] {
    if (!this.daemonOnline) return [];

    if (!element) return this.buildGroups();

    if (element instanceof GroupItem) return element.children;

    return [];
  }

  private buildGroups(): GroupItem[] {
    const critical = this.memories
      .filter((m) => m.priority === 3)
      .map((m) => new MemoryItem(m));

    const recentCutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
    const recent = this.memories
      .filter((m) => m.priority < 3 && m.when && Date.parse(m.when) > recentCutoff)
      .map((m) => new MemoryItem(m));

    const criticalSlugs = new Set(critical.map((i) => i.memory.slug));
    const recentSlugs = new Set(recent.map((i) => i.memory.slug));
    const rest = this.memories
      .filter((m) => !criticalSlugs.has(m.slug) && !recentSlugs.has(m.slug))
      .map((m) => new MemoryItem(m));

    const groups: GroupItem[] = [];
    if (critical.length) groups.push(new GroupItem("critical", `Critical (!3)`, critical));
    if (recent.length) groups.push(new GroupItem("recent", `Recent (7d)`, recent));
    if (rest.length) groups.push(new GroupItem("all", `All Memories`, rest));

    return groups;
  }

  getMemories(): Memory[] {
    return this.memories;
  }
}

// ── History Log (sidebar) ─────────────────────────────────────────────────────

export class CheckpointItem extends vscode.TreeItem {
  constructor(public readonly checkpoint: Checkpoint) {
    super(checkpoint.sha, vscode.TreeItemCollapsibleState.None);
    const ts = new Date(checkpoint.timestamp).toLocaleString();
    this.description = ts;
    this.tooltip = `${checkpoint.message}\n${ts}`;
    const added = checkpoint.added ?? 0;
    const modified = checkpoint.modified ?? 0;
    const removed = checkpoint.removed ?? 0;
    if (added || modified || removed) {
      this.tooltip += `\n+${added} ~${modified} -${removed}`;
    }
    this.iconPath = new vscode.ThemeIcon("git-commit");
    this.contextValue = "checkpoint";
  }
}

export class CheckpointTreeProvider
  implements vscode.TreeDataProvider<CheckpointItem>
{
  private _onDidChangeTreeData = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private checkpoints: Checkpoint[] = [];

  constructor(private readonly client: MemgitDaemonClient) {}

  refresh(): void {
    this._onDidChangeTreeData.fire();
  }

  async load(): Promise<void> {
    try {
      this.checkpoints = await this.client.getCheckpoints(20);
    } catch {
      this.checkpoints = [];
    }
    this.refresh();
  }

  getTreeItem(element: CheckpointItem): vscode.TreeItem {
    return element;
  }

  getChildren(): CheckpointItem[] {
    return this.checkpoints.map((ck) => new CheckpointItem(ck));
  }
}
