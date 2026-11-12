"""`memgit cloud …` — Click commands for E2E-encrypted team sync.

Heavy imports (pynacl, httpx) happen inside command bodies so plain memgit users
pay zero cost; a missing extra produces one clear install hint.
"""
from __future__ import annotations

import os
import sys
import time

import click
from rich.console import Console

console = Console()

APP_URL = os.environ.get('MEMGIT_CLOUD_APP', 'https://app.memgit.dev')


def _fail(msg: str):
    console.print(f'[red]✗[/red] {msg}')
    sys.exit(1)


def _require_extra():
    try:
        import httpx  # noqa: F401
        import nacl  # noqa: F401
    except ImportError:
        console.print("[red]✗[/red] cloud sync could not load pynacl or httpx — reinstall with: "
                      "pip install --upgrade --force-reinstall memgit")
        sys.exit(1)


def _repo():
    from ..repo import Repository
    repo = Repository.find()
    if repo is None:
        _fail('no memgit store found — run: memgit init')
    return repo


def _ctx():
    """(repo, CloudState, ApiClient) for the current store."""
    _require_extra()
    from .client import ApiClient, DEFAULT_API_URL
    from .state import CloudState
    repo = _repo()
    cstate = CloudState(repo.path)
    api_url = os.environ.get('MEMGIT_CLOUD_API') or cstate.creds.get('api_url') or DEFAULT_API_URL
    return repo, cstate, ApiClient(api_url, cstate)


def _passphrase(confirm: bool = False) -> str:
    p = click.prompt('Passphrase', hide_input=True, confirmation_prompt=confirm)
    if len(p) < 10:
        _fail('passphrase must be at least 10 characters — it protects all your encrypted memories')
    return p


def _private_key(cstate, api) -> bytes:
    """Decrypted user private key — from the 0600 cache, else passphrase re-derivation."""
    from . import crypto
    creds = cstate.creds
    if creds.get('private_key'):
        return crypto.b64u_decode(creds['private_key'])
    email = creds.get('email') or _fail('not logged in — run: memgit cloud login')
    salt = crypto.b64u_decode(api.get_salt(email))
    mk = crypto.master_key(_passphrase(), salt)
    me = api.me()
    priv = crypto.secretbox_open(me['enc_private_key'], crypto.enc_key(mk))
    return priv


def _team_key(cstate, api, team_id: str) -> bytes:
    from . import crypto
    cached = (cstate.creds.get('team_keys') or {}).get(team_id)
    if cached:
        return crypto.b64u_decode(cached)
    priv = _private_key(cstate, api)
    from nacl.public import PrivateKey
    pub = bytes(PrivateKey(priv).public_key)
    for t in api.my_teams():
        if t['team']['id'] == team_id:
            key = crypto.seal_open(t['wrapped_team_key'], pub, priv)
            if cstate.cache_keys_allowed():
                keys = cstate.creds.get('team_keys') or {}
                keys[team_id] = crypto.b64u(key)
                cstate.save_creds(team_keys=keys)
            return key
    _fail('you are not a member of this team')


def _my_teams(cstate, api) -> list[tuple[dict, bytes, str, str]]:
    """(team, key, name, role) for every team this account belongs to."""
    from . import crypto
    from nacl.public import PrivateKey
    priv = _private_key(cstate, api)
    pub = bytes(PrivateKey(priv).public_key)
    out = []
    for t in api.my_teams():
        key = crypto.seal_open(t['wrapped_team_key'], pub, priv)
        out.append((t['team'], key, crypto.decrypt_meta(key, t['team']['name_enc']),
                    t.get('role', '')))
    return out


def _team_ref(team: dict, name: str, teams) -> str:
    """How to name a team on the command line: its name, or its id prefix when
    another team of this account has the same name."""
    if sum(1 for _, _, n, _ in teams if n == name) > 1:
        return team['id'][:8]
    return name


