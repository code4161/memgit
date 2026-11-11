"""The one line that offers memgit cloud, decided from local state only.

Nothing here opens a connection or sends anything anywhere. Whether to show the
line is decided from three facts the machine already has: how many memories the
store holds, whether this store has been opened on a different machine, and
whether the user just ran an export or a backup. Each of those is a moment when
having the memory on another machine is the thing the user is already doing by
hand, which is when an offer reads as help rather than as an advert.

Each trigger shows at most once per store, and the state that remembers this is
a small JSON file inside the store's .memgit directory. The line never shows
when the store is logged in to memgit cloud or linked to a repo, when
MEMGIT_NO_SYNC_HINT=1, or after memgit cloud hint off.

The wording states a fact and the one command. It never counts down, never
suggests data is at risk, and never tells the user what they must do.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
from pathlib import Path
from typing import Optional

STATE_FILE = 'sync-hint.json'

#: Memory counts at which the store has grown into something worth having on
#: every machine. 50 is a store in real use over several sessions, well past
#: the 20 at which the backup warning starts; 250 is a store nobody would
#: rebuild by hand. Each shows once.
COUNT_THRESHOLDS = (50, 250)

OFFER = 'memgit cloud signup'
TERMS = '14 days free, no card'


def _off_by_env() -> bool:
    return os.environ.get('MEMGIT_NO_SYNC_HINT', '') in ('1', 'true', 'yes')


def machine_fingerprint() -> str:
    """A hash of this machine's hostname, never the hostname itself.

    The domain part is dropped and case folded, because macOS reports the same
    machine as name.local on one network and name on another.
    """
    try:
        host = socket.gethostname() or ''
    except Exception:
        host = ''
    host = host.strip().lower().split('.')[0]
    return hashlib.sha256(f'memgit-machine:{host}'.encode()).hexdigest()[:16]


def _path(memgit_dir: Path) -> Path:
    return Path(memgit_dir) / STATE_FILE


def read_state(memgit_dir: Path) -> dict:
    try:
        data = json.loads(_path(memgit_dir).read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_state(memgit_dir: Path, data: dict) -> None:
    path = _path(memgit_dir)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(path)


def set_off(memgit_dir: Path, off: bool) -> None:
    data = read_state(memgit_dir)
    data['off'] = bool(off)
    write_state(memgit_dir, data)


def cloud_connected(memgit_dir: Path) -> bool:
    """True when the store is logged in to memgit cloud or linked to a repo."""
    try:
        from .cloud.state import CloudState
        cs = CloudState(Path(memgit_dir))
        creds = cs.creds
        if creds.get('email') or creds.get('access') or creds.get('refresh'):
            return True
        return cs.link() is not None
    except Exception:
        # If the cloud state cannot be read, say nothing: an offer to a user
        # who may already be signed up is worse than no offer.
        return True


def suppressed(memgit_dir: Path) -> bool:
    if _off_by_env():
        return True
    if read_state(memgit_dir).get('off'):
        return True
    return cloud_connected(memgit_dir)


def _plural(n: int) -> str:
    return f'{n} memory' if n == 1 else f'{n} memories'


def _line(key: str, count: int) -> str:
    if key == 'machine':
        return (f'This store has been opened on two machines. {OFFER} keeps '
                f'each machine\'s memories in step on its own ({TERMS}).')
    if key == 'export':
        return (f'To have these {_plural(count)} on your other machines without '
                f'copying files: {OFFER} ({TERMS}).')
    return (f'{_plural(count)} are on this machine. {OFFER} puts them on your '
            f'other machines too ({TERMS}).')


def _record_machine(memgit_dir: Path, data: dict) -> bool:
    """Record this machine the first time; True when the store has moved."""
    fp = machine_fingerprint()
    first = data.get('machine')
    if not first:
        data['machine'] = fp
        try:
            write_state(memgit_dir, data)
        except Exception:
            pass
        return False
    return first != fp


def pending(memgit_dir: Path, count: int, event: Optional[str] = None
            ) -> Optional[tuple[str, str]]:
    """The hint due now as (key, line), or None. Does not mark it shown.

    The caller marks it with mark_shown once the line has actually been
    printed, so a digest cut at its budget never uses up the one showing.
    At most one line is offered at a time; the others wait for a later
    session. Never raises.
    """
    try:
        memgit_dir = Path(memgit_dir)
        data = read_state(memgit_dir)
        moved = _record_machine(memgit_dir, data)
        if suppressed(memgit_dir):
            return None
        shown = set(data.get('shown') or [])
        if event in ('export', 'backup') and 'export' not in shown:
            return 'export', _line('export', count)
        if moved and 'machine' not in shown:
            return 'machine', _line('machine', count)
        for n in sorted(COUNT_THRESHOLDS, reverse=True):
            key = f'count-{n}'
            if count >= n and key not in shown:
                return key, _line(key, count)
        return None
    except Exception:
        return None


def mark_shown(memgit_dir: Path, key: str) -> None:
    """Remember that a hint was shown. A count hint also retires every lower
    threshold, so a store that is already large is offered once, not twice."""
    try:
        memgit_dir = Path(memgit_dir)
        data = read_state(memgit_dir)
        shown = set(data.get('shown') or [])
        shown.add(key)
        if key.startswith('count-'):
            n = int(key.split('-', 1)[1])
            shown.update(f'count-{t}' for t in COUNT_THRESHOLDS if t <= n)
        data['shown'] = sorted(shown)
        write_state(memgit_dir, data)
    except Exception:
        pass


def show_for_event(memgit_dir: Path, count: int, event: str) -> Optional[str]:
    """For a command's own output (export, backup): the line, already marked."""
    hint = pending(memgit_dir, count, event)
    if not hint:
        return None
    mark_shown(memgit_dir, hint[0])
    return hint[1]
