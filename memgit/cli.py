"""memgit CLI — git for AI memory."""

from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

from .models import Mnemonic
from .repo import Repository
from .toon import mnemonic_to_markdown, serialize_mnemonic

console = Console()
err = Console(stderr=True)


def _require_repo() -> Repository:
    repo = Repository.find()
    if repo is None:
        err.print('[red]Not in a memgit repository. Run `memgit init` first.[/red]')
        sys.exit(1)
    return repo


# ── Root group ────────────────────────────────────────────────────────────────

@click.group()
@click.version_option('0.1.0', prog_name='memgit')
def cli():
    """memgit — git for AI memory.

    Version-controlled context persistence for Claude Code and other AI tools.
    """
    pass


# ── init ──────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument('directory', default='.', type=click.Path())
def init(directory):
    """Initialize a memgit repository."""
    path = Path(directory).resolve()
    if (path / '.memgit').exists():
        console.print(f'[yellow]Already initialized:[/yellow] {path / ".memgit"}')
        return
    repo = Repository.init(path)
    console.print(f'[green]Initialized[/green] memgit repository in [cyan]{repo.path}[/cyan]')


# ── add ───────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument('slug')
@click.argument('rule')
@click.option('--type', '-t', 'type_code', default='fb',
              type=click.Choice(['fb', 'us', 'pj', 'rf', 'cn', 'lx']),
              help='fb=feedback us=user pj=project rf=reference cn=convention lx=lesson')
@click.option('--why', '-w', default=None, help='Reasoning / why this rule exists')
@click.option('--when', '-W', default=None, help='When / where to apply')
@click.option('--tags', default=None, help='Comma-separated tags')
@click.option('--priority', '-p', default=2, type=click.IntRange(1, 3),
              help='1=low  2=medium  3=critical (always loaded)')
def add(slug, rule, type_code, why, when, tags, priority):
    """Add or update a mnemonic.

    SLUG  kebab-case identifier (e.g. ig-pipeline-no-fallback)\n
    RULE  the primary fact / rule (quoted if it contains spaces)
    """
    repo = _require_repo()
    tag_list = [t.strip() for t in tags.split(',')] if tags else []

    m = Mnemonic(
        type_code=type_code,
        slug=slug,
        timestamp=datetime.now(timezone.utc),
        rule=rule,
        why=why,
        when=when,
        tags=tag_list,
        priority=priority,
    )
    sha = repo.add(m)
    console.print(f'[green]staged[/green]  {slug} [{sha[:8]}]')


# ── remove ────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument('slug')
def remove(slug):
    """Remove a mnemonic from the index (does not delete history)."""
    repo = _require_repo()
    if repo.remove(slug):
        console.print(f'[yellow]removed[/yellow] {slug}')
    else:
        console.print(f'[dim]not found: {slug}[/dim]')


# ── commit ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option('--message', '-m', default=None, help='Checkpoint message')
def commit(message):
    """Create a checkpoint of the current memory state."""
    repo = _require_repo()
    sha = repo.commit(message=message)
    if sha is None:
        console.print('[dim]Nothing to commit — memory state unchanged.[/dim]')
    else:
        console.print(f'[green]checkpoint[/green] {sha[:8]}')
        ck = repo.store.read_checkpoint(sha)
        console.print(f'    {ck.message}')


# ── status ────────────────────────────────────────────────────────────────────

@cli.command()
def status():
    """Show current repository status."""
    repo = _require_repo()
    thread = repo.current_thread()
    head = repo.head_sha()

    console.print(f'Thread: [cyan]{thread}[/cyan]')
    if head:
        console.print(f'HEAD:   [yellow]{head[:8]}[/yellow]')
        ck = repo.store.read_checkpoint(head)
        console.print(f'        {ck.message}')
    else:
        console.print('HEAD:   [dim]none[/dim]')

    # Staged vs committed
    index = repo.get_index()
    if head:
        ms = repo.store.read_mindstate(
            repo.store.read_checkpoint(head).mindstate_sha
        )
        committed = {e.slug: e.mnem_sha for e in ms.entries}
    else:
        committed = {}

    new_slugs = [s for s in index if s not in committed]
    updated = [s for s in index if s in committed and index[s] != committed[s]]
    removed = [s for s in committed if s not in index]

    if new_slugs or updated or removed:
        console.print('\n[bold]Staged changes (not yet committed):[/bold]')
        for s in new_slugs:
            console.print(f'  [green]new[/green]      {s}')
        for s in updated:
            console.print(f'  [yellow]updated[/yellow]  {s}')
        for s in removed:
            console.print(f'  [red]removed[/red]  {s}')
        console.print('\n[dim]  (run "memgit commit" to checkpoint)[/dim]')
    else:
        total = len(index)
        console.print(f'\n[dim]Clean — {total} mnemonic{"s" if total != 1 else ""} committed[/dim]')


# ── log ───────────────────────────────────────────────────────────────────────

