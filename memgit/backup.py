"""Durability that does not wait for a human.

memgit's operating premise is that the AI is the operator. Backup was the one
place that premise broke: off-machine safety required someone to remember to
run `memgit git init --remote <url>` and then keep pushing. On a store audited
at 1,734 memories across five weeks of daily use, it had never been run once —
the entire memory set existed on a single disk with no copy anywhere.

A maintenance task that needs a human command is a maintenance task that will
not happen. So this module makes durability automatic, with the safety boundary
drawn at *network egress* rather than at *effort*:

  * LOCAL destinations (a cloud-synced folder the user already has, an external
    volume) are used AUTOMATICALLY. memgit copies files; it opens no
    connection and signs up for no service. Whatever sync client the user
    already trusts does the rest.
  * A GIT REMOTE is pushed to automatically ONLY when the user has already
    configured one. memgit never invents a remote, never creates a repository,
    and never sends memories to a host the user has not already chosen.

That distinction matters because memories are not neutral text: a prior audit
on this very store found client credentials among them. Convenience is not a
reason to publish someone's private notes to a service they never picked.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

#: Backup state lives beside the store, not inside the object DB — it is
#: operational metadata, not memory, and must not churn the index.
_STATE = 'backup.json'

#: A backup older than this is stale enough to redo on the next quiet moment.
STALE_AFTER_HOURS = 24

#: Skipped when mirroring: caches are per-session scratch, and the flat
#: memories/ export is regenerated on demand. Everything needed to reconstruct
#: the store (objects, refs, index, HEAD, config) is copied.
_MIRROR_SKIP = {'cache'}


@dataclass
class Destination:
    kind: str            # synced | volume | remote | path
    label: str           # human-readable, e.g. "iCloud Drive"
    target: str          # filesystem path, or git remote name
    auto_ok: bool        # may be used without asking (no new network egress)


@dataclass
class BackupState:
    last_ok: Optional[str] = None       # ISO timestamp
    last_target: Optional[str] = None
    last_kind: Optional[str] = None
    last_error: Optional[str] = None
    memories: int = 0
    disabled: bool = False
    pinned: Optional[str] = None        # operator-chosen destination path


def _state_path(repo) -> Path:
    return repo.path / _STATE


def read_state(repo) -> BackupState:
    try:
        raw = json.loads(_state_path(repo).read_text(encoding='utf-8'))
        return BackupState(**{k: v for k, v in raw.items()
                              if k in BackupState.__dataclass_fields__})
    except (OSError, json.JSONDecodeError, TypeError):
        return BackupState()


def write_state(repo, state: BackupState) -> None:
    try:
        _state_path(repo).write_text(json.dumps(asdict(state), indent=1),
                                     encoding='utf-8')
    except OSError:
        pass


# ── destination discovery ─────────────────────────────────────────────────────

def _synced_folder_candidates(home: Path) -> list[tuple[str, Path]]:
    """Cloud-sync roots this machine already has. Presence is the whole test —
    if the directory exists the user already uses (and trusts) that service."""
    return [
        ('iCloud Drive', home / 'Library' / 'Mobile Documents' / 'com~apple~CloudDocs'),
        ('Dropbox', home / 'Dropbox'),
        ('Google Drive', home / 'Library' / 'CloudStorage'),
        ('OneDrive', home / 'OneDrive'),
        ('Sync', home / 'Sync'),
    ]


def detect_destinations(repo, home: Optional[Path] = None) -> list[Destination]:
    """Every viable backup target, best-first.

    Ordering is deliberate: a configured git remote is the user's own explicit
    choice and wins; then cloud-synced folders (genuinely off-machine); then
    external volumes (off-disk, but only as good as the drive being attached).
    """
    home = home or Path.home()
    out: list[Destination] = []

    remote = _configured_remote(repo)
    if remote:
        out.append(Destination('remote', f'git remote ({remote})', remote,
                               auto_ok=True))

    for label, path in _synced_folder_candidates(home):
        if path.is_dir():
            out.append(Destination('synced', label, str(path / 'memgit-backup'),
                                   auto_ok=True))

    for vol in _external_volumes():
        out.append(Destination('volume', f'volume {vol.name}',
                               str(vol / 'memgit-backup'), auto_ok=True))

    return out


def _external_volumes() -> list[Path]:
    """Mounted volumes that are not the boot disk."""
    vols = Path('/Volumes')
    if not vols.is_dir():
        return []
    out = []
    try:
        for v in sorted(vols.iterdir()):
            try:
                if v.is_dir() and not v.is_symlink() and os.access(v, os.W_OK):
                    out.append(v)
            except OSError:
                continue
    except OSError:
        return []
    return out


def _configured_remote(repo) -> Optional[str]:
    """Name of a git remote already configured on the store, or None.

    memgit NEVER creates one. A remote here means the user chose a host.
    """
    root = repo.path.parent
    if not (root / '.git').exists():
        return None
    try:
        r = subprocess.run(['git', 'remote'], cwd=root, capture_output=True,
                           text=True, timeout=10)
        names = [n.strip() for n in r.stdout.splitlines() if n.strip()]
        return names[0] if names else None
    except Exception:
        return None


# ── running a backup ──────────────────────────────────────────────────────────

#: Archive name inside the destination directory. Fixed, not timestamped:
#: an unbounded pile of dated archives in someone's iCloud is a bug, and
#: memgit's own history already provides point-in-time recovery.
ARCHIVE_NAME = 'memgit-store.tar.gz'


def mirror_store(repo, target: Path) -> int:
    """Write the store to `target` as ONE compressed archive. Returns file count.

    An archive rather than a directory tree, because the realistic destination
    is a cloud-synced folder: the audited store is 203 MB across 10,295 small
    object files, and handing a sync client 10k files to reconcile on every
    backup is how you get a sync client that never finishes. One file also
    makes the swap below genuinely atomic.

    Written to a staging name and renamed over the target, with the old copy
    kept until the new one lands — an interrupted backup must never destroy the
    good copy it was replacing. That failure mode does not lose data loudly; it
    leaves a corrupt file where safety used to be, which is worse.
    """
    import tarfile

    target_dir = Path(target)
    target_dir.mkdir(parents=True, exist_ok=True)
    final = target_dir / ARCHIVE_NAME
    staging = target_dir / (ARCHIVE_NAME + '.incoming')
    previous = target_dir / (ARCHIVE_NAME + '.previous')
    staging.unlink(missing_ok=True)

    src_root = repo.path.parent
    files = 0

    def _filter(info: 'tarfile.TarInfo'):
        nonlocal files
        parts = Path(info.name).parts
        if any(p in _MIRROR_SKIP for p in parts):
            return None
        if info.issym() or info.islnk():
            return None
        if info.isfile():
            files += 1
        return info

    with tarfile.open(staging, 'w:gz', compresslevel=6) as tar:
        tar.add(src_root, arcname='memgit-store', filter=_filter)

    (target_dir / 'RESTORE.txt').write_text(
        f'memgit store backup\n'
        f'source  : {src_root}\n'
        f'written : {datetime.now(timezone.utc).isoformat()}\n'
        f'files   : {files}\n'
        f'archive : {ARCHIVE_NAME}\n\n'
        f'To restore:\n'
        f'  tar -xzf {ARCHIVE_NAME}\n'
        f'  rm -rf ~/.claude/memgit-store\n'
        f'  mv memgit-store ~/.claude/memgit-store\n'
        f'  memgit fsck\n',
        encoding='utf-8')

    previous.unlink(missing_ok=True)
    if final.exists():
        final.rename(previous)
    staging.rename(final)
    previous.unlink(missing_ok=True)
    return files


def push_remote(repo, remote: str) -> None:
    """Export flat memories, commit, and push to an ALREADY-configured remote."""
    root = repo.path.parent
    repo.write_flat()
    subprocess.run(['git', 'add', '-A'], cwd=root, capture_output=True, timeout=60)
    subprocess.run(
        ['git', 'commit', '-m',
         f'memgit backup {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}'],
        cwd=root, capture_output=True, timeout=60)
    r = subprocess.run(['git', 'push', remote, 'HEAD'], cwd=root,
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or 'git push failed').strip()[:300])


def run_backup(repo, dest: Optional[Destination] = None,
               home: Optional[Path] = None) -> tuple[bool, str]:
    """Back the store up to `dest` (or the best automatic one). (ok, message)."""
    state = read_state(repo)
    if dest is None:
        if state.pinned:
            dest = Destination('path', 'pinned', state.pinned, auto_ok=True)
        else:
            options = [d for d in detect_destinations(repo, home) if d.auto_ok]
            dest = options[0] if options else None
    if dest is None:
        return False, ('no backup destination available — no git remote is '
                       'configured and no cloud-synced folder or external '
                       'volume was found')

    try:
        if dest.kind == 'remote':
            push_remote(repo, dest.target)
            detail = f'pushed to {dest.label}'
        else:
            n = mirror_store(repo, Path(dest.target))
            detail = f'mirrored {n} files to {dest.target}'
    except Exception as e:                                  # noqa: BLE001
        state.last_error = str(e)[:300]
        write_state(repo, state)
        return False, f'backup failed: {state.last_error}'

    try:
        count = len(repo.list())
    except Exception:
        count = state.memories
    state.last_ok = datetime.now(timezone.utc).isoformat()
    state.last_target = dest.target
    state.last_kind = dest.kind
    state.last_error = None
    state.memories = count
    write_state(repo, state)
    return True, detail


# ── the automatic path ────────────────────────────────────────────────────────

def hours_since_backup(repo, now: Optional[datetime] = None) -> Optional[float]:
    """Hours since the last successful backup, or None if there has never been one."""
    state = read_state(repo)
    if not state.last_ok:
        return None
    try:
        last = datetime.fromisoformat(state.last_ok)
    except ValueError:
        return None
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - last).total_seconds() / 3600.0


def is_stale(repo, now: Optional[datetime] = None) -> bool:
    age = hours_since_backup(repo, now)
    return age is None or age >= STALE_AFTER_HOURS


def auto_backup_allowed(repo) -> bool:
    """Whether the UNATTENDED path may run for this store.

    Guard against a class of bug found the hard way: a test that exercised the
    end-of-session sync path fired a real backup into the developer's actual
    iCloud folder, because destination discovery reads the true home directory
    while the store was a temp path. Anything that writes outside the store,
    unprompted, must be certain it is operating on the user's real store.

    `MEMGIT_STORE` is set by the test suite (and by anyone pointing memgit at a
    scratch store), so it is exactly the signal for "this is not the store whose
    durability I am responsible for". Explicit `memgit backup now` is unaffected
    — that is a human or agent asking on purpose.
    """
    if os.environ.get('MEMGIT_STORE'):
        return False
    if os.environ.get('PYTEST_CURRENT_TEST'):
        return False
    return True


def maybe_auto_backup(repo, home: Optional[Path] = None,
                      now: Optional[datetime] = None) -> Optional[str]:
    """Back up if it is due and a safe destination exists. Silent and best-effort.

    Called from the end-of-session sync path, alongside the other housekeeping
    the AI operator never has to think about. Returns a short message when a
    backup ran, else None. Never raises into a hook.
    """
    try:
        if not auto_backup_allowed(repo):
            return None
        state = read_state(repo)
        if state.disabled:
            return None
        if not is_stale(repo, now):
            return None
        ok, msg = run_backup(repo, home=home)
        return msg if ok else None
    except Exception:                                       # noqa: BLE001
        return None


def status_line(repo, now: Optional[datetime] = None) -> Optional[str]:
    """One line for the resume digest when durability needs attention.

    Silent when a recent backup exists — a warning that fires every session is
    a warning that gets ignored. Loud, with the exact call to make, when there
    is no copy at all: that is the state where a disk failure is total loss.
    """
    state = read_state(repo)
    if state.disabled:
        return None
    age = hours_since_backup(repo, now)
    if age is None:
        try:
            n = len(repo.list())
        except Exception:
            n = 0
        if n < 20:
            return None      # nothing worth protecting yet
        # Terse on purpose. This rides a hard-budgeted digest injected every
        # session; the reasoning and the destination list live in
        # `memgit backup status`, one command away.
        return f'no backup — {n} memories on one disk. `memgit backup now`'
    if age >= STALE_AFTER_HOURS * 7:
        return f'last backup {int(age / 24)}d ago. `memgit backup now`'
    return None