def _team_by_name(cstate, api, name: str) -> tuple[dict, bytes]:
    """The team called `name`, or whose id starts with `name`.

    Two teams can share a name: every new account gets a team called
    "personal", so a teammate who signs up and then joins an invite holds two.
    Measured 2026-11-12: `link personal/memory` took the first match, linked the
    teammate to their own empty repo, and every later sync said "up-to-date"
    while none of the team's memories ever arrived. An ambiguous name is an
    error that lists the choices, never a guess.
    """
    from . import crypto
    teams = _my_teams(cstate, api)
    matches = [t for t in teams if t[2] == name]
    if not matches and len(name) >= 6:
        matches = [t for t in teams if t[0]['id'].startswith(name)]
    if len(matches) > 1:
        console.print(f'[red]✗[/red] {len(matches)} of your teams are named {name!r}; '
                      'name one by its id:')
        for team, _key, tname, role in matches:
            click.echo(f'  {team["id"][:8]}  {tname} ({role})')
        sys.exit(1)
    if not matches:
        _fail(f'no team named {name!r} — run: memgit cloud team list')
    team, key, _name, _role = matches[0]
    if cstate.cache_keys_allowed():
        keys = cstate.creds.get('team_keys') or {}
        keys[team['id']] = crypto.b64u(key)
        cstate.save_creds(team_keys=keys)
    return team, key


def _repo_choices(cstate, api, only_team_id: str | None = None) -> list[str]:
    """Every <team>/<repo> this account can link to, unambiguous on the command line."""
    from . import crypto
    teams = _my_teams(cstate, api)
    choices = []
    for team, key, tname, _role in teams:
        if only_team_id and team['id'] != only_team_id:
            continue
        ref = _team_ref(team, tname, teams)
        repos = api.team_detail(team['id'])['repos']
        choices += [f"{ref}/{crypto.decrypt_meta(key, r['name_enc'])}" for r in repos]
        if not repos:
            choices.append(f'{ref}/{DEFAULT_REPO}')
    return choices


def _linked(repo, cstate, api):
    """(SyncEngine, thread) for the linked repo, or fail with guidance."""
    from .sync import SyncEngine
    link = cstate.link()
    if link is None:
        _fail('this store is not linked — run: memgit cloud link <team>/<repo>')
    team_id, repo_id = link
    key = _team_key(cstate, api, team_id)
    return SyncEngine(repo, api, cstate, key, repo_id)


def _run(engine_call, label: str):
    from .client import CloudError, RefConflict
    try:
        return engine_call()
    except RefConflict:
        _fail(f'{label}: remote has new checkpoints — run: memgit cloud sync')
    except CloudError as e:
        _fail(f'{label}: {e}')


# ── group ────────────────────────────────────────────────────────────────────

DEFAULT_TEAM = 'personal'
DEFAULT_REPO = 'memory'


