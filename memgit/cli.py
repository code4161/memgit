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

# Source of truth is the code, not dist metadata: editable installs keep
# whatever metadata version existed at `pip install -e` time (observed: a
# 0.3.1 checkout reporting 0.1.0 via importlib.metadata).
from . import __version__ as _version


@click.group()
@click.version_option(_version, prog_name='memgit')
def cli():
    """memgit — git for AI memory.

    Version-controlled context persistence for Claude Code and other AI tools.
    """
    pass


# ── init ──────────────────────────────────────────────────────────────────────

def _default_store_path() -> Path:
    """Pick the best default store location based on what's installed."""
    from .repo import default_store_candidates
    for candidate in default_store_candidates():
        # candidates are <tool-dir>/memgit-store; pick the first whose tool dir exists
        if candidate.parent.exists() and candidate.parent != Path.home():
            return candidate
    return Path.home() / '.memgit-store'


@cli.command()
@click.argument('directory', default=None, required=False, type=click.Path())
def init(directory):
    """Initialize a memgit store.

    If no path is given, picks the best location automatically:
      · ~/.claude/memgit-store   (if Claude Code is installed)
      · ~/.cursor/memgit-store   (if Cursor is installed)
      · ~/.windsurf/memgit-store (if Windsurf is installed)
      · ~/.memgit-store          (fallback)
    """
    if directory is None:
        path = _default_store_path()
        console.print(f'[dim]Using[/dim] [cyan]{path}[/cyan]  [dim](auto-detected)[/dim]')
    else:
        path = Path(directory).resolve()

    if (path / '.memgit').exists():
        console.print(f'[yellow]Already initialized:[/yellow] {path / ".memgit"}')
        return
    repo = Repository.init(path)
    console.print(f'[green]Initialized[/green] memgit store in [cyan]{repo.path}[/cyan]')

    # Step-by-step flow: find existing memories automatically and offer the
    # import, instead of making the user discover the right path themselves.
    try:
        from .importer import from_claude_code
        found = from_claude_code()
    except Exception:
        found = []
    if found:
        projects = {m.project for m in found if m.project}
        console.print(f'\nFound [bold]{len(found)}[/bold] existing Claude Code memories '
                      f'across [bold]{len(projects)}[/bold] projects '
                      f'[dim](~/.claude/projects/*/memory)[/dim]')
        do_import = True
        if sys.stdin.isatty():
            do_import = click.confirm('Import them now?', default=True)
        if do_import:
            count, skipped, renamed = _stage_imported(repo, found)
            sha = repo.commit(message=f'onboard: imported {count} Claude Code memories',
                              trigger='import')
            console.print(f'[green]Imported {count} memories[/green]'
                          + (f'  [dim]checkpoint {sha[:8]}[/dim]' if sha else ''))
        else:
            console.print('[dim]Skipped — run [bold]memgit sync[/bold] anytime to import.[/dim]')

    console.print(f'\n[bold]Next steps[/bold]')
    console.print(f'  1. [bold]memgit setup[/bold]    register with your AI tools (interactive)')
    console.print(f'  2. [bold]memgit onboard[/bold]  seed memories for a project that has none')
    console.print(f'  3. [bold]memgit stats[/bold]    see what you saved')


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
@click.option('--body', '-b', default=None,
              help='Full long-form detail (multi-line ok, or "-" to read stdin)')
@click.option('--project', '-P', default=None,
              help='Project this memory belongs to (default: derived from the '
                   'current directory; pass "" for a global memory)')
def add(slug, rule, type_code, why, when, tags, priority, body, project):
    """Add or update a mnemonic.

    SLUG  kebab-case identifier (e.g. ig-pipeline-no-fallback)\n
    RULE  the primary fact / rule (quoted if it contains spaces)
    """
    repo = _require_repo()
    tag_list = [t.strip() for t in tags.split(',')] if tags else []
    if body == '-':
        body = sys.stdin.read().strip() or None
    # Same scoping semantics as MCP save_memory: absent → this workspace,
    # explicit empty → deliberately global.
    if project is None:
        from .project import project_label_from_path
        project = project_label_from_path(Path.cwd())
    elif not project.strip():
        project = None

    m = Mnemonic(
        type_code=type_code,
        slug=slug,
        timestamp=datetime.now(timezone.utc),
        rule=rule,
        why=why,
        when=when,
        tags=tag_list,
        priority=priority,
        body=body,
        project=project,
    )
    sha = repo.add(m)
    from rich.markup import escape as _mesc
    console.print(f'[green]staged[/green]  {_mesc(m.slug)} {_mesc("[" + sha[:8] + "]")}')


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

    hint = repo.maintenance_hint()
    if hint:
        console.print(f'[yellow]maintenance:[/yellow] {hint}')


# ── resume ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option('--checkpoints', '-n', default=5, help='Recent checkpoints to include')
@click.option('--recent', '-r', default=10, help='Recently updated memories to include')
@click.option('--plain', is_flag=True, help='Plain text (for hooks / piping into an AI context)')
@click.option('--json', 'fmt_json', is_flag=True, help='JSON output')
@click.option('--project', '-P', default=None,
              help='Prefer this project\'s memories in the digest '
                   '(default: derived from the current directory)')