@cli.command()
@click.option('--limit', '-n', default=10, help='Max checkpoints to show')
@click.option('--oneline', is_flag=True, help='Compact one-line format')
def log(limit, oneline):
    """Show checkpoint history."""
    repo = _require_repo()
    checkpoints = repo.log(limit=limit)
    if not checkpoints:
        console.print('[dim]No checkpoints yet.[/dim]')
        return

    for ck in checkpoints:
        sha_s = ck.sha[:8] if ck.sha else '????????'
        ts = ck.timestamp.strftime('%Y-%m-%d %H:%M')

        if oneline:
            console.print(f'[yellow]{sha_s}[/yellow]  {ts}  {ck.message}')
        else:
            console.print(f'\n[yellow]checkpoint {sha_s}[/yellow]')
            console.print(f'  Date:    {ts}')
            console.print(f'  Trigger: {ck.trigger}')
            console.print(f'  Author:  {ck.author}')
            console.print(f'  Message: {ck.message}')
            if ck.diff_summary:
                d = ck.diff_summary
                parts = []
                if d.added:
                    parts.append(f'[green]+{len(d.added)}[/green]')
                if d.modified:
                    parts.append(f'[yellow]~{len(d.modified)}[/yellow]')
                if d.removed:
                    parts.append(f'[red]-{len(d.removed)}[/red]')
                if parts:
                    console.print(f'  Changes: {" ".join(parts)}')


# ── diff ──────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument('sha1', required=False)
@click.argument('sha2', required=False)
@click.option('--full', is_flag=True, help='Show rule text for changed mnemonics')
def diff(sha1, sha2, full):
    """Show diff between two checkpoints (default: HEAD^ vs HEAD)."""
    repo = _require_repo()

    if full:
        changes = repo.diff_full(sha1, sha2)
        for slug, status, old_m, new_m in changes:
            if status == 'unchanged':
                continue
            color = {'added': 'green', 'removed': 'red', 'modified': 'yellow'}[status]
            marker = {'added': '+', 'removed': '-', 'modified': '~'}[status]
            console.print(f'[{color}]{marker} {slug}[/{color}]')
            if status in ('added', 'modified') and new_m:
                console.print(f'  [dim]RULE:[/dim] {new_m.rule}')
            if status == 'modified' and old_m:
                console.print(f'  [dim]WAS:[/dim]  {old_m.rule}')
    else:
        d = repo.diff(sha1, sha2)
        for s in d.added:
            console.print(f'[green]+ {s}[/green]')
        for s in d.modified:
            console.print(f'[yellow]~ {s}[/yellow]')
        for s in d.removed:
            console.print(f'[red]- {s}[/red]')
        if not d.added and not d.modified and not d.removed:
            console.print('[dim]No changes[/dim]')


# ── show ──────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument('slug')
@click.option('--toon', is_flag=True, help='Show raw TOON format')
@click.option('--markdown', 'fmt_markdown', is_flag=True, help='Show Claude Code markdown format')
def show(slug, toon, fmt_markdown):
    """Show a mnemonic."""
    repo = _require_repo()
    m = repo.get(slug)
    if m is None:
        err.print(f'[red]No mnemonic: {slug}[/red]')
        sys.exit(1)

    if fmt_markdown:
        print(mnemonic_to_markdown(m))
    elif toon:
        print(serialize_mnemonic(m))
    else:
        sha_s = m.sha[:8] if m.sha else '?'
        p_label = {1: 'low', 2: 'medium', 3: '[bold red]CRITICAL[/bold red]'}[m.priority]
        console.print(f'[bold cyan]{m.slug}[/bold cyan]  [{m.type_code}]  priority={p_label}  sha={sha_s}')
        console.print(f'')
        console.print(f'[bold]RULE[/bold] {m.rule}')
        if m.why:
            console.print(f'[bold]WHY[/bold]  {m.why}')
        if m.when:
            console.print(f'[bold]WHEN[/bold] {m.when}')
        if m.desc:
            console.print(f'[bold]DESC[/bold] {m.desc}')
        if m.who:
            console.print(f'[bold]WHO[/bold]  {m.who}')
        if m.where:
            console.print(f'[bold]WHERE[/bold] {m.where}')
        if m.inc:
            console.print(f'[bold]INC[/bold]  {m.inc}')
        if m.cost:
            console.print(f'[bold]COST[/bold] {m.cost}')
        if m.tags:
            console.print(f'[dim]Tags: {", ".join(m.tags)}[/dim]')
        if m.related:
            console.print(f'[dim]Related: {", ".join(m.related)}[/dim]')
        if m.supersedes:
            console.print(f'[dim]Supersedes: {", ".join(m.supersedes)}[/dim]')


# ── list ──────────────────────────────────────────────────────────────────────

@cli.command(name='list')
@click.option('--type', '-t', 'type_filter', default=None,
              type=click.Choice(['fb', 'us', 'pj', 'rf', 'cn', 'lx']),
              help='Filter by type')
@click.option('--priority', '-p', default=None, type=click.IntRange(1, 3), help='Filter by priority')
@click.option('--toon', is_flag=True, help='Show TOON format')
def list_cmd(type_filter, priority, toon):
    """List all mnemonics in the current thread."""
    repo = _require_repo()
    mnemonics = repo.list()
    if type_filter:
        mnemonics = [m for m in mnemonics if m.type_code == type_filter]
    if priority:
        mnemonics = [m for m in mnemonics if m.priority == priority]
    mnemonics.sort(key=lambda m: (m.type_code, m.slug))

    if not mnemonics:
        console.print('[dim]No mnemonics.[/dim]')
        return

    if toon:
        for m in mnemonics:
            print(serialize_mnemonic(m))
            print()
        return

    table = Table(show_header=True, header_style='bold', box=None, pad_edge=False)
    table.add_column('Slug', style='cyan', min_width=20)
    table.add_column('T', width=2)
    table.add_column('P', width=1)
    table.add_column('Rule', max_width=70)

    for m in mnemonics:
        p_str = '!' if m.priority == 3 else str(m.priority)
        rule_preview = m.rule[:68] + '..' if len(m.rule) > 68 else m.rule
        table.add_row(m.slug, m.type_code, p_str, rule_preview)

    console.print(table)
    console.print(f'\n[dim]{len(mnemonics)} mnemonic{"s" if len(mnemonics) != 1 else ""}[/dim]')


