"""`memgit cloud …` — Click commands for E2E-encrypted team sync.

Heavy imports (pynacl, httpx) happen inside command bodies so plain memgit users
pay zero cost; a missing extra produces one clear install hint.
"""
from __future__ import annotations

import os
import sys

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
        console.print(r"[red]✗[/red] cloud sync needs extra dependencies — install with: pip install 'memgit\[cloud]'")
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


def _team_by_name(cstate, api, name: str) -> tuple[dict, bytes]:
    from . import crypto
    priv = _private_key(cstate, api)
    from nacl.public import PrivateKey
    pub = bytes(PrivateKey(priv).public_key)
    for t in api.my_teams():
        key = crypto.seal_open(t['wrapped_team_key'], pub, priv)
        if crypto.decrypt_meta(key, t['team']['name_enc']) == name:
            if cstate.cache_keys_allowed():
                keys = cstate.creds.get('team_keys') or {}
                keys[t['team']['id']] = crypto.b64u(key)
                cstate.save_creds(team_keys=keys)
            return t['team'], key
    _fail(f'no team named {name!r} — run: memgit cloud team list')


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

@click.group()
def cloud():
    """E2E-encrypted team sync — app.memgit.dev"""


@cloud.command()
@click.option('--email', prompt=True)
def signup(email):
    """Create a memgit cloud account (30-day free trial)."""
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
    console.print(f'[green]✓[/green] account created — trial until '
                  f'{__import__("datetime").datetime.fromtimestamp(body["user"]["trial_ends_at"]).date()}')


@cloud.command()
@click.option('--email', prompt=True)
def login(email):
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
    import datetime as dt
    trial = dt.datetime.fromtimestamp(me['trial_ends_at']).date()
    console.print(f'[bold]{me["email"]}[/bold] · plan: {me["plan"]} (until {trial})')
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
    console.print(f'[green]✓[/green] invite (valid {days}d, {uses} uses):')
    # plain echo, not rich: links must never be line-wrapped (breaks copy-paste)
    click.echo(f'{APP_URL}/join#{inv["invite_id"]}.{secret}')
    click.echo(f'MEMGIT_INVITE={inv["invite_id"]}.{secret}')


@team.command('join')
@click.argument('link')
def team_join(link):
    """Join a team from an invite link (or its fragment)."""
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
                  f'— now: memgit cloud sync')


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


@cloud.command()
@click.option('--thread', default=None, help='thread to push (default: current)')
def push(thread):
    """Encrypt and upload local checkpoints, then advance the remote ref."""
    repo, cstate, api = _ctx()
    engine = _linked(repo, cstate, api)
    th = thread or repo.current_thread()
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
def cloud_sync(thread):
    """Pull then push — the everyday command."""
    repo, cstate, api = _ctx()
    engine = _linked(repo, cstate, api)
    th = thread or repo.current_thread()
    pulled, pushed = _run(lambda: engine.sync(th), 'sync')
    _report(pulled, f'pull {th}')
    _report(pushed, f'push {th}')