def resume(checkpoints, recent, plain, fmt_json, project):
    """Show where you left off — the session-start primer.

    Prints the last checkpoints, staged work in flight, recently updated
    memories, and critical rules. Designed to orient an AI agent (or you)
    at the start of a session. Wire it into Claude Code automatically with
    `memgit setup hooks`. Runs project-aware: the recent-memories section
    leads with the project you are standing in.
    """
    import json as _j
    from .importer import project_label_from_path
    repo = _require_repo()
    if project is None:
        project = project_label_from_path(Path.cwd())
    ctx = repo.resume_context(checkpoints=checkpoints, recent=recent, project=project)

    if fmt_json:
        print(_j.dumps(ctx, indent=2, default=str))
        return

    if plain:
        print(_format_resume_plain(ctx))
        return

    console.print(f'\n[bold cyan]memgit resume[/bold cyan] — thread [cyan]{ctx["thread"]}[/cyan] '
                  f'@ [yellow]{ctx["head"] or "none"}[/yellow]  '
                  f'[dim]({ctx["checkpoint_count"]} checkpoints, {ctx["total_memories"]} memories)[/dim]\n')

    st = ctx['staged']
    if st['new'] or st['updated'] or st['removed']:
        console.print('[bold]Work in flight (staged, not committed):[/bold]')
        for s in st['new']:
            console.print(f'  [green]new[/green]      {s}')
        for s in st['updated']:
            console.print(f'  [yellow]updated[/yellow]  {s}')
        for s in st['removed']:
            console.print(f'  [red]removed[/red]  {s}')
        console.print()

    console.print('[bold]Last checkpoints:[/bold]')
    for ck in ctx['checkpoints']:
        ts = ck['timestamp'].strftime('%Y-%m-%d %H:%M')
        delta = f"+{ck['added']} ~{ck['modified']} -{ck['removed']}"
        console.print(f'  [yellow]{ck["sha"]}[/yellow]  {ts}  {ck["message"]}  [dim]{delta} · {ck["author"]}[/dim]')

    if ctx['recent_memories']:
        console.print('\n[bold]Recently updated memories:[/bold]')
        for m in ctx['recent_memories']:
            ts = m['timestamp'].strftime('%m-%d')
            rule = m['rule'][:80] + '..' if len(m['rule']) > 80 else m['rule']
            console.print(f'  [cyan]{m["slug"]}[/cyan] [dim][{m["type"]} {ts}][/dim] {rule}')

    if ctx['critical_memories']:
        console.print('\n[bold red]Critical rules (always apply):[/bold red]')
        for m in ctx['critical_memories']:
            console.print(f'  [red]![/red] [cyan]{m["slug"]}[/cyan]  {m["rule"]}')
    if ctx.get('maintenance'):
        console.print(f'\n[yellow]maintenance:[/yellow] {ctx["maintenance"]}')
    console.print()


def _format_resume_plain(ctx: dict) -> str:
    """Plain-text resume digest — injected into AI context by the SessionStart hook.

    Deliberately bounded (~300-600 tokens regardless of store size): rules are
    truncated and the critical list is capped, because this text is paid for
    at the start of EVERY session. Full text is one get_memory call away.
    """
    def clip(text: str, n: int = 200) -> str:
        return text if len(text) <= n else text[:n - 1] + '…'

    proj = f' · project {ctx["project"]}' if ctx.get('project') else ''
    lines = [
        f'# memgit resume — thread {ctx["thread"]} @ {ctx["head"] or "none"} '
        f'({ctx["checkpoint_count"]} checkpoints, {ctx["total_memories"]} memories{proj})',
    ]
    st = ctx['staged']
    if st['new'] or st['updated'] or st['removed']:
        lines.append('')
        lines.append('## Work in flight (staged, not committed)')
        for s in st['new']:
            lines.append(f'- new: {s}')
        for s in st['updated']:
            lines.append(f'- updated: {s}')
        for s in st['removed']:
            lines.append(f'- removed: {s}')
    if ctx['checkpoints']:
        lines.append('')
        lines.append('## Last checkpoints (newest first)')
        for ck in ctx['checkpoints']:
            ts = ck['timestamp'].strftime('%Y-%m-%d %H:%M')
            lines.append(f'- {ck["sha"]} {ts} [{ck["author"]}] {clip(ck["message"], 160)}')
    if ctx['recent_memories']:
        lines.append('')
        lines.append('## Recently updated memories')
        for m in ctx['recent_memories']:
            ts = m['timestamp'].strftime('%Y-%m-%d')
            # flag memories from OTHER projects so the agent doesn't conflate them
            other = (f' [{m["project"]}]'
                     if m.get('project') and m['project'] != ctx.get('project') else '')
            lines.append(f'- {m["slug"]} ({m["type"]}, {ts}){other}: {clip(m["rule"], 160)}')
    if ctx['critical_memories']:
        lines.append('')
        lines.append('## Critical rules — always apply')
        crit = ctx['critical_memories']
        for m in crit[:20]:
            lines.append(f'- {m["slug"]}: {clip(m["rule"])}')
        if len(crit) > 20:
            lines.append(f'- …and {len(crit) - 20} more — run list_memories with min_priority=3')
    if ctx.get('maintenance'):
        lines.append('')
        lines.append(f'## Maintenance needed\n- {ctx["maintenance"]}')
    if ctx.get('project_is_new'):
        lines.append('')
        lines.append(
            f'## This project has no memories yet ({ctx["project"]})\n'
            '- memgit was adopted mid-project: nothing above is specific to this '
            'workspace. Bootstrap it once — run `memgit onboard` for a repo '
            'digest + seeding brief, then save 10-20 durable facts '
            '(purpose, architecture, conventions, state, gotchas) via save_memory.'
        )
    lines.append('')
    lines.append('(Check work-in-flight and the last checkpoints before assuming state; '
                 'use memgit search for anything task-specific.)')
    return '\n'.join(lines)


# ── hook handlers (invoked by AI-tool hosts, not humans) ─────────────────────

@cli.group(name='hook')
def hook():
    """Hook handlers for AI-tool hosts (installed by `memgit setup hooks`)."""