# ── import ────────────────────────────────────────────────────────────────────

@cli.group(name='import')
def import_group():
    """Import memories from other sources."""
    pass


@import_group.command(name='claude-code')
@click.argument('path', required=False, type=click.Path(exists=True, file_okay=False))
@click.option('--dry-run', is_flag=True, help='Preview without importing')
@click.option('--no-commit', is_flag=True, help='Stage but do not checkpoint')
def import_claude_code(path, dry_run, no_commit):
    """Import Claude Code memory markdown files.

    PATH  optional directory to read from (default: ~/.claude/projects/*/memory/)
    """
    from .importer import from_claude_code
    repo = _require_repo()

    mem_dir = Path(path) if path else None
    mnemonics = from_claude_code(mem_dir)

    if not mnemonics:
        console.print('[yellow]No memories found.[/yellow]')
        return

    console.print(f'Found [bold]{len(mnemonics)}[/bold] memories')

    if dry_run:
        for m in mnemonics:
            rule_preview = m.rule[:60] + '..' if len(m.rule) > 60 else m.rule
            console.print(f'  [cyan]{m.slug}[/cyan] [{m.type_code}]  {rule_preview}')
        return

    count = 0
    for m in mnemonics:
        try:
            repo.add(m)
            count += 1
        except Exception as e:
            err.print(f'[yellow]skip {m.slug}: {e}[/yellow]')

    console.print(f'[green]Staged {count} memories[/green]')

    if not no_commit:
        sha = repo.commit(
            message=f'Import {count} memories from Claude Code',
            trigger='import',
        )
        if sha:
            console.print(f'[green]Checkpoint[/green] {sha[:8]}')
        else:
            console.print('[dim]Nothing new to checkpoint[/dim]')


@import_group.command(name='toon-file')
@click.argument('path', type=click.Path(exists=True, dir_okay=False))
@click.option('--dry-run', is_flag=True)
def import_toon_file(path, dry_run):
    """Import mnemonics from a .toon file."""
    from .importer import from_toon_file
    repo = _require_repo()

    mnemonics = from_toon_file(Path(path))
    if not mnemonics:
        console.print('[yellow]No mnemonics found.[/yellow]')
        return

    console.print(f'Found [bold]{len(mnemonics)}[/bold] mnemonics')
    if dry_run:
        for m in mnemonics:
            console.print(f'  [cyan]{m.slug}[/cyan] [{m.type_code}]')
        return

    for m in mnemonics:
        repo.add(m)
    sha = repo.commit(trigger='import')
    if sha:
        console.print(f'[green]Imported {len(mnemonics)} mnemonics → checkpoint {sha[:8]}[/green]')


# ── export ────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument('slug')
@click.option('--toon', 'fmt', flag_value='toon', default=True, help='TOON format (default)')
@click.option('--markdown', 'fmt', flag_value='markdown', help='Claude Code markdown format')
def export(slug, fmt):
    """Export a mnemonic to stdout."""
    repo = _require_repo()
    m = repo.get(slug)
    if m is None:
        err.print(f'[red]No mnemonic: {slug}[/red]')
        sys.exit(1)
    if fmt == 'markdown':
        print(mnemonic_to_markdown(m))
    else:
        print(serialize_mnemonic(m))


# ── fsck ──────────────────────────────────────────────────────────────────────

@cli.command()
@click.option('--rebuild-index', is_flag=True, help='Rebuild TOON_INDEX from HEAD')
def fsck(rebuild_index):
    """Verify repository integrity."""
    repo = _require_repo()
    console.print('Checking…')
    errors = repo.fsck(rebuild_index=rebuild_index)
    index = repo.get_index()
    if errors:
        for e in errors:
            err.print(f'[red]{e}[/red]')
        sys.exit(1)
    else:
        console.print(f'[green]OK[/green] — {len(index)} objects verified'
                      + (', index rebuilt' if rebuild_index else ''))


# ── thread ────────────────────────────────────────────────────────────────────

@cli.group()
def thread():
    """Manage memory threads (branches)."""
    pass


@thread.command(name='list')
def thread_list():
    """List all threads."""
    repo = _require_repo()
    current = repo.current_thread()
    threads = repo.thread_list()
    for t in sorted(threads, key=lambda t: t.name):
        marker = '*' if t.name == current else ' '
        sha_s = t.head_sha[:8] if t.head_sha else '?'
        console.print(f'  {marker} [cyan]{t.name}[/cyan]  [{sha_s}]')


@thread.command(name='create')
@click.argument('name')
@click.option('--description', '-d', default='')
def thread_create(name, description):
    """Create a new thread from HEAD."""
    repo = _require_repo()
    t = repo.thread_create(name, description)
    console.print(f'[green]Created thread[/green] {name} from {t.head_sha[:8]}')


@thread.command(name='switch')
@click.argument('name')
def thread_switch(name):
    """Switch to a different thread."""
    repo = _require_repo()
    try:
        repo.thread_switch(name)
        console.print(f'[green]Switched to[/green] {name}')
    except ValueError as e:
        err.print(f'[red]{e}[/red]')
        sys.exit(1)