def _finish_setup(ctx, new_account: bool, invite: str | None = None) -> None:
    """Leave a store that has just signed up or logged in already syncing.

    Measured 2026-11-11: after `memgit cloud signup` nothing synced until three
    more commands were typed (team create, link, auto on), each of which a
    newcomer had to discover. A new account gets a personal team and one repo;
    a second machine links to the account's only repo; both turn autosync on.
    When the account has several repos the choice is the user's, so they are
    listed and nothing is linked.
    """
    from . import auto as autosync
    repo, cstate, api = _ctx()
    try:
        if invite:
            # A teammate joining by invite wants the TEAM's memory, not a new
            # personal team of their own (which is how a joining teammate ended
            # up linked to an empty repo, 2026-11-12).
            team_id = ctx.invoke(team_join, link=invite, link_store=False)
            choices = _repo_choices(cstate, api, only_team_id=team_id)
            if cstate.link():
                console.print("This store is already linked to another cloud repo. To sync it "
                              "with the team's memory instead (this shares every memory in "
                              "this store with the team):")
                for c in choices:
                    click.echo(f'  memgit cloud link {c}')
            else:
                if len(choices) == 1:
                    ctx.invoke(link, target=choices[0])
                else:
                    console.print('This team has more than one cloud repo. Link this store to one:')
                    for c in choices:
                        click.echo(f'  memgit cloud link {c}')
                    return
        if not cstate.link():
            target = None
            if new_account:
                ctx.invoke(team_create, name=DEFAULT_TEAM)
                target = f'{DEFAULT_TEAM}/{DEFAULT_REPO}'
            else:
                choices = _repo_choices(cstate, api)
                if not choices:
                    ctx.invoke(team_create, name=DEFAULT_TEAM)
                    target = f'{DEFAULT_TEAM}/{DEFAULT_REPO}'
                elif len(choices) == 1:
                    target = choices[0]
                else:
                    console.print('This account has more than one cloud repo. Link this store to one:')
                    for c in choices:
                        click.echo(f'  memgit cloud link {c}')
                    return
            ctx.invoke(link, target=target)
        _, cstate, _ = _ctx()
        if not cstate.creds.get('private_key'):
            console.print('[yellow]·[/yellow] key caching is off (MEMGIT_CLOUD_NO_CACHE), so sync '
                          'stays manual: memgit cloud sync')
            return
        if cstate.state.get('autosync') is None:
            cstate.save_state(autosync=True)
        if autosync.status(repo.path)['enabled']:
            autosync.trigger(repo.path)
            console.print('[green]✓[/green] this store now syncs on its own: every save goes up, and '
                          'other machines\' memories arrive at session start and while you work')
            if new_account:
                console.print('  On another machine:  [bold]pip install memgit && memgit init && '
                              'memgit cloud login[/bold]')
    except SystemExit:
        raise
    except Exception as e:  # the account exists and is logged in; say what is left to do
        console.print(f'[yellow]·[/yellow] could not finish setup ({type(e).__name__}: {e}). '
                      f'Run: memgit cloud link {DEFAULT_TEAM}/{DEFAULT_REPO} && memgit cloud auto on')


def trial_line(user: dict) -> str:
    """One factual sentence about the trial dates, from the server's user object.

    Since 2026-11-11 the server starts the trial at the second machine or the first
    teammate, so trial_ends_at is null on a new account; before that the account was
    created with an end date. Both are worded from what the server sent.
    """
    import datetime as dt

    def day(ts):
        return dt.datetime.fromtimestamp(ts).date()

    ends = user.get('trial_ends_at')
    if ends:
        verb = 'ended' if ends <= time.time() else 'runs until'
        return f'Trial {verb} {day(ends)}.'
    days = user.get('trial_days') or 14
    deadline = user.get('trial_deadline_at')
    line = (f'The {days}-day trial starts when a second machine connects to this account '
            'or a teammate joins your team')
    if deadline:
        line += f', and on {day(deadline)} if neither has happened by then'
    return line + '.'


class _CloudGroup(click.Group):
    """Every cloud command ends in one line naming the problem, never a traceback.

    Measured 2026-11-12: `memgit cloud signup` with an email that already had an
    account printed a 30-line Python traceback ending in "API error 409". A
    failed request is an expected outcome of a network command, so it is
    reported like one, with the next command to run where there is one.
    """

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except Exception as e:
            from .client import CloudError
            try:
                import httpx
                net = (httpx.TransportError,)
            except ImportError:
                net = ()
            if isinstance(e, CloudError):
                msg = str(e)
                if 'already exists' in msg and ctx.invoked_subcommand == 'signup':
                    msg += ' — log in instead: memgit cloud login'
                _fail(msg)
            if net and isinstance(e, net):
                api = os.environ.get('MEMGIT_CLOUD_API') or 'api.memgit.dev'
                _fail(f'could not reach {api} ({type(e).__name__}); check the connection '
                      'and run the command again.')
            raise


@click.group(cls=_CloudGroup)
def cloud():
    """E2E-encrypted team sync — app.memgit.dev"""


@cloud.command()
@click.option('--email', prompt=True)
@click.option('--no-setup', is_flag=True, help='Only create the account; do not create a team, link or turn autosync on.')
@click.option('--invite', default=None, metavar='LINK',
              help="Join a team from its invite link and sync this store with the team's memory.")