@hook.command('prompt-recall')
def hook_prompt_recall():
    """UserPromptSubmit: inject memories relevant to the prompt (stdin JSON)."""
    from .hooks import prompt_recall
    sys.exit(prompt_recall())


@hook.command('stop-guard')
def hook_stop_guard():
    """Stop: nudge once if a substantive session saved nothing (stdin JSON)."""
    from .hooks import stop_guard
    sys.exit(stop_guard())


# ── onboard ───────────────────────────────────────────────────────────────────

ONBOARD_BRIEF = """\
# memgit onboard — bootstrap memory for {project}

This project has {count} memories in memgit{count_note}. A memory store that
starts empty mid-project is useless until it is seeded — do that now, once,
and every future session (in any AI tool) starts oriented.
{digest_section}
## Instructions for the AI operator

Extract 10–20 DURABLE facts about this project and save each one as a memory
(via the memgit MCP `save_memory` tool, or `memgit add` in a shell).
{reading_plan}

## What to save (one memory each, not a dump)

- `pj` project: what this project IS, its goal, its current state / active work
- `cn` convention: code style, naming, architecture rules an AI must follow
- `rf` reference: key entry points, dashboards, external services, URLs
- `fb` feedback: known constraints ("never touch X", "Y is production")
- `lx` lesson: past incidents or gotchas documented in the repo

Rules for good memories: one fact per memory; kebab-case slug; a one-line
`rule` stating the fact; details in `body`; set `project` to "{project}";
priority 3 ONLY for always-apply safety rules; tag with real topics.

## Finish

Checkpoint the seed set so it is versioned from day one:

    memgit commit -m "onboard: {project}"

Then verify: `memgit search "<something about this project>"` should hit.
"""

_READING_PLAN_WITH_DIGEST = """\
The repo digest above was extracted deterministically from git and the
filesystem — treat it as ground truth and do NOT re-derive it. On a large
repo, do NOT crawl the tree. Work only from:

1. The "Read these first" files listed in the digest — purpose, architecture, setup
2. The manifests listed — stack, entry points, scripts, dependencies
3. The recent commit subjects + hot areas — what is being worked on RIGHT NOW
   (turn these into the "current state / active work" memory)
4. Config/env samples and CI files if present — deploy targets, environments, gates"""

_READING_PLAN_GENERIC = """\
Read, in this order, whatever exists:

1. README / CLAUDE.md / CONTRIBUTING / docs/ — purpose, architecture, setup
2. Package manifests (package.json, pyproject.toml, go.mod, …) — stack, entry points, scripts
3. `git log --oneline -30` and recent PRs — what is being worked on RIGHT NOW
4. Config/env samples, CI files — deploy targets, environments, gates
5. The code layout itself — modules, boundaries, naming conventions"""


@cli.command()
@click.option('--project', '-P', default=None,
              help='Project label (default: derived from the current directory)')
@click.option('--path', 'proj_path', default='.', type=click.Path(exists=True),
              help='Project directory to onboard (default: cwd)')
@click.option('--json', 'fmt_json', is_flag=True, help='Emit the raw repo digest as JSON')
def onboard(project, proj_path, fmt_json):
    """Print the bootstrap brief for adopting memgit on an existing project.

    memgit only knows what has been saved — a project adopted midway starts
    with zero context. This mines the repo's git history and filesystem
    (bounded and read-only, fast even on huge repos) into a factual digest,
    then prints a step-by-step brief for an AI agent (or you) to seed the
    store from it. Paste it into your AI session, or run
    `memgit onboard | pbcopy`.
    """
    from .gitdigest import build_digest, format_digest
    from .importer import project_label_from_path

    repo = _require_repo()
    target = Path(proj_path)
    label = project or project_label_from_path(target) or target.resolve().name

    digest = build_digest(target)
    if fmt_json:
        import json as _j
        digest['project'] = label
        print(_j.dumps(digest, indent=2))
        return

    count = sum(1 for m in repo.list() if m.project == label)
    count_note = '' if count else ' — it is a blank slate for this project'

    rendered = format_digest(digest)
    if rendered:
        digest_section = ('\n## Repo digest (auto-extracted — trust it, don\'t re-derive)\n\n'
                          f'{rendered}\n')
        reading_plan = _READING_PLAN_WITH_DIGEST
    else:
        digest_section = ''
        reading_plan = _READING_PLAN_GENERIC

    print(ONBOARD_BRIEF.format(project=label, count=count, count_note=count_note,
                               digest_section=digest_section, reading_plan=reading_plan))


# ── log ───────────────────────────────────────────────────────────────────────

@cli.command()
@click.option('--limit', '-n', default=10, help='Max checkpoints to show')
@click.option('--skip', default=0, help='Skip the newest N checkpoints (pagination)')
@click.option('--oneline', is_flag=True, help='Compact one-line format')
def log(limit, skip, oneline):
    """Show checkpoint history."""
    repo = _require_repo()
    checkpoints = repo.log(limit=limit, skip=skip)
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


# ── rollback ──────────────────────────────────────────────────────────────────