# ── lint ──────────────────────────────────────────────────────────────────────

@cli.command()
def lint():
    """Lint all staged mnemonics."""
    repo = _require_repo()
    mnemonics = repo.list()
    issues = 0
    for m in mnemonics:
        if not m.rule:
            console.print(f'[red]{m.slug}[/red]: missing RULE')
            issues += 1
        if len(m.rule) > 400:
            console.print(f'[yellow]{m.slug}[/yellow]: RULE too long ({len(m.rule)} chars, max 400)')
            issues += 1
        if not re.match(r'^[a-z0-9_-]+$', m.slug):
            console.print(f'[yellow]{m.slug}[/yellow]: slug should be kebab-case [a-z0-9_-]')
            issues += 1
    if issues == 0:
        console.print(f'[green]OK[/green] — {len(mnemonics)} mnemonics, no issues')
    else:
        console.print(f'[yellow]{issues} issue{"s" if issues != 1 else ""}[/yellow]')


import re  # noqa: E402 — needed for lint command


# ── search ────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument('query')
@click.option('--top', '-k', default=10, help='Max results to return')
@click.option('--toon', is_flag=True, help='Output TOON format (token-efficient)')
@click.option('--json', 'fmt_json', is_flag=True, help='Output JSON')
@click.option('--type', '-t', 'type_filter', default=None,
              type=click.Choice(['fb', 'us', 'pj', 'rf', 'cn', 'lx']),
              help='Filter by type before scoring')
def search(query, top, toon, fmt_json, type_filter):
    """Search memories by relevance.

    Returns the top-k mnemonics scored against QUERY using BM25.
    """
    import json
    from .scorer import score as bm25_score

    repo = _require_repo()
    mnemonics = repo.list()
    if type_filter:
        mnemonics = [m for m in mnemonics if m.type_code == type_filter]

    results = bm25_score(query, mnemonics, top_k=top)

    if not results:
        console.print('[dim]No results.[/dim]')
        return

    if fmt_json:
        out = []
        for r in results:
            m = r.mnemonic
            out.append({
                'slug': m.slug,
                'score': r.score,
                'type': m.type_code,
                'priority': m.priority,
                'rule': m.rule,
                'why': m.why,
                'when': m.when,
                'tags': m.tags,
                'matched': r.matched_fields,
            })
        print(json.dumps(out, indent=2))
        return

    if toon:
        for r in results:
            print(serialize_mnemonic(r.mnemonic))
            print()
        return

    table = Table(show_header=True, header_style='bold', box=None, pad_edge=False)
    table.add_column('Score', width=6, style='dim')
    table.add_column('Slug', style='cyan', min_width=20)
    table.add_column('T', width=2)
    table.add_column('Rule', max_width=65)

    for r in results:
        m = r.mnemonic
        rule_preview = m.rule[:63] + '..' if len(m.rule) > 63 else m.rule
        table.add_row(f'{r.score:.2f}', m.slug, m.type_code, rule_preview)

    console.print(table)
    console.print(f'\n[dim]{len(results)} result{"s" if len(results) != 1 else ""} for "{query}"[/dim]')


# ── sync ──────────────────────────────────────────────────────────────────────

@cli.command()
@click.option('--message', '-m', default=None, help='Custom checkpoint message')
@click.option('--dry-run', is_flag=True, help='Show what would be imported, no writes')
def sync(message, dry_run):
    """Sync from Claude Code memory files and auto-checkpoint.

    Imports all Claude Code markdown memory files, stages changes,
    and creates a checkpoint if anything changed. Safe to run repeatedly.
    """
    from .importer import from_claude_code

    repo = _require_repo()
    mnemonics = from_claude_code()

    if not mnemonics:
        console.print('[dim]No Claude Code memories found.[/dim]')
        return

    if dry_run:
        console.print(f'Would import [bold]{len(mnemonics)}[/bold] memories:')
        for m in mnemonics[:10]:
            console.print(f'  [cyan]{m.slug}[/cyan] [{m.type_code}]')
        if len(mnemonics) > 10:
            console.print(f'  [dim]… and {len(mnemonics) - 10} more[/dim]')
        return

    count = 0
    skipped = 0
    for m in mnemonics:
        try:
            repo.add(m)
            count += 1
        except Exception:
            skipped += 1

    msg = message or f'sync: {count} memories from Claude Code'
    sha = repo.commit(message=msg, trigger='session_end')

    if sha:
        console.print(f'[green]sync[/green]  {sha[:8]}  {count} staged' +
                      (f', {skipped} skipped' if skipped else ''))
    else:
        console.print(f'[dim]sync: no changes ({count} memories already current)[/dim]')


# ── graph ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.option('--output', '-o', default=None,
              help='Output HTML file path (default: memgit-graph.html in repo dir)')
@click.option('--open', 'auto_open', is_flag=True, default=True,
              help='Open in browser after generating (default: true)')
@click.option('--no-open', 'auto_open', flag_value=False,
              help='Skip opening browser')