@click.pass_context
def signup(ctx, email, no_setup, invite):
    """Create a memgit cloud account (free trial; the server sets the length).

    The trial length is stamped by the server at signup and printed below, so this
    help text does not hardcode it. It said "30-day" while the deployed server granted
    14, which is a promise broken on day 15 for every reader of --help.
    """
    _require_extra()
    from . import crypto
    from nacl import utils
    repo, cstate, api = _ctx()
    console.print('[dim]Your passphrase encrypts everything client-side. '
                  'It cannot be recovered — losing it means losing cloud data.[/dim]')
    passphrase = _passphrase(confirm=True)
    salt = utils.random(16)
    mk = crypto.master_key(passphrase, salt)
    keypair = crypto.new_keypair()
    body = api.signup(
        email=email,
        auth_key=crypto.auth_key(mk),
        kdf_salt=crypto.b64u(salt),
        public_key=crypto.b64u(bytes(keypair.public_key)),
        enc_private_key=crypto.secretbox(bytes(keypair), crypto.enc_key(mk)),
    )
    creds = {'api_url': api.api_url, 'email': email, 'user_id': body['user']['id'],
             'access': api.access, 'refresh': api.refresh}
    if cstate.cache_keys_allowed():
        creds['private_key'] = crypto.b64u(bytes(keypair))
    cstate.save_creds(**creds)
    console.print(f'[green]✓[/green] account created. {trial_line(body["user"])}')
    if invite and no_setup:
        ctx.invoke(team_join, link=invite, link_store=False)
    elif not no_setup:
        _finish_setup(ctx, new_account=True, invite=invite)


@cloud.command()
@click.option('--email', prompt=True)
@click.option('--no-setup', is_flag=True, help='Only log in; do not link this store or turn autosync on.')
@click.option('--invite', default=None, metavar='LINK',
              help="Join a team from its invite link and sync this store with the team's memory.")
@click.pass_context
def login(ctx, email, no_setup, invite):
    """Log in and unlock your keys."""
    _require_extra()
    from . import crypto
    repo, cstate, api = _ctx()
    salt = crypto.b64u_decode(api.get_salt(email))
    mk = crypto.master_key(_passphrase(), salt)
    from .client import CloudError
    try:
        body = api.login(email, crypto.auth_key(mk))
    except CloudError as e:
        _fail(str(e))
    priv = crypto.secretbox_open(body['enc_private_key'], crypto.enc_key(mk))
    creds = {'api_url': api.api_url, 'email': email, 'user_id': body['user']['id'],
             'access': api.access, 'refresh': api.refresh}
    if cstate.cache_keys_allowed():
        creds['private_key'] = crypto.b64u(priv)
    cstate.save_creds(**creds)
    console.print(f'[green]✓[/green] logged in as {email}')
    if invite and no_setup:
        ctx.invoke(team_join, link=invite, link_store=False)
    elif not no_setup:
        _finish_setup(ctx, new_account=False, invite=invite)


@cloud.command()
def logout():
    """Forget tokens and cached keys on this machine."""
    repo = _repo()
    from .state import CloudState
    CloudState(repo.path).clear_creds()
    console.print('[green]✓[/green] logged out')


@cloud.command()
def whoami():
    """Show account, plan, and link status."""
    repo, cstate, api = _ctx()
    from .client import CloudError
    try:
        me = api.me()
    except CloudError as e:
        _fail(str(e))
    if me.get('plan') == 'trial':
        console.print(f'[bold]{me["email"]}[/bold] · plan: trial. {trial_line(me)}')
    elif me.get('trial_ends_at'):
        import datetime as dt
        trial = dt.datetime.fromtimestamp(me['trial_ends_at']).date()
        console.print(f'[bold]{me["email"]}[/bold] · plan: {me["plan"]} (until {trial})')
    else:
        console.print(f'[bold]{me["email"]}[/bold] · plan: {me["plan"]}')
    link = cstate.link()
    if link:
        console.print(f'linked: team={link[0][:8]}… repo={link[1].split(".",1)[1][:8]}…')
    else:
        console.print('[dim]not linked — memgit cloud link <team>/<repo>[/dim]')