@cli.command()
@click.argument('ref')
@click.option('--dry-run', is_flag=True, help='Preview changes without applying')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
def rollback(ref, dry_run, yes):
    """Restore memory state to a checkpoint (HEAD~N or SHA).

    Creates a new checkpoint matching the target state — history is
    preserved, nothing is deleted. Examples:

    \b
      memgit rollback HEAD~2
      memgit rollback a1d9f3c
      memgit rollback HEAD~1 --dry-run
    """
    repo = _require_repo()

    try:
        _, d = repo.rollback(ref, dry_run=True)
    except ValueError:
        err.print(f'[red]Cannot resolve ref:[/red] {ref}')
        sys.exit(1)

    for s in d.added:
        console.print(f'[green]+ {s}[/green]  [dim](restored)[/dim]')
    for s in d.modified:
        console.print(f'[yellow]~ {s}[/yellow]  [dim](reverted to older version)[/dim]')
    for s in d.removed:
        console.print(f'[red]- {s}[/red]')

    if not d.added and not d.modified and not d.removed:
        console.print('[dim]Already at that state — nothing to roll back.[/dim]')
        return
    if dry_run:
        console.print('[dim]Dry run — no changes applied.[/dim]')
        return
    if not yes and not click.confirm('Confirm rollback?'):
        console.print('[dim]Aborted.[/dim]')
        return

    new_sha, _ = repo.rollback(ref)
    console.print(f'[green]Rolled back[/green] → new checkpoint [cyan]{(new_sha or "")[:8]}[/cyan]')


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
        # User content and shas go through markup escaping — `[pj]`,
        # `[[wikilinks]]`, or a sha like [fadc1234] would otherwise be
        # eaten as rich tags and silently altered on screen.
        from rich.markup import escape as _mesc
        sha_s = m.sha[:8] if m.sha else '?'
        p_label = {1: 'low', 2: 'medium', 3: '[bold red]CRITICAL[/bold red]'}[m.priority]
        proj = f'  project={_mesc(m.project)}' if m.project else ''
        console.print(f'[bold cyan]{_mesc(m.slug)}[/bold cyan]  {_mesc("[" + m.type_code + "]")}  '
                      f'priority={p_label}{proj}  sha={_mesc(sha_s)}')
        console.print(f'')
        console.print(f'[bold]RULE[/bold] {_mesc(m.rule)}')
        if m.why:
            console.print(f'[bold]WHY[/bold]  {_mesc(m.why)}')
        if m.when:
            console.print(f'[bold]WHEN[/bold] {_mesc(m.when)}')
        if m.desc:
            console.print(f'[bold]DESC[/bold] {_mesc(m.desc)}')
        if m.body:
            console.print(f'\n[bold]BODY[/bold]')
            console.print(m.body, markup=False)
        if m.who:
            console.print(f'[bold]WHO[/bold]  {_mesc(m.who)}')
        if m.where:
            console.print(f'[bold]WHERE[/bold] {_mesc(m.where)}')
        if m.inc:
            console.print(f'[bold]INC[/bold]  {_mesc(m.inc)}')
        if m.cost:
            console.print(f'[bold]COST[/bold] {_mesc(m.cost)}')
        if m.tags:
            console.print(f'[dim]Tags: {_mesc(", ".join(m.tags))}[/dim]')
        if m.related:
            console.print(f'[dim]Related: {_mesc(", ".join(m.related))}[/dim]')
        if m.supersedes:
            console.print(f'[dim]Supersedes: {_mesc(", ".join(m.supersedes))}[/dim]')


# ── list ──────────────────────────────────────────────────────────────────────

@cli.command(name='list')
@click.option('--type', '-t', 'type_filter', default=None,
              type=click.Choice(['fb', 'us', 'pj', 'rf', 'cn', 'lx']),
              help='Filter by type')
@click.option('--priority', '-p', default=None, type=click.IntRange(1, 3), help='Filter by priority')
@click.option('--project', '-P', 'project_filter', default=None, help='Filter by project')
@click.option('--toon', is_flag=True, help='Show TOON format')
def list_cmd(type_filter, priority, project_filter, toon):
    """List all mnemonics in the current thread."""
    repo = _require_repo()
    mnemonics = repo.list()
    if type_filter:
        mnemonics = [m for m in mnemonics if m.type_code == type_filter]
    if priority:
        mnemonics = [m for m in mnemonics if m.priority == priority]
    if project_filter:
        mnemonics = [m for m in mnemonics if m.project == project_filter]
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
    table.add_column('Project', style='dim', max_width=18)
    table.add_column('Rule', max_width=60)

    for m in mnemonics:
        p_str = '!' if m.priority == 3 else str(m.priority)
        proj = (m.project or '')[:18]
        rule_preview = m.rule[:58] + '..' if len(m.rule) > 58 else m.rule
        table.add_row(m.slug, m.type_code, p_str, proj, rule_preview)

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

    count, skipped, renamed = _stage_imported(repo, mnemonics)
    for slug in renamed:
        console.print(f'  [yellow]collision[/yellow] stored as [cyan]{slug}[/cyan]')
    if skipped:
        err.print(f'[yellow]{skipped} skipped (parse/stage errors)[/yellow]')

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
        sys.exit(1)  # let scripts/CI gate on lint


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
@click.option('--project', '-P', 'project_filter', default=None,
              help='Only memories from this project (as shown in `memgit list`)')
def search(query, top, toon, fmt_json, type_filter, project_filter):
    """Search memories by relevance.

    Returns the top-k mnemonics scored against QUERY using BM25.
    """
    import json
    from .scorer import score as bm25_score

    repo = _require_repo()
    mnemonics = repo.list()
    if type_filter:
        mnemonics = [m for m in mnemonics if m.type_code == type_filter]
    if project_filter:
        mnemonics = [m for m in mnemonics if m.project == project_filter]

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

def _stage_imported(repo, mnemonics) -> tuple[int, int, list[str]]:
    """Stage imported mnemonics, re-slugging cross-project collisions.

    If an incoming slug already belongs to a DIFFERENT project, the incoming
    memory is stored as '<slug>--<project>' instead of silently overwriting.
    Returns (staged, skipped, renamed_slugs).
    """
    count = skipped = 0
    renamed: list[str] = []
    for m in mnemonics:
        try:
            existing = repo.get(m.slug)
            if (existing is not None and m.project and existing.project
                    and existing.project != m.project):
                suffix = re.sub(r'[^a-z0-9-]+', '-', m.project.lower()).strip('-')
                m.slug = f'{m.slug}--{suffix}'
                renamed.append(m.slug)
            repo.add(m)
            count += 1
        except Exception:
            skipped += 1
    return count, skipped, renamed