def graph(output, auto_open):
    """Generate an interactive HTML graph of the memory store.

    Visualizes all mnemonics as a force-directed graph with:
      - Nodes colored by type (fb/us/pj/rf/cn/lx)
      - Node size by priority
      - Edges from [[wikilink]] references and explicit related/supersedes links
      - Filter by type, search by keyword, click to highlight neighbours
      - Checkpoint timeline in the sidebar
    """
    import webbrowser
    from .graph import build_graph_data, render_html

    repo = _require_repo()
    data = build_graph_data(repo)
    html = render_html(data)

    out_path = Path(output) if output else (repo.path.parent / 'memgit-graph.html')
    out_path.write_text(html, encoding='utf-8')

    n = data['meta']['total']
    e = data['meta']['edge_count']
    console.print(f'[green]graph[/green]  {out_path}')
    console.print(f'       {n} nodes · {e} edges · {len(data["checkpoints"])} checkpoints')

    if auto_open:
        webbrowser.open(out_path.as_uri())
        console.print(f'[dim]opened in browser[/dim]')


# ── serve ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.option('--store', default=None,
              help='Path to memgit store dir (default: ~/.claude/memgit-store)')
@click.option('--http', 'use_http', is_flag=True, default=False,
              help='Run as HTTP REST server instead of MCP stdio (for GPT Actions, Gemini, etc.)')
@click.option('--port', default=7474, show_default=True,
              help='HTTP server port (only used with --http)')
def serve(store, use_http, port):
    """Start the memgit server.

    Default (no flags): MCP stdio server — for Claude Code, Cursor, Windsurf, Cline, Continue.dev.
    With --http: REST server — for GPT Custom Actions, Gemini function calling, any OpenAPI client.
    """
    store_path = Path(store).resolve() if store else None
    if use_http:
        from .http_server import run_http_server
        run_http_server(port=port, store_path=store_path)
    else:
        from .mcp_server import run_server
        run_server(store_path)


# ── stats ─────────────────────────────────────────────────────────────────────

@cli.command()
def stats():
    """Show token-savings proof and store health metrics.

    Compares loading ALL memories (the claude.md / dump approach) against
    memgit's relevance-filtered search — and shows the real token and dollar
    savings your team gets every session.
    """
    repo = _require_repo()
    s = repo.stats()

    if s.get('total', 0) == 0:
        console.print('[yellow]No memories yet. Run `memgit sync` or `memgit add` first.[/yellow]')
        return

    type_labels = {'fb': 'feedback', 'us': 'user', 'pj': 'project',
                   'rf': 'reference', 'cn': 'convention', 'lx': 'lesson'}

    type_str = ' · '.join(
        f"{s['by_type'].get(tc, 0)} {lbl}"
        for tc, lbl in type_labels.items()
        if s['by_type'].get(tc, 0) > 0
    )

    prio = s['priority_counts']
    prio_str = f"{prio.get(3, 0)} critical · {prio.get(2, 0)} medium · {prio.get(1, 0)} low"

    reduction = s['reduction_pct']
    full_tok = s['full_tokens']
    search_tok = s['avg_search_tokens']
    crit_tok = s['critical_tokens']

    weekly_tokens = s['weekly_savings_tokens']
    weekly_usd = s['weekly_savings_usd']

    ck_count = s['checkpoint_count']
    first_ts = s['first_checkpoint_ts'].strftime('%Y-%m-%d') if s['first_checkpoint_ts'] else '—'
    last_ts = s['last_checkpoint_ts'].strftime('%Y-%m-%d') if s['last_checkpoint_ts'] else '—'

    # ── render ────────────────────────────────────────────────────────────────
    from rich.rule import Rule
    from rich.panel import Panel
    from rich import box

    console.print()
    console.print(Rule('[bold cyan]memgit stats[/bold cyan]'))
    console.print()

    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column(style='dim', width=30)
    t.add_column()

    t.add_row('Total memories', f'[bold]{s["total"]}[/bold]   {type_str}')
    t.add_row('Priority breakdown', prio_str)
    t.add_row('Checkpoints', f'{ck_count}   {first_ts} → {last_ts}')
    console.print(t)
    console.print()

    console.print('[bold]Token cost comparison[/bold]')
    console.print()

    bench = Table(box=box.SIMPLE, header_style='bold')
    bench.add_column('Approach', style='', min_width=30)
    bench.add_column('Tokens/session', justify='right')
    bench.add_column('vs full load', justify='right')
    bench.add_column('$/session (GPT-4o)', justify='right')

    from .tokens import token_cost_usd
    bench.add_row(
        '[red]claude.md / dump all memories[/red]',
        f'{full_tok:,}',
        '100%  baseline',
        f'${token_cost_usd(full_tok):.4f}',
    )
    bench.add_row(
        '[yellow]mem-search plugin (top-20 obs)[/yellow]',
        f'{min(full_tok, search_tok * 2):,}  [dim](est.)[/dim]',
        f'~{min(100, round(100 * min(full_tok, search_tok * 2) / full_tok))}%',
        f'${token_cost_usd(min(full_tok, search_tok * 2)):.4f}',
    )
    bench.add_row(
        '[green]memgit search (BM25 top-8)[/green]',
        f'{search_tok:,}',
        f'[green]{100 - reduction}%  ({reduction}% savings)[/green]',
        f'[green]${token_cost_usd(search_tok):.4f}[/green]',
    )
    if crit_tok > 0:
        bench.add_row(
            '[cyan]  + critical memories (always)[/cyan]',
            f'+{crit_tok:,}  [dim](overhead)[/dim]',
            '',
            '',
        )
    console.print(bench)

    console.print()
    console.print('[bold]Weekly savings  [dim](10 sessions/week)[/dim][/bold]')
    console.print()

    savings = Table(box=None, show_header=False, padding=(0, 2))
    savings.add_column(style='dim', width=30)
    savings.add_column()

    savings.add_row('Tokens saved/week', f'[green]{weekly_tokens:,}[/green]')
    savings.add_row('Cost saved/week (GPT-4o)', f'[green]${weekly_usd:.4f}[/green]')
    savings.add_row('', '')
    savings.add_row('Annualised token savings', f'[bold green]{weekly_tokens * 52:,}[/bold green]')
    savings.add_row('Annualised cost savings', f'[bold green]${weekly_usd * 52:.2f}[/bold green]')
    console.print(savings)

    console.print()
    has_flat = (repo.path.parent / 'memories').exists()
    has_git = (repo.path.parent / '.git').exists()
    git_status = '[green]✓[/green]' if has_git else '[red]✗[/red] (run `memgit git init` to enable team sync)'
    flat_status = '[green]✓[/green]' if has_flat else '[yellow]–[/yellow] (run `memgit git export`)'
    console.print(f'[dim]Git sync:[/dim]  {git_status}   [dim]Flat memories/:[/dim] {flat_status}')
    console.print()