@cloud.group()
def team():
    """Manage teams."""


@team.command('create')
@click.argument('name')
def team_create(name):
    """Create a team (you become owner; team key never leaves your machine unencrypted)."""
    _require_extra()
    from . import crypto
    from nacl import utils
    from nacl.public import PrivateKey
    repo, cstate, api = _ctx()
    priv = _private_key(cstate, api)
    pub = bytes(PrivateKey(priv).public_key)
    key = utils.random(32)
    t = _run(lambda: api.create_team(crypto.encrypt_meta(key, name), crypto.seal(key, pub)),
             'create team')
    if cstate.cache_keys_allowed():
        keys = cstate.creds.get('team_keys') or {}
        keys[t['id']] = crypto.b64u(key)
        cstate.save_creds(team_keys=keys)
    console.print(f'[green]✓[/green] team [bold]{name}[/bold] created ({t["id"][:8]}…)')


@team.command('list')
def team_list():
    """List your teams (names decrypted locally)."""
    _require_extra()
    from . import crypto
    from nacl.public import PrivateKey
    repo, cstate, api = _ctx()
    priv = _private_key(cstate, api)
    pub = bytes(PrivateKey(priv).public_key)
    teams = _run(api.my_teams, 'list teams')
    if not teams:
        console.print('[dim]no teams yet — memgit cloud team create <name>[/dim]')
        return
    for t in teams:
        key = crypto.seal_open(t['wrapped_team_key'], pub, priv)
        name = crypto.decrypt_meta(key, t['team']['name_enc'])
        console.print(f'  [bold]{name}[/bold]  ({t["team"]["id"][:8]}…, {t["role"]})')


@team.command('invite')
@click.argument('name')
@click.option('--uses', default=10, show_default=True)
@click.option('--days', default=14, show_default=True)
def team_invite(name, uses, days):
    """Create an invite link. The secret stays in the URL fragment — the server never sees it."""
    _require_extra()
    from . import crypto
    repo, cstate, api = _ctx()
    t, key = _team_by_name(cstate, api, name)
    secret, box, verifier = crypto.invite_material(key)
    inv = _run(lambda: api.create_invite(t['id'], box, verifier, uses, days), 'create invite')
    url = f'{APP_URL}/join#{inv["invite_id"]}.{secret}'
    console.print(f'[green]✓[/green] invite (valid {days}d, {uses} uses):')
    # plain echo, not rich: links must never be line-wrapped (breaks copy-paste)
    click.echo(url)
    click.echo(f'MEMGIT_INVITE={inv["invite_id"]}.{secret}')
    console.print('Send your teammate this, to run on their machine:')
    click.echo(f"  pip install memgit && memgit init && memgit cloud signup --invite '{url}'")
    console.print("[dim]  (already have an account: memgit cloud login --invite '<link>')[/dim]")


@team.command('join')
@click.argument('link')
@click.option('--no-link', 'link_store', flag_value=False, default=True,
              help="Join only; do not link this store to the team's repo.")