def _staged_diff_message(repo) -> Optional[str]:
    """Build a checkpoint message from what is actually staged vs HEAD."""
    index = repo.get_index()
    committed = repo._mindstate_map(repo.head_sha())
    new = sorted(s for s in index if s not in committed)
    upd = sorted(s for s in index if s in committed and index[s] != committed[s])
    rem = sorted(s for s in committed if s not in index)
    if not (new or upd or rem):
        return None
    changed = new + upd
    preview = ', '.join(changed[:4]) + (', …' if len(changed) > 4 else '')
    parts = [f'+{len(new)}'] if new else []
    if upd:
        parts.append(f'~{len(upd)}')
    if rem:
        parts.append(f'-{len(rem)}')
    return f'sync: {" ".join(parts)} ({preview})' if preview else f'sync: {" ".join(parts)}'


@cli.command()
@click.option('--message', '-m', default=None, help='Custom checkpoint message')
@click.option('--dry-run', is_flag=True, help='Show what would be imported, no writes')
def sync(message, dry_run):
    """Sync from Claude Code memory files and auto-checkpoint.

    Imports all Claude Code markdown memory files, stages changes,
    and creates a checkpoint if anything changed. Safe to run repeatedly.
    The checkpoint message names what actually changed.
    """
    from .importer import from_claude_code

    repo = _require_repo()
    mnemonics = from_claude_code()

    if not mnemonics:
        # No markdown sources on this machine — but anything already staged
        # (MCP saves, CLI adds) must still be checkpointed, or it lingers
        # uncommitted forever on stores fed purely through MCP.
        if not dry_run:
            msg = message or _staged_diff_message(repo)
            sha = repo.commit(message=msg, trigger='session_end') if msg else None
            if sha:
                console.print(f'[green]sync[/green]  {sha[:8]}  {msg}')
                return
        console.print('[dim]No Claude Code memories found.[/dim]')
        return

    if dry_run:
        console.print(f'Would import [bold]{len(mnemonics)}[/bold] memories:')
        for m in mnemonics[:10]:
            proj = f'  [dim]{m.project}[/dim]' if m.project else ''
            console.print(f'  [cyan]{m.slug}[/cyan] [{m.type_code}]{proj}')
        if len(mnemonics) > 10:
            console.print(f'  [dim]… and {len(mnemonics) - 10} more[/dim]')
        return

    count, skipped, renamed = _stage_imported(repo, mnemonics)
    for slug in renamed:
        console.print(f'  [yellow]collision[/yellow] stored as [cyan]{slug}[/cyan]')

    msg = message or _staged_diff_message(repo) or f'sync: {count} memories from Claude Code'
    sha = repo.commit(message=msg, trigger='session_end')

    if sha:
        console.print(f'[green]sync[/green]  {sha[:8]}  {msg}' +
                      (f'  [dim]({skipped} skipped)[/dim]' if skipped else ''))
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


# ── daemon ────────────────────────────────────────────────────────────────────

@cli.group()
def daemon():
    """Manage the memgit HTTP daemon (used by VS Code extension and IDE plugins)."""
    pass


@daemon.command('start')
@click.option('--port', default=7474, show_default=True, help='Port to listen on')
@click.option('--store', default=None, help='Path to memgit store dir')
def daemon_start(port, store):
    """Start the memgit HTTP daemon."""
    store_path = Path(store).resolve() if store else None
    from .http_server import run_http_server
    run_http_server(port=port, store_path=store_path)


@daemon.command('status')
@click.option('--port', default=7474, show_default=True, help='Daemon port to check')
def daemon_status(port):
    """Check whether the memgit daemon is running."""
    import urllib.request
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/status', timeout=2) as r:
            import json
            data = json.loads(r.read())
            console.print(f'[green]online[/green] — memgit {data.get("version","?")} · '
                          f'{data.get("memory_count", 0)} memories · port {port}')
    except Exception:
        console.print(f'[red]offline[/red] — daemon not reachable on port {port}')
        console.print('[dim]Run `memgit daemon start` to start it.[/dim]')


# ── stats ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.option('--json', 'fmt_json', is_flag=True, help='Machine-readable output (token-cheap for AI callers)')
def stats(fmt_json):
    """Show token-savings proof and store health metrics.

    Compares loading ALL memories (the claude.md / dump approach) against
    memgit's relevance-filtered search — and shows the real token and dollar
    savings your team gets every session.
    """
    repo = _require_repo()
    s = repo.stats()

    if fmt_json:
        import json as _j
        s['maintenance'] = repo.maintenance_hint(s.get('checkpoint_count'))
        print(_j.dumps(s, default=str))
        return

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
    by_project = s.get('by_project') or {}
    if len(by_project) > 1:
        top = sorted(by_project.items(), key=lambda kv: -kv[1])
        proj_str = ' · '.join(f'{n} {name}' for name, n in top[:6])
        if len(top) > 6:
            proj_str += f' · … {len(top) - 6} more'
        t.add_row('Projects', f'{len(by_project)}   {proj_str}')
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
@click.option('--json', 'fmt_json', is_flag=True, help='Machine-readable output (token-cheap for AI callers)')
def squash(keep_last, older_than_days, dry_run, fmt_json):
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

    if fmt_json:
        import json as _j
        print(_j.dumps(result))
        return

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