# ── squash ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option('--keep-last', type=int, default=None,
              help='Keep this many recent checkpoints; squash the rest into one baseline')
@click.option('--older-than', 'older_than_days', type=int, default=None, metavar='DAYS',
              help='Squash all checkpoints older than N days')
@click.option('--dry-run', is_flag=True, help='Preview what would be squashed without changing anything')
def squash(keep_last, older_than_days, dry_run):
    """Squash old checkpoints to keep history manageable at scale.

    Like `git rebase --autosquash`, but for memory history. Collapses old
    checkpoints into a single baseline so the store stays fast even at
    10,000+ commits. The current memory state is always preserved — only
    the historical chain is compressed.

    Examples:

      memgit squash --keep-last 100      Keep only the last 100 checkpoints

      memgit squash --older-than 30      Squash everything older than 30 days

      memgit squash --dry-run            Preview without making changes
    """
    repo = _require_repo()
    result = repo.squash(
        keep_last=keep_last,
        older_than_days=older_than_days,
        dry_run=dry_run,
    )

    kept = result['kept']
    squashed = result['squashed']

    if squashed == 0:
        console.print('[yellow]Nothing to squash (too few checkpoints).[/yellow]')
        return

    if dry_run:
        console.print(f'[dim]dry-run:[/dim] would squash [yellow]{squashed}[/yellow] checkpoints '
                      f'(baseline: {result["baseline_ts"]}) '
                      f'→ keep [green]{kept}[/green] recent ones')
    else:
        console.print(f'[green]squash[/green]  {squashed} old checkpoints '
                      f'→ baseline at {result["baseline_ts"]}  '
                      f'[dim]({kept} kept, new HEAD: {result.get("new_head", "?")})[/dim]')


# ── git ───────────────────────────────────────────────────────────────────────

@cli.group()
def git():
    """Git-native sync — push/pull memories across machines and teammates.

    memgit stores are plain git repos under the hood. Every memory is a
    readable .toon file in memories/. Standard git commands work on them.

    Quick start:

      memgit git init                 Initialize git in your store

      memgit git push                 Push memories to remote

      memgit git pull                 Pull teammate memories from remote

      memgit git export               Write flat memories/ files (no push)

      memgit git status               Show what's changed since last push
    """
    pass


@git.command('init')
@click.option('--remote', default=None, help='Git remote URL to add as "origin" (optional)')
def git_init(remote):
    """Initialize git in the memory store for team sync.

    After this, your memory store is a regular git repo. You can:

      cd ~/.claude/memgit-store

      git remote add origin git@github.com:yourteam/ai-memory.git

      git push -u origin main

    Then teammates run `memgit git pull` to get your memories.
    """
    repo = _require_repo()
    ok = repo.git_init()
    if not ok:
        err.print('[red]git init failed — is git installed?[/red]')
        return

    store_root = repo.path.parent
    if remote:
        try:
            import subprocess
            subprocess.run(['git', 'remote', 'add', 'origin', remote],
                           cwd=store_root, check=True, capture_output=True)
            console.print(f'[green]git init[/green]  {store_root}  remote: {remote}')
        except Exception:
            console.print(f'[green]git init[/green]  {store_root}  [yellow](remote add failed — add manually)[/yellow]')
    else:
        console.print(f'[green]git init[/green]  {store_root}')
        console.print(f'[dim]Add a remote: cd {store_root} && git remote add origin <url>[/dim]')

    # Write initial flat files
    repo.write_flat()
    mem_count = len(list((store_root / 'memories').glob('*.toon')))
    console.print(f'[dim]memories/: {mem_count} .toon files ready to commit[/dim]')


@git.command('export')
def git_export():
    """Write all memories as flat .toon files in memories/ without pushing.

    Creates one file per memory: memories/{slug}.toon

    Files are human-readable, greppable, and diff-friendly. You can also
    search across all your memories with: grep -r "trading" memories/
    """
    repo = _require_repo()
    repo.write_flat()
    store_root = repo.path.parent
    count = len(list((store_root / 'memories').glob('*.toon')))
    console.print(f'[green]export[/green]  {count} memories → {store_root / "memories"}')
    console.print(f'[dim]Grep them: grep -rl "your query" {store_root / "memories"}[/dim]')