@click.pass_context
def team_join(ctx, link, link_store):
    """Join a team from an invite link (or its fragment).

    A store that is not linked yet is linked to the team's repo straight away.
    A store already linked elsewhere is left alone: linking shares the whole
    store with the team, so that is the user's call, and the exact command is
    printed.
    """
    _require_extra()
    from . import crypto
    from nacl.public import PrivateKey
    repo, cstate, api = _ctx()
    frag = link.split('#', 1)[-1]
    if '.' not in frag:
        _fail('invalid invite link')
    # invite_id itself contains a dot ({team_id}.{uuid}); the secret is base64url (dot-free)
    invite_id, secret = frag.rsplit('.', 1)
    verifier = crypto.invite_verifier(secret)
    preview = _run(lambda: api.preview_invite(invite_id, verifier), 'read invite')
    key, verifier = crypto.invite_open(secret, preview['box'])
    name = crypto.decrypt_meta(key, preview['team_name_enc'])
    priv = _private_key(cstate, api)
    pub = bytes(PrivateKey(priv).public_key)
    _run(lambda: api.accept_invite(invite_id, verifier, crypto.seal(key, pub)), 'join team')
    if cstate.cache_keys_allowed():
        keys = cstate.creds.get('team_keys') or {}
        keys[preview['team_id']] = crypto.b64u(key)
        cstate.save_creds(team_keys=keys)
    console.print(f'[green]✓[/green] joined team [bold]{name}[/bold]')
    if link_store:
        choices = _repo_choices(cstate, api, only_team_id=preview['team_id'])
        if not cstate.link() and len(choices) == 1:
            ctx.invoke(globals()['link'], target=choices[0])
        else:
            console.print("To sync this store with the team's memory, link it (this shares "
                          "every memory in this store with the team):")
            for c in choices:
                click.echo(f'  memgit cloud link {c}')
    return preview['team_id']


@cloud.command()
@click.argument('target')
def link(target):
    """Link this store to <team>/<repo> (repo is created if it doesn't exist)."""
    _require_extra()
    from . import crypto
    repo, cstate, api = _ctx()
    if '/' not in target:
        _fail('usage: memgit cloud link <team-name>/<repo-name>')
    team_name, repo_name = target.split('/', 1)
    t, key = _team_by_name(cstate, api, team_name)
    detail = _run(lambda: api.team_detail(t['id']), 'read team')
    repo_doc = None
    for r in detail['repos']:
        if crypto.decrypt_meta(key, r['name_enc']) == repo_name:
            repo_doc = r
            break
    if repo_doc is None:
        repo_doc = _run(lambda: api.create_repo(t['id'], crypto.encrypt_meta(key, repo_name)),
                        'create repo')
        console.print(f'[green]✓[/green] created cloud repo [bold]{repo_name}[/bold]')
    cstate.save_state(team_id=t['id'], repo_id=repo_doc['id'],
                      team_name=team_name, repo_name=repo_name)
    console.print(f'[green]✓[/green] linked to [bold]{team_name}/{repo_name}[/bold] '
                  f'— sync once with memgit cloud sync, or leave it to memgit cloud auto on')


def _report(res, direction):
    icons = {'up-to-date': '=', 'pushed': '↑', 'created': '↑', 'fast-forward': '↓', 'merged': '⇵'}
    bits = []
    if res.pushed:
        bits.append(f'{res.pushed} objects up')
    if res.fetched:
        bits.append(f'{res.fetched} objects down')
    if res.conflicts:
        bits.append(f'{len(res.conflicts)} conflicts auto-resolved (newest wins)')
    head = f' @ {res.head[:8]}' if res.head else ''
    detail = f' ({", ".join(bits)})' if bits else ''
    console.print(f'[green]{icons.get(res.action, "·")}[/green] {direction}: {res.action}{detail}{head}')


def _guard_uncommitted(repo, thread: str, allow: bool) -> None:
    """Refuse to transmit while staged memories are not in a checkpoint.

    Sync ships CHECKPOINTS. `memgit add` stages a memory but does not create
    one, so pushing straight after `add` uploads nothing of the user's — and
    said "created (2 objects up)" while doing it, with the receiving machine
    reporting a clean, empty, fsck-OK store (measured 2026-09-06). Nothing in
    that sequence errored, which is why it reads as "sync is broken" rather
    than "you have not committed". An error naming the fix is the whole point;
    `--allow-uncommitted` is there for anyone who means it.
    """
    if allow:
        return
    pending = repo.uncommitted_slugs(thread)
    if not pending:
        return
    shown = ', '.join(pending[:5]) + (f' and {len(pending) - 5} more' if len(pending) > 5 else '')
    console.print(
        f'[red]✗[/red] {len(pending)} memor{"y is" if len(pending) == 1 else "ies are"} '
        f'not committed, and sync only ships committed memory: [bold]{shown}[/bold]')
    console.print('  [dim]commit them first:  memgit commit -m "what changed"[/dim]')
    console.print('  [dim]or push the committed state anyway:  --allow-uncommitted[/dim]')
    sys.exit(1)