# ── gc ────────────────────────────────────────────────────────────────────────

def _human_bytes(n: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.1f} {unit}' if unit != 'B' else f'{n} B'
        n /= 1024
    return f'{n} B'


@cli.command()
@click.option('--dry-run', is_flag=True, help='Report what would be deleted without deleting')
@click.option('--squash-keep', type=int, default=None, metavar='N',
              help='First squash history to the last N checkpoints, then sweep')
@click.option('--reflog-keep', type=int, default=1000, show_default=True,
              help='Max reflog entries to keep per thread')
@click.option('--json', 'fmt_json', is_flag=True, help='Machine-readable output (token-cheap for AI callers)')
def gc(dry_run, squash_keep, reflog_keep, fmt_json):
    """Reclaim disk space — delete unreachable objects and trim reflogs.

    Only provably-unreachable objects are swept; reachable history and
    staged memories are never touched. Squashed-away checkpoints keep a
    one-line record in .memgit/logs/archive/ (never deleted).

    Typical maintenance:

      memgit gc --dry-run                Preview

      memgit gc                          Sweep orphans (safe anytime)

      memgit gc --squash-keep 200        Compact history, then sweep
    """
    repo = _require_repo()

    sq = None
    if squash_keep is not None:
        sq = repo.squash(keep_last=squash_keep, dry_run=dry_run)
        if sq['squashed'] and not fmt_json:
            verb = 'would squash' if dry_run else 'squashed'
            console.print(f'[green]squash[/green]  {verb} {sq["squashed"]} checkpoints '
                          f'→ {sq["kept"]} kept')

    r = repo.gc(dry_run=dry_run, reflog_keep=reflog_keep)

    if fmt_json:
        import json as _j
        if sq is not None:
            r['squash'] = sq
        print(_j.dumps(r))
        return

    verb = 'would delete' if dry_run else 'deleted'
    console.print(f'[green]gc[/green]  {verb} [bold]{r["objects_deleted"]}[/bold] unreachable objects '
                  f'({_human_bytes(r["bytes_freed"])} freed), '
                  f'trimmed {r["reflog_entries_trimmed"]} reflog entries')
    console.print(f'    [dim]store: {r["objects_after"]} objects, '
                  f'{_human_bytes(r["bytes_before"] - (0 if dry_run else r["bytes_freed"]))}[/dim]')


# ── merge ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument('thread_name')
@click.option('--message', '-m', default=None, help='Merge checkpoint message')
def merge(thread_name, message):
    """Merge another thread's memories into the current thread.

    Three-way merge against the common ancestor — the multi-agent workflow:
    each agent works on its own thread (memgit thread create agent-1), then
    the results merge back:

      memgit merge agent-1

    Conflicts (same memory changed on both sides) resolve to the newest
    version; an edit always beats a delete. Both histories are preserved.
    """
    repo = _require_repo()
    try:
        sha, conflicts, d = repo.merge_thread(thread_name, message=message)
    except ValueError as e:
        err.print(f'[red]{e}[/red]')
        sys.exit(1)

    for s in d.added:
        console.print(f'[green]+ {s}[/green]')
    for s in d.modified:
        console.print(f'[yellow]~ {s}[/yellow]')
    for s in d.removed:
        console.print(f'[red]- {s}[/red]')
    for s in conflicts:
        console.print(f'[magenta]⚡ {s}[/magenta]  [dim](both sides changed — newest kept)[/dim]')

    if sha is None:
        console.print('[dim]Already up to date — nothing to merge.[/dim]')
    else:
        console.print(f'[green]merge[/green]  {thread_name} → {repo.current_thread()}  '
                      f'checkpoint [cyan]{sha[:8]}[/cyan]')


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


def _memgit_base_cmd() -> list[str]:
    """Return the best command prefix to invoke this memgit installation.

    Priority: running binary path > which > python -m fallback.
    sys.argv[0] ensures we register the exact binary that ran setup,
    not whatever 'memgit' is first in PATH. A .py argv[0] (python -m runs)
    is not directly executable — fall through to the interpreter form.
    """
    import sys as _sys, os as _os
    argv0 = _sys.argv[0]
    if not argv0.endswith('.py'):
        if _os.path.isabs(argv0) and _os.path.isfile(argv0):
            return [argv0]
        resolved = _os.path.realpath(argv0) if argv0 else None
        if resolved and _os.path.isfile(resolved):
            return [resolved]
    binary = _shutil.which('memgit')
    if binary:
        return [binary]
    return [_sys.executable, '-m', 'memgit.cli']


def _memgit_cmd() -> list[str]:
    """Return the best command to launch `memgit serve`."""
    return _memgit_base_cmd() + ['serve']


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
            # Never clobber an existing config we can't parse — for Claude Code
            # this file (~/.claude.json) holds all user state, not just MCP.
            raise RuntimeError(
                f'{config_path} exists but is not valid JSON — fix it manually, then re-run setup'
            )
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