@git.command('push')
@click.argument('remote', default='origin')
@click.argument('branch', default='main')
@click.option('--message', '-m', default=None, help='Git commit message')
def git_push(remote, branch, message):
    """Write flat files, git commit, and push to remote.

    This is how you share memories with teammates:

      memgit git push                      Push to origin/main

      memgit git push upstream feature     Push to upstream/feature
    """
    repo = _require_repo()
    ok, msg = repo.git_push(remote=remote, branch=branch, message=message)
    color = 'green' if ok else 'red'
    console.print(f'[{color}]{"push" if ok else "error"}[/{color}]  {msg}')


@git.command('pull')
@click.argument('remote', default='origin')
@click.argument('branch', default='main')
def git_pull_cmd(remote, branch):
    """Pull memories from a git remote and import them.

    After a `git pull`, memgit imports any new or updated memories from
    the memories/ flat files and creates a new checkpoint.

    Teammate workflow:

      git clone git@github.com:yourteam/ai-memory.git ~/.claude/memgit-store

      memgit git pull          # then pull updates anytime
    """
    repo = _require_repo()
    ok, msg, count = repo.git_pull(remote=remote, branch=branch)
    color = 'green' if ok else 'red'
    console.print(f'[{color}]{"pull" if ok else "error"}[/{color}]  {msg}')


@git.command('status')
def git_status_cmd():
    """Show what's changed in the memory store since the last git commit."""
    repo = _require_repo()
    status = repo.git_status()
    if status is None:
        console.print('[yellow]Not a git repo. Run `memgit git init` first.[/yellow]')
        return
    if not status:
        console.print('[green]Nothing to push — memories are in sync.[/green]')
    else:
        console.print('[bold]Changes since last git commit:[/bold]')
        console.print(status)


# ── setup ─────────────────────────────────────────────────────────────────────

import shutil as _shutil
import json as _json


def _memgit_cmd() -> list[str]:
    """Return the best command to launch `memgit serve`.

    Priority: running binary path > which > python -m fallback.
    sys.argv[0] ensures we register the exact binary that ran setup,
    not whatever 'memgit' is first in PATH.
    """
    import sys as _sys, os as _os
    argv0 = _sys.argv[0]
    if _os.path.isabs(argv0) and _os.path.isfile(argv0):
        return [argv0, 'serve']
    resolved = _os.path.realpath(argv0) if argv0 else None
    if resolved and _os.path.isfile(resolved):
        return [resolved, 'serve']
    binary = _shutil.which('memgit')
    if binary:
        return [binary, 'serve']
    return [_sys.executable, '-m', 'memgit.cli', 'serve']


def _mcp_server_entry() -> dict:
    cmd = _memgit_cmd()
    return {'command': cmd[0], 'args': cmd[1:]}


def _write_json_safe(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(data, indent=2) + '\n', encoding='utf-8')


def _patch_mcp_servers(config_path: Path, dry_run: bool = False) -> str:
    """Upsert mcpServers.memgit in a JSON config file. Returns status string."""
    if config_path.exists():
        try:
            data = _json.loads(config_path.read_text(encoding='utf-8'))
        except _json.JSONDecodeError:
            data = {}
    else:
        data = {}

    servers = data.setdefault('mcpServers', {})
    existing = servers.get('memgit')
    entry = _mcp_server_entry()

    if existing == entry:
        return 'already registered'

    servers['memgit'] = entry
    if not dry_run:
        _write_json_safe(config_path, data)
    return 'updated' if existing else 'registered'


def _patch_continue(config_path: Path, dry_run: bool = False) -> str:
    """Patch Continue.dev config.json which uses a list, not a dict."""
    if config_path.exists():
        try:
            data = _json.loads(config_path.read_text(encoding='utf-8'))
        except _json.JSONDecodeError:
            data = {}
    else:
        data = {}

    entry = _mcp_server_entry()
    entry['name'] = 'memgit'

    servers: list = data.setdefault('mcpServers', [])
    for i, s in enumerate(servers):
        if s.get('name') == 'memgit':
            if s == entry:
                return 'already registered'
            servers[i] = entry
            if not dry_run:
                _write_json_safe(config_path, data)
            return 'updated'

    servers.append(entry)
    if not dry_run:
        _write_json_safe(config_path, data)
    return 'registered'


# Targets: (label, config_path_fn, patch_fn)
def _all_targets():
    home = Path.home()
    app_support = home / 'Library' / 'Application Support'
    linux_config = home / '.config'
    return [
        (
            'Claude Code',
            home / '.claude' / 'settings.json',
            _patch_mcp_servers,
        ),
        (
            'Claude Desktop (macOS)',
            app_support / 'Claude' / 'claude_desktop_config.json',
            _patch_mcp_servers,
        ),
        (
            'Claude Desktop (Linux)',
            linux_config / 'Claude' / 'claude_desktop_config.json',
            _patch_mcp_servers,
        ),
        (
            'Cursor',
            home / '.cursor' / 'mcp.json',
            _patch_mcp_servers,
        ),
        (
            'Windsurf',
            home / '.windsurf' / 'mcp.json',
            _patch_mcp_servers,
        ),
        (
            'Cline (VS Code)',
            app_support / 'Code' / 'User' / 'globalStorage' / 'saoudrizwan.claude-dev' / 'settings' / 'cline_mcp_settings.json',
            _patch_mcp_servers,
        ),
        (
            'Roo-Code (VS Code)',
            app_support / 'Code' / 'User' / 'globalStorage' / 'rooveterinaryinc.roo-cline' / 'settings' / 'cline_mcp_settings.json',
            _patch_mcp_servers,
        ),
        (
            'Continue.dev',
            home / '.continue' / 'config.json',
            _patch_continue,
        ),
    ]