@cloud.command()
@click.option('--thread', default=None, help='thread to push (default: current)')
@click.option('--allow-uncommitted', is_flag=True,
              help='Push committed state even though staged memories would not be sent')
def push(thread, allow_uncommitted):
    """Encrypt and upload local checkpoints, then advance the remote ref."""
    repo, cstate, api = _ctx()
    engine = _linked(repo, cstate, api)
    th = thread or repo.current_thread()
    _guard_uncommitted(repo, th, allow_uncommitted)
    res = _run(lambda: engine.push(th), 'push')
    _report(res, f'push {th}')


@cloud.command()
@click.option('--thread', default=None, help='thread to pull (default: current)')
def pull(thread):
    """Fetch, verify, and integrate remote checkpoints (fast-forward or merge)."""
    repo, cstate, api = _ctx()
    engine = _linked(repo, cstate, api)
    th = thread or repo.current_thread()
    res = _run(lambda: engine.pull(th), 'pull')
    _report(res, f'pull {th}')


@cloud.command('sync')
@click.option('--thread', default=None, help='thread to sync (default: current)')
@click.option('--allow-uncommitted', is_flag=True,
              help='Sync committed state even though staged memories would not be sent')
def cloud_sync(thread, allow_uncommitted):
    """Pull then push — the everyday command."""
    repo, cstate, api = _ctx()
    engine = _linked(repo, cstate, api)
    th = thread or repo.current_thread()
    # Guarded before the pull as well as the push: sync is the command users
    # reach for, and finding out after a merge that half of it was a no-op is
    # worse than being told up front which memories are not committed yet.
    _guard_uncommitted(repo, th, allow_uncommitted)
    pulled, pushed = _run(lambda: engine.sync(th), 'sync')
    _report(pulled, f'pull {th}')
    _report(pushed, f'push {th}')


@cloud.command('auto')
@click.argument('mode', type=click.Choice(['on', 'off', 'status']), default='status')
def auto(mode):
    """Sync automatically after every save and at session start."""
    from . import auto as autosync
    repo = _repo()
    from .state import CloudState
    cstate = CloudState(repo.path)
    if mode != 'status':
        cstate.save_state(autosync=(mode == 'on'))
    st = autosync.status(repo.path)
    if st['enabled']:
        console.print('[green]✓[/green] autosync on: every save is pushed in the background, '
                      'and each session start pulls other machines\' memories')
        if mode == 'on':
            autosync.trigger(repo.path)
    else:
        console.print('[yellow]·[/yellow] autosync off: ' + '; '.join(st['reasons']))
    last = st['last']
    if last:
        if last.get('ok'):
            console.print(f'  [dim]last run {last["at"]}: pull {last["pull"]}, push {last["push"]} '
                          f'@ {last.get("head", "")}[/dim]')
        else:
            console.print(f'  [red]last run {last.get("at", "?")} failed:[/red] {last.get("error")}')


@cloud.command()
@click.option('--interval', default=60, show_default=True, help='seconds between syncs')
@click.option('--once', is_flag=True, help='sync once and exit (for a systemd timer)')
@click.option('--export', type=click.Path(dir_okay=False), default=None,
              help='also write the session digest to this file whenever new memory arrives '
                   '(for agents that load context files, such as Hermes .hermes.md)')
def watch(interval, once, export):
    """Keep a server's store in sync: pull and push on a loop, one JSON line per run.

    For machines that run an agent but no interactive sessions, such as a Mac
    mini or a VM. Run it under systemd or launchd; it needs a prior
    `memgit cloud login` so the key is cached.
    """
    _require_extra()
    from . import auto as autosync
    repo = _repo()
    st = autosync.status(repo.path)
    missing = [r for r in st['reasons'] if not r.startswith('autosync is off')]
    if missing:
        _fail('; '.join(missing))
    autosync.watch(repo.path, interval, once, export)