# Targets: (label, config_path, patch_fn, detect_path)
# detect_path: existence marks the tool as installed; None falls back to
# "config file or its parent dir exists". Claude Code needs an explicit one
# because its real MCP config (~/.claude.json) sits directly in $HOME —
# Claude Code ignores mcpServers in ~/.claude/settings.json.
def _all_targets():
    home = Path.home()
    app_support = home / 'Library' / 'Application Support'
    linux_config = home / '.config'
    return [
        (
            'Claude Code',
            home / '.claude.json',
            _patch_mcp_servers,
            home / '.claude',
        ),
        (
            'Claude Desktop (macOS)',
            app_support / 'Claude' / 'claude_desktop_config.json',
            _patch_mcp_servers,
            None,
        ),
        (
            'Claude Desktop (Linux)',
            linux_config / 'Claude' / 'claude_desktop_config.json',
            _patch_mcp_servers,
            None,
        ),
        (
            'Cursor',
            home / '.cursor' / 'mcp.json',
            _patch_mcp_servers,
            None,
        ),
        (
            'Windsurf',
            home / '.windsurf' / 'mcp.json',
            _patch_mcp_servers,
            None,
        ),
        (
            'Cline (VS Code)',
            app_support / 'Code' / 'User' / 'globalStorage' / 'saoudrizwan.claude-dev' / 'settings' / 'cline_mcp_settings.json',
            _patch_mcp_servers,
            None,
        ),
        (
            'Roo-Code (VS Code)',
            app_support / 'Code' / 'User' / 'globalStorage' / 'rooveterinaryinc.roo-cline' / 'settings' / 'cline_mcp_settings.json',
            _patch_mcp_servers,
            None,
        ),
        (
            'Continue.dev',
            home / '.continue' / 'config.json',
            _patch_continue,
            None,
        ),
        (
            'Gemini CLI',
            home / '.gemini' / 'settings.json',
            _patch_mcp_servers,
            home / '.gemini',
        ),
    ]


def _setup_wizard() -> None:
    """Interactive step-by-step tool picker for `memgit setup` (bare)."""
    targets = _all_targets()

    detected, missing = [], []
    for label, config_path, patch_fn, detect_path in targets:
        installed = (
            detect_path.exists()
            if detect_path is not None
            else config_path.exists() or config_path.parent.exists()
        )
        (detected if installed else missing).append((label, config_path, patch_fn))

    console.print('[bold]memgit setup[/bold] — interactive tool registration\n')

    if not detected:
        console.print('[yellow]No AI tools detected on this machine.[/yellow]')
        console.print('Install Claude Code, Cursor, Windsurf, Cline, or Continue.dev first,')
        console.print('then run [bold]memgit setup all[/bold] or [bold]memgit setup <tool>[/bold].')
        return

    console.print('[green]Detected on this machine:[/green]')
    for i, (label, config_path, _) in enumerate(detected, 1):
        note = 'config exists' if config_path.exists() else 'dir exists'
        console.print(f'  [bold]{i}[/bold]. {label}  [dim]({note})[/dim]')

    if missing:
        console.print('\n[dim]Not detected (will be skipped):[/dim]')
        for label, _, _ in missing:
            console.print(f'  [dim]· {label}[/dim]')

    console.print()
    choice = click.prompt('Register which tools? (all / 1,2,3 / none)', default='all')
    choice = choice.strip().lower()

    if choice in ('none', 'n', 'q'):
        console.print('[dim]Cancelled.[/dim]')
        return

    if choice == 'all':
        selected = detected
    else:
        try:
            indices = [int(x.strip()) - 1 for x in choice.split(',')]
            selected = [detected[i] for i in indices if 0 <= i < len(detected)]
        except ValueError:
            console.print('[red]Invalid selection — enter "all", "none", or numbers like 1,2[/red]')
            return

    console.print()
    for label, config_path, patch_fn in selected:
        _run_target(label, config_path, patch_fn, dry_run=False)

    if selected:
        console.print('[dim]\nRestart each AI tool for changes to take effect.[/dim]')


@cli.group(invoke_without_command=True)
@click.pass_context
def setup(ctx):
    """Register memgit with AI coding tools (MCP).

    Run bare for an interactive picker, or use a subcommand:

      memgit setup              # step-by-step: pick which tools to register
      memgit setup all          # auto-register every detected tool
      memgit setup claude-code  # register one specific tool

    Safe to re-run — only updates what's missing.
    """
    if ctx.invoked_subcommand is None:
        _setup_wizard()


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


def _cleanup_legacy_claude_code(dry_run: bool = False) -> None:
    """Drop the memgit entry from ~/.claude/settings.json if present.

    Releases before 0.1.5 registered there, but Claude Code only loads MCP
    servers from ~/.claude.json — the old entry is dead weight.
    """
    legacy = Path.home() / '.claude' / 'settings.json'
    if not legacy.exists():
        return
    try:
        data = _json.loads(legacy.read_text(encoding='utf-8'))
    except _json.JSONDecodeError:
        return
    servers = data.get('mcpServers')
    if not isinstance(servers, dict) or 'memgit' not in servers:
        return
    servers.pop('memgit')
    if not servers:
        data.pop('mcpServers', None)
    if not dry_run:
        _write_json_safe(legacy, data)
    console.print(
        f'[yellow]↻[/yellow] removed stale memgit entry from {legacy} '
        f'[dim](Claude Code ignores mcpServers there)[/dim]'
    )


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
    for label, config_path, patch_fn, detect_path in _all_targets():
        installed = (
            detect_path.exists()
            if detect_path is not None
            else config_path.exists() or config_path.parent.exists()
        )
        if not installed:
            skipped += 1
            continue
        _run_target(label, config_path, patch_fn, dry_run)
        registered += 1
    _cleanup_legacy_claude_code(dry_run)

    console.print(f'\n[dim]{registered} tool(s) processed, {skipped} not installed (skipped)[/dim]')
    if not dry_run and registered:
        console.print('[dim]Restart each AI tool for changes to take effect.[/dim]')


@setup.command('claude-code')
@click.option('--dry-run', is_flag=True)
def setup_claude_code(dry_run):
    """Register with Claude Code (~/.claude.json, user scope)."""
    path = Path.home() / '.claude.json'
    _run_target('Claude Code', path, _patch_mcp_servers, dry_run)
    _cleanup_legacy_claude_code(dry_run)


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