@cli.group()
def setup():
    """Register memgit with AI coding tools (MCP).

    Writes the memgit MCP server entry into each tool's config file.
    Safe to run multiple times — only updates what's missing.
    """
    pass


def _run_target(label: str, config_path: Path, patch_fn, dry_run: bool) -> None:
    exists = config_path.exists()
    if not exists and label.startswith('Claude Desktop (Linux)') and (Path.home() / 'Library').exists():
        # Skip Linux path on macOS
        return
    if not exists and 'Linux' in label and not (Path.home() / '.config').exists():
        return

    try:
        status = patch_fn(config_path, dry_run=dry_run)
        icon = '[green]✓[/green]' if 'registered' in status or 'already' in status else '[yellow]↻[/yellow]'
        note = ' [dim](dry run)[/dim]' if dry_run else ''
        console.print(f'{icon} {label}: {status}{note}')
        console.print(f'  [dim]{config_path}[/dim]')
    except Exception as e:
        console.print(f'[red]✗[/red] {label}: {e}')


@setup.command('all')
@click.option('--dry-run', is_flag=True, help='Show what would be changed without writing files.')
def setup_all(dry_run):
    """Detect all installed AI tools and register memgit with each.

    Safe to re-run. Skips tools that aren't installed (config dir missing).
    Only registers tools whose config file already exists OR whose parent dir exists.
    """
    cmd = _memgit_cmd()
    console.print(f'[bold]memgit setup all[/bold]  command=[cyan]{" ".join(cmd)}[/cyan]\n')

    registered = 0
    skipped = 0
    for label, config_path, patch_fn in _all_targets():
        # Skip if neither the file nor its parent directory exists
        # (tool not installed on this machine)
        if not config_path.exists() and not config_path.parent.exists():
            skipped += 1
            continue
        _run_target(label, config_path, patch_fn, dry_run)
        registered += 1

    console.print(f'\n[dim]{registered} tool(s) processed, {skipped} not installed (skipped)[/dim]')
    if not dry_run and registered:
        console.print('[dim]Restart each AI tool for changes to take effect.[/dim]')


@setup.command('claude-code')
@click.option('--dry-run', is_flag=True)
def setup_claude_code(dry_run):
    """Register with Claude Code (~/.claude/settings.json)."""
    path = Path.home() / '.claude' / 'settings.json'
    _run_target('Claude Code', path, _patch_mcp_servers, dry_run)


@setup.command('claude-desktop')
@click.option('--dry-run', is_flag=True)
def setup_claude_desktop(dry_run):
    """Register with Claude Desktop app."""
    mac = Path.home() / 'Library' / 'Application Support' / 'Claude' / 'claude_desktop_config.json'
    linux = Path.home() / '.config' / 'Claude' / 'claude_desktop_config.json'
    path = mac if mac.parent.exists() else linux
    _run_target('Claude Desktop', path, _patch_mcp_servers, dry_run)


@setup.command('cursor')
@click.option('--dry-run', is_flag=True)
def setup_cursor(dry_run):
    """Register with Cursor (~/.cursor/mcp.json)."""
    path = Path.home() / '.cursor' / 'mcp.json'
    _run_target('Cursor', path, _patch_mcp_servers, dry_run)


@setup.command('windsurf')
@click.option('--dry-run', is_flag=True)
def setup_windsurf(dry_run):
    """Register with Windsurf (~/.windsurf/mcp.json)."""
    path = Path.home() / '.windsurf' / 'mcp.json'
    _run_target('Windsurf', path, _patch_mcp_servers, dry_run)


@setup.command('cline')
@click.option('--dry-run', is_flag=True)
def setup_cline(dry_run):
    """Register with Cline/Roo-Code (VS Code extension)."""
    base = Path.home() / 'Library' / 'Application Support' / 'Code' / 'User' / 'globalStorage'
    for slug, label in [
        ('saoudrizwan.claude-dev', 'Cline'),
        ('rooveterinaryinc.roo-cline', 'Roo-Code'),
    ]:
        path = base / slug / 'settings' / 'cline_mcp_settings.json'
        if path.parent.exists() or path.exists():
            _run_target(label, path, _patch_mcp_servers, dry_run)
        else:
            console.print(f'[dim]skip {label} — not installed[/dim]')


@setup.command('continue')
@click.option('--dry-run', is_flag=True)
def setup_continue(dry_run):
    """Register with Continue.dev (~/.continue/config.json)."""
    path = Path.home() / '.continue' / 'config.json'
    _run_target('Continue.dev', path, _patch_continue, dry_run)


@setup.command('print-config')
@click.argument('tool', default='generic',
                type=click.Choice(['claude-code', 'claude-desktop', 'cursor', 'windsurf', 'continue', 'generic']))
def setup_print_config(tool):
    """Print the config snippet to copy-paste manually.

    Useful when you need to edit the config yourself or when auto-setup fails.
    """
    entry = _mcp_server_entry()

    if tool == 'continue':
        snippet = _json.dumps({'mcpServers': [{'name': 'memgit', **entry}]}, indent=2)
    else:
        snippet = _json.dumps({'mcpServers': {'memgit': entry}}, indent=2)

    console.print(f'\n[bold]Config snippet for {tool}:[/bold]\n')
    console.print(snippet)
    console.print('\n[dim]Merge this into your tool\'s config file.[/dim]')
