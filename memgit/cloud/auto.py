"""Automatic cloud sync: every checkpoint goes out without anyone typing a command.

`memgit cloud auto on` records autosync in state.json. From then on each commit
(every MCP save_memory commits) starts one detached `memgit cloud sync` and
returns immediately, so a save never waits on the network. A lock keeps runs
from overlapping; a save that lands while a run is in flight sets a dirty flag
and the running worker goes round once more, so nothing committed is left
behind. Session start triggers the same worker, which is how other machines'
memories arrive. Servers with no sessions run `memgit cloud watch` instead.

The worker reads the 0600 key cache that `memgit cloud login` writes. With no
cached key there is nothing it can decrypt or encrypt without a passphrase, so
autosync stays off rather than prompting from the background.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Set in the worker's environment so the commits a pull merge makes cannot
# start another worker. Users can also set it to pause autosync for one shell.
DISABLE_ENV = 'MEMGIT_NO_AUTOSYNC'
STALE_LOCK_SECS = 600

# When a read should fetch. A commit always syncs; a read (search, recall, an
# MCP lookup) starts a background sync only when the last one is older than
# this, so a long session still receives what other machines saved without a
# request per query. MEMGIT_AUTOSYNC_MAX_AGE overrides it in seconds; 0 turns
# read-triggered fetching off.
FETCH_MAX_AGE_SECS = 300
# After a failed run (plan lapsed, offline, key refused) reads wait this long
# before asking again. Asking on every read is how a refusal becomes a flood.
FAILURE_BACKOFF_SECS = 900
# Session start waits at most this long for the fetch, so the digest carries
# other machines' memories when the network is quick and is never held up when
# it is not. MEMGIT_AUTOSYNC_WAIT overrides it in seconds; 0 never waits.
SESSION_WAIT_SECS = 3.0


def _cloud_dir(memgit_dir: Path) -> Path:
    return Path(memgit_dir) / 'cloud'


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def status(memgit_dir: Path) -> dict:
    """What autosync would do right now, and why not when it would not."""
    d = _cloud_dir(memgit_dir)
    state = _read_json(d / 'state.json')
    creds = _read_json(d / 'credentials.json')
    reasons = []
    if not state.get('autosync'):
        reasons.append('autosync is off (memgit cloud auto on)')
    if not (state.get('team_id') and state.get('repo_id')):
        reasons.append('store is not linked (memgit cloud link <team>/<repo>)')
    if not creds.get('private_key'):
        reasons.append('no cached key on this machine (memgit cloud login)')
    last = _read_json(d / 'autosync-last.json')
    return {'enabled': not reasons, 'reasons': reasons, 'last': last}


def enabled(memgit_dir: Path) -> bool:
    if os.environ.get(DISABLE_ENV, '') in ('1', 'true', 'yes'):
        return False
    return status(memgit_dir)['enabled']


def trigger(memgit_dir: Path) -> bool:
    """Start a background sync if autosync is on. Never raises, never blocks."""
    try:
        if not enabled(memgit_dir):
            return False
        d = _cloud_dir(memgit_dir)
        lock = d / 'autosync.lock'
        if lock.exists() and time.time() - lock.stat().st_mtime < STALE_LOCK_SECS:
            # A worker is running; it re-checks this flag before it exits.
            (d / 'autosync.dirty').touch()
            return True
        env = dict(os.environ, **{DISABLE_ENV: '1', 'MEMGIT_STORE': str(Path(memgit_dir).parent)})
        log = open(d / 'autosync.log', 'ab')
        subprocess.Popen(
            [sys.executable, '-m', 'memgit.cloud.auto', str(memgit_dir)],
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=env,
            start_new_session=True, close_fds=True,
        )
        return True
    except Exception:
        return False


def _env_secs(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(name, '')))
    except ValueError:
        return default


def _age_secs(last: dict) -> float | None:
    """Seconds since the last recorded run, or None when there has been none."""
    try:
        at = datetime.fromisoformat(last['at'])
    except (KeyError, TypeError, ValueError):
        return None
    return (datetime.now(timezone.utc) - at).total_seconds()


def due(memgit_dir: Path) -> bool:
    """Whether a read should start a fetch: never synced, or the last run is old.

    A failed run is retried after FAILURE_BACKOFF_SECS, not FETCH_MAX_AGE_SECS.
    """
    max_age = _env_secs('MEMGIT_AUTOSYNC_MAX_AGE', FETCH_MAX_AGE_SECS)
    if max_age <= 0:
        return False
    last = _read_json(_cloud_dir(memgit_dir) / 'autosync-last.json')
    age = _age_secs(last)
    if age is None:
        return True
    if last.get('ok') is False:
        return age >= max(max_age, FAILURE_BACKOFF_SECS)
    return age >= max_age


def trigger_if_stale(memgit_dir: Path) -> bool:
    """Start a background fetch from a read path, when one is due. Never raises."""
    try:
        if not enabled(memgit_dir) or not due(memgit_dir):
            return False
        return trigger(memgit_dir)
    except Exception:
        return False


def fetch_for_session(memgit_dir: Path, wait: float | None = None) -> bool:
    """Session start: start a sync and give it a moment to land. Never raises.

    Returns True when a run finished inside the wait, so the caller's digest
    was built from a store that already holds the other machines' memories.
    """
    try:
        d = _cloud_dir(memgit_dir)
        before = _read_json(d / 'autosync-last.json').get('at')
        if not trigger(memgit_dir):
            return False
        wait = _env_secs('MEMGIT_AUTOSYNC_WAIT', SESSION_WAIT_SECS) if wait is None else wait
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            time.sleep(0.1)
            if _read_json(d / 'autosync-last.json').get('at') != before \
                    and not (d / 'autosync.lock').exists():
                return True
        return False
    except Exception:
        return False


def sync_once(memgit_dir: Path) -> dict:
    """One pull-then-push of the current thread. Returns the outcome it recorded."""
    from ..repo import Repository
    from .client import ApiClient, DEFAULT_API_URL, CloudError
    from .state import CloudState
    from .sync import SyncEngine
    from . import crypto
    from nacl.public import PrivateKey

    out = {'at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    from .client import RefConflict
    try:
        repo = Repository(Path(memgit_dir))
        cstate = CloudState(repo.path)
        api_url = os.environ.get('MEMGIT_CLOUD_API') or cstate.creds.get('api_url') or DEFAULT_API_URL
        api = ApiClient(api_url, cstate)
        team_id, repo_id = cstate.link()
        key_b64 = (cstate.creds.get('team_keys') or {}).get(team_id)
        if key_b64:
            key = crypto.b64u_decode(key_b64)
        else:
            priv = crypto.b64u_decode(cstate.creds['private_key'])
            pub = bytes(PrivateKey(priv).public_key)
            key = next(crypto.seal_open(t['wrapped_team_key'], pub, priv)
                       for t in api.my_teams() if t['team']['id'] == team_id)
        thread = repo.current_thread()
        out['thread'] = thread
        for attempt in range(3):
            try:
                pulled, pushed = SyncEngine(repo, api, cstate, key, repo_id).sync(thread)
                break
            except RefConflict:
                # Another machine pushed between our pull and push; pull again.
                if attempt == 2:
                    raise
        out.update(ok=True, pull=pulled.action, push=pushed.action,
                   down=pulled.fetched, up=pushed.pushed,
                   head=(pushed.head or pulled.head or '')[:12])
    except CloudError as e:
        # A lapsed plan answers 402: on push at once, on pull after the grace days. Record it so
        # `memgit cloud auto status` can say why memories stopped going out.
        out.update(ok=False, error=str(e))
    except StopIteration:
        out.update(ok=False, error='this account is no longer a member of the linked team')
    except Exception as e:
        # Offline, DNS, a key that no longer opens the team key. An unrecorded
        # failure leaves the last success on show and reads keep retrying.
        out.update(ok=False, error=f'{type(e).__name__}: {e}')
    (_cloud_dir(memgit_dir) / 'autosync-last.json').write_text(json.dumps(out))
    return out


def _worker(memgit_dir: Path) -> None:
    d = _cloud_dir(memgit_dir)
    lock = d / 'autosync.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if time.time() - lock.stat().st_mtime < STALE_LOCK_SECS:
            (d / 'autosync.dirty').touch()
            return
        lock.unlink(missing_ok=True)
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    try:
        for _ in range(5):
            (d / 'autosync.dirty').unlink(missing_ok=True)
            print(json.dumps(sync_once(memgit_dir)), flush=True)
            if not (d / 'autosync.dirty').exists():
                break
    finally:
        lock.unlink(missing_ok=True)


def export_digest(memgit_dir: Path, path: Path) -> None:
    """Write the session-start digest to a file an agent loads as context.

    For agents that read context files rather than calling MCP tools (Hermes
    reads .hermes.md or AGENTS.md at session start). Written atomically so an
    agent starting mid-write never reads half a file.
    """
    from ..cli import _format_resume_plain
    from ..repo import Repository
    ctx = Repository(Path(memgit_dir)).resume_context(checkpoints=5, recent=10, project=None)
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(_format_resume_plain(ctx) + '\n')
    tmp.replace(path)


def watch(memgit_dir: Path, interval: int, once: bool = False, export: Path | None = None) -> None:
    """Foreground loop for servers: sync every interval seconds, forever."""
    os.environ[DISABLE_ENV] = '1'  # the loop is the sync; commits must not spawn workers
    exported_head = None
    while True:
        try:
            out = sync_once(memgit_dir)
            if export and out.get('ok') and (out.get('head') != exported_head or not Path(export).exists()):
                export_digest(memgit_dir, Path(export))
                exported_head = out.get('head')
                out['exported'] = str(export)
        except Exception as e:  # keep a long-running service alive across blips
            out = {'ok': False, 'error': f'{type(e).__name__}: {e}'}
        print(json.dumps(out), flush=True)
        if once:
            return
        time.sleep(interval)


if __name__ == '__main__':
    _worker(Path(sys.argv[1]))