@setup.command('gemini-cli')
@click.option('--dry-run', is_flag=True)
def setup_gemini_cli(dry_run):
    """Register with Gemini CLI (~/.gemini/settings.json)."""
    path = Path.home() / '.gemini' / 'settings.json'
    _run_target('Gemini CLI', path, _patch_mcp_servers, dry_run)


#: substrings identifying a hook command as one of ours (any generation)
_MEMGIT_HOOK_SIGNS = ('resume --plain', 'hook prompt-recall', 'hook stop-guard', ' sync')


def _is_memgit_hook_entry(h: dict) -> bool:
    return any(
        'memgit' in inner.get('command', '') and
        any(sign in inner.get('command', '') for sign in _MEMGIT_HOOK_SIGNS)
        for inner in h.get('hooks', []) if isinstance(inner, dict)
    )


@setup.command('hooks')
@click.option('--remove', is_flag=True, help='Uninstall all memgit hooks')
@click.option('--no-recall', is_flag=True,
              help='Skip the per-prompt auto-recall hook (UserPromptSubmit)')
@click.option('--no-guard', is_flag=True,
              help='Skip the end-of-session capture guard (Stop)')
@click.option('--dry-run', is_flag=True, help='Show the change without writing')
def setup_hooks(remove, no_recall, no_guard, dry_run):
    """Install the Claude Code hooks that make memory automatic.

    Four hooks, one principle: what a hook enforces happens, what a tool
    description suggests mostly doesn't (measured: 6% voluntary engagement
    vs 100% hook delivery).

    \b
      SessionStart      inject `memgit resume` — last checkpoints, work in
                        flight, critical rules
      UserPromptSubmit  inject memories relevant to each prompt (BM25,
                        silent when nothing clears the relevance bar)
      Stop              capture guard — a substantive session ending with
                        zero memory writes gets ONE nudge to save durable
                        facts; plus async `memgit sync` to checkpoint
                        markdown memories

    Hooks live in ~/.claude/settings.json (unlike MCP servers, which live
    in ~/.claude.json).
    """
    import shlex
    settings_path = Path.home() / '.claude' / 'settings.json'
    base = ' '.join(shlex.quote(p) for p in _memgit_base_cmd())

    from .repo import default_store_candidates
    store = next((c for c in default_store_candidates() if (c / '.memgit').is_dir()),
                 Path.home() / '.claude' / 'memgit-store')

    if settings_path.exists():
        try:
            data = _json.loads(settings_path.read_text(encoding='utf-8'))
        except _json.JSONDecodeError:
            err.print(f'[red]{settings_path} is not valid JSON — fix it manually, then re-run.[/red]')
            sys.exit(1)
    else:
        data = {}

    hooks = data.setdefault('hooks', {})

    # `|| true` + stderr silenced everywhere: a broken store must never
    # block the user's session.
    plan: dict[str, list[dict]] = {
        'SessionStart': [
            {'type': 'command',
             'command': f'{base} resume --plain 2>/dev/null || true'},
        ],
        'UserPromptSubmit': [] if no_recall else [
            {'type': 'command',
             'command': f'{base} hook prompt-recall 2>/dev/null || true'},
        ],
        'Stop': ([] if no_guard else [
            {'type': 'command',
             'command': f'{base} hook stop-guard 2>/dev/null || true'},
        ]) + [
            {'type': 'command',
             'command': f'cd {shlex.quote(str(store))} && {base} sync 2>/dev/null || true',
             'async': True},
        ],
    }

    changed = []
    for event in ('SessionStart', 'UserPromptSubmit', 'Stop'):
        entries = hooks.setdefault(event, [])
        had = [h for h in entries if isinstance(h, dict) and _is_memgit_hook_entry(h)]
        entries[:] = [h for h in entries if h not in had]
        if not remove and plan[event]:
            entries.append({'hooks': plan[event]})
            changed.append(event)
        if not entries:
            hooks.pop(event, None)
    if not hooks:
        data.pop('hooks', None)

    if not dry_run:
        _write_json_safe(settings_path, data)

    suffix = ' [dim](dry run)[/dim]' if dry_run else ''
    if remove:
        console.print(f'[yellow]removed[/yellow] all memgit hooks from {settings_path}{suffix}')
        return
    console.print(f'[green]✓[/green] memgit hooks installed in {settings_path}{suffix}')
    for event in changed:
        for inner in plan[event]:
            tag = ' [dim](async)[/dim]' if inner.get('async') else ''
            console.print(f'  [cyan]{event}[/cyan]  [dim]{inner["command"]}[/dim]{tag}')
    console.print('[dim]Resume at session start, relevant memories per prompt, '
                  'capture guard + sync at stop.[/dim]')


@setup.command('print-config')
@click.argument('tool', default='generic',
                type=click.Choice(['claude-code', 'claude-desktop', 'cursor', 'windsurf', 'continue', 'gemini-cli', 'generic']))
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


if __name__ == '__main__':
    # Required for the `python -m memgit.cli` fallback used by _memgit_cmd();
    # without it the module imports and exits silently.
    cli()


# ── cloud (E2E-encrypted team sync — optional extra) ──────────────────────────

try:
    from .cloud.commands import cloud as _cloud_group
    cli.add_command(_cloud_group)
except Exception:
    # extras missing or broken — plain memgit must keep working untouched
    @cli.group()
    def cloud():
        """E2E-encrypted team sync — requires: pip install 'memgit[cloud]'"""

    @cloud.command('setup', help="Show how to enable cloud sync.")
    def _cloud_setup_hint():
        console.print(r"Install the cloud extra first:  [bold]pip install 'memgit\[cloud]'[/bold]")
