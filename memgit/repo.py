"""Repository operations — init, add, commit, log, diff, show, squash, flat-export."""

from __future__ import annotations
import json
import os
import subprocess
import time
import tomllib
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .models import (
    Checkpoint, DiffSummary, MindState, MindStateEntry, Mnemonic, Thread,
)
from .store import ObjectStore


def default_store_candidates() -> list[Path]:
    """Well-known store locations, in the same order `memgit init` auto-detects."""
    home = Path.home()
    return [
        home / '.claude' / 'memgit-store',
        home / '.cursor' / 'memgit-store',
        home / '.windsurf' / 'memgit-store',
        home / '.memgit-store',
    ]


#: A lock older than this is considered abandoned (crashed process) and broken.
LOCK_STALE_SECONDS = 60.0
#: How long a writer waits for the lock before giving up.
LOCK_TIMEOUT_SECONDS = float(os.environ.get('MEMGIT_LOCK_TIMEOUT', '10'))


class LockTimeout(RuntimeError):
    """Could not acquire the store lock — another agent holds it."""


class Repository:
    """A memgit repository rooted at `.memgit/`."""

    def __init__(self, memgit_dir: Path):
        self.path = memgit_dir
        self.store = ObjectStore(memgit_dir)
        self._lock_depth = 0  # same-process re-entrancy for the store lock

    # ── Store lock (multi-agent write safety) ─────────────────────────────────

    @property
    def _lock_path(self) -> Path:
        return self.path / 'memgit.lock'

    def _try_break_stale_lock(self):
        """Remove the lockfile if its owner is gone or it has aged out."""
        lp = self._lock_path
        try:
            raw = lp.read_text().split()
            pid = int(raw[0]) if raw else 0
            age = time.time() - lp.stat().st_mtime
        except (OSError, ValueError):
            return
        pid_alive = False
        if pid > 0:
            try:
                os.kill(pid, 0)
                pid_alive = True
            except OSError:
                pid_alive = False
        if not pid_alive or age > LOCK_STALE_SECONDS:
            try:
                lp.unlink()
            except OSError:
                pass

    @contextmanager
    def _lock(self, timeout: float = None):
        """Advisory whole-store write lock (git-style lockfile).

        Serializes index/ref mutations across processes so concurrent agents
        can't interleave read-modify-write cycles. Re-entrant within one
        Repository instance. Raises LockTimeout if the lock stays held.
        """
        if self._lock_depth > 0:
            self._lock_depth += 1
            try:
                yield
            finally:
                self._lock_depth -= 1
            return

        timeout = LOCK_TIMEOUT_SECONDS if timeout is None else timeout
        deadline = time.monotonic() + timeout
        while True:
            try:
                fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f'{os.getpid()} {time.time():.0f}\n'.encode())
                os.close(fd)
                break
            except FileExistsError:
                self._try_break_stale_lock()
                if time.monotonic() >= deadline:
                    raise LockTimeout(
                        f'store locked by another process ({self._lock_path}) — '
                        f'retried for {timeout:.0f}s'
                    )
                time.sleep(0.05)

        self._lock_depth = 1
        try:
            yield
        finally:
            self._lock_depth = 0
            try:
                self._lock_path.unlink()
            except OSError:
                pass

    # ── Discovery ─────────────────────────────────────────────────────────────

    @classmethod
    def find(cls, start: Path = None) -> Optional['Repository']:
        """Walk up from start looking for a `.memgit/` directory.

        If none is found, fall back to the well-known store locations that
        `memgit init` auto-detects, so commands work from any directory.
        """
        current = Path(start or Path.cwd())
        while True:
            candidate = current / '.memgit'
            if candidate.is_dir():
                return cls(candidate)
            parent = current.parent
            if parent == current:
                break
            current = parent

        for store in default_store_candidates():
            candidate = store / '.memgit'
            if candidate.is_dir():
                return cls(candidate)
        return None

    # ── Init ──────────────────────────────────────────────────────────────────

    @classmethod
    def init(cls, project_dir: Path) -> 'Repository':
        """Initialize a new repository in `project_dir`."""
        memgit = project_dir / '.memgit'
        for sub in ['objects', 'refs/threads', 'refs/tags', 'logs/threads']:
            (memgit / sub).mkdir(parents=True, exist_ok=True)

        (memgit / 'HEAD').write_text('threads/main\n')
        _write_config(memgit / 'config', {
            'core': {'author': os.environ.get('USER', 'unknown'), 'version': 1},
            'thread': {'default': 'main'},
        })

        repo = cls(memgit)

        # Create flat memories directory for git-native sync
        (project_dir / 'memories').mkdir(exist_ok=True)

        # Root checkpoint with empty MindState
        now = datetime.now(timezone.utc)
        ms = MindState(timestamp=now, entries=[])
        ms_sha = repo.store.write_mindstate(ms)

        ck = Checkpoint(
            mindstate_sha=ms_sha,
            timestamp=now,
            trigger='explicit',
            message='Initial checkpoint',
            author=_env_author(),
            session_id=str(uuid.uuid4()),
            parent_sha=None,
            diff_summary=DiffSummary(),
        )
        ck_sha = repo.store.write_checkpoint(ck)
        repo._set_ref('main', ck_sha)
        repo._write_index({})
        return repo

    # ── Thread / HEAD ─────────────────────────────────────────────────────────

    def current_thread(self) -> str:
        head = (self.path / 'HEAD').read_text().strip()
        return head.removeprefix('threads/')

    def head_sha(self, thread: str = None) -> Optional[str]:
        ref = self.path / 'refs' / 'threads' / (thread or self.current_thread())
        return ref.read_text().strip() if ref.exists() else None

    def _set_ref(self, thread: str, sha: str):
        ref = self.path / 'refs' / 'threads' / thread
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_text(sha + '\n')
        log = self.path / 'logs' / 'threads' / thread
        log.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat()
        with open(log, 'a') as f:
            f.write(f'{ts} {sha}\n')

    # ── TOON_INDEX (staging area) ─────────────────────────────────────────────

    def get_index(self) -> dict[str, str]:
        """Load TOON_INDEX → {slug: mnem_sha}."""
        idx_path = self.path / 'TOON_INDEX'
        if not idx_path.exists():
            return {}
        result: dict[str, str] = {}
        for line in idx_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # rsplit tolerates legacy slugs containing spaces instead of
            # silently dropping the entry (the SHA is always the last field).
            parts = line.rsplit(None, 1)
            if len(parts) == 2:
                result[parts[0]] = parts[1]
        return result

    def get_index_base(self) -> Optional[str]:
        """The checkpoint SHA the staging index was built from.

        Read from the `# checkpoint:` header. Used by commit() to detect that
        another agent moved HEAD since this index was staged (→ auto-merge).
        """
        idx_path = self.path / 'TOON_INDEX'
        if not idx_path.exists():
            return None
        for line in idx_path.read_text().splitlines():
            if line.startswith('# checkpoint:'):
                sha = line.split(':', 1)[1].strip()
                return None if sha in ('', 'none') else sha
        return None

    def _write_index(self, index: dict[str, str], base_sha: Optional[str] = 'HEAD'):
        """Write TOON_INDEX.

        base_sha: checkpoint the index derives from. Default 'HEAD' stamps the
        current head; staging ops pass the preserved base so a concurrent
        commit by another agent is still detected at commit time.
        """
        thread = self.current_thread()
        if base_sha == 'HEAD':
            base_sha = self.head_sha()
        lines = [
            '# TOON_INDEX v1',
            f'# thread: {thread}',
            f'# checkpoint: {base_sha or "none"}',
        ]
        for slug in sorted(index):
            lines.append(f'{slug} {index[slug]}')
        (self.path / 'TOON_INDEX').write_text('\n'.join(lines) + '\n')

    def _rebuild_index(self):
        """Rebuild TOON_INDEX from the HEAD checkpoint's MindState."""
        sha = self.head_sha()
        if not sha:
            self._write_index({})
            return
        ck = self.store.read_checkpoint(sha)
        ms = self.store.read_mindstate(ck.mindstate_sha)
        self._write_index({e.slug: e.mnem_sha for e in ms.entries})

    # ── Mnemonic operations ───────────────────────────────────────────────────

    def add(self, m: Mnemonic) -> str:
        """Write a mnemonic and stage it in the index. Returns SHA.

        The slug is normalized to index-safe characters: the index format is
        space-delimited, so a slug containing whitespace would be unparseable
        on read-back and the memory would silently vanish.
        """
        import re as _re
        safe = _re.sub(r'[^A-Za-z0-9_-]+', '-', m.slug).strip('-')
        if not safe:
            raise ValueError(f'invalid slug: {m.slug!r}')
        m.slug = safe
        if not (m.rule or '').strip():
            raise ValueError(f'empty rule for {m.slug!r} — a memory with no '
                             'fact is unrecallable')
        with self._lock():
            sha = self.store.write_mnemonic(m)
            index = self.get_index()
            base = self.get_index_base()
            index[m.slug] = sha
            self._write_index(index, base_sha=base)
        return sha

    def remove(self, slug: str) -> bool:
        """Remove a slug from the index (does not delete objects). Returns True if it existed."""
        with self._lock():
            index = self.get_index()
            if slug not in index:
                return False
            base = self.get_index_base()
            del index[slug]
            self._write_index(index, base_sha=base)
        return True

    def get(self, slug: str) -> Optional[Mnemonic]:
        index = self.get_index()
        sha = index.get(slug)
        return self.store.read_mnemonic(sha) if sha else None

    def list(self) -> list[Mnemonic]:
        index = self.get_index()
        result = []
        for slug, sha in index.items():
            try:
                result.append(self.store.read_mnemonic(sha))
            except Exception:
                pass
        return result

    # ── Commit ────────────────────────────────────────────────────────────────

    def _mindstate_map(self, ck_sha: Optional[str]) -> dict[str, str]:
        """slug → mnem_sha map for a checkpoint's MindState ({} for None)."""
        if not ck_sha:
            return {}
        try:
            ck = self.store.read_checkpoint(ck_sha)
            ms = self.store.read_mindstate(ck.mindstate_sha)
            return {e.slug: e.mnem_sha for e in ms.entries}
        except Exception:
            return {}

    def _merge_maps(
        self,
        base: dict[str, str],
        theirs: dict[str, str],
        ours: dict[str, str],
    ) -> tuple[dict[str, str], list[str]]:
        """Three-way merge of slug→sha maps. Returns (merged, conflicted_slugs).

        Standard rules: a side that didn't touch a slug defers to the side
        that did; both touching it identically is trivial; both touching it
        differently is a conflict, resolved by newest mnemonic timestamp
        (delete loses to an edit).
        """
        merged: dict[str, str] = {}
        conflicts: list[str] = []
        for slug in set(base) | set(theirs) | set(ours):
            b, t, o = base.get(slug), theirs.get(slug), ours.get(slug)
            if t == o:
                winner = o
            elif t == b:      # only we changed it
                winner = o
            elif o == b:      # only they changed it
                winner = t
            else:             # both changed → newest mnemonic wins; edit beats delete
                conflicts.append(slug)
                if t is None:
                    winner = o
                elif o is None:
                    winner = t
                else:
                    try:
                        t_ts = self.store.read_mnemonic(t).timestamp
                        o_ts = self.store.read_mnemonic(o).timestamp
                        winner = t if t_ts > o_ts else o
                    except Exception:
                        winner = o
            if winner is not None:
                merged[slug] = winner
        return merged, sorted(conflicts)

    def commit(self, message: str = None, trigger: str = 'explicit') -> Optional[str]:
        """Checkpoint the current index. Returns checkpoint SHA or None if no changes.

        Multi-agent safe: runs under the store lock, and if HEAD moved past the
        index's base checkpoint (another agent committed since this index was
        staged) the two states are three-way merged instead of clobbered.
        """
        with self._lock():
            return self._commit_locked(message, trigger)

    def _commit_locked(self, message: str = None, trigger: str = 'explicit') -> Optional[str]:
        now = datetime.now(timezone.utc)
        index = self.get_index()

        # CAS check: did another agent move HEAD since this index was staged?
        base = self.get_index_base()
        head_now = self.head_sha()
        merged_note = ''
        if head_now and base != head_now:
            base_map = self._mindstate_map(base)
            head_map = self._mindstate_map(head_now)
            index, conflicts = self._merge_maps(base_map, head_map, index)
            merged_note = f'(auto-merged over {head_now[:8]}'
            merged_note += f', {len(conflicts)} conflict{"s" if len(conflicts) != 1 else ""} resolved) ' \
                if conflicts else ') '
            if trigger == 'explicit':
                trigger = 'merge'

        entries = [MindStateEntry(slug=s, mnem_sha=h) for s, h in index.items()]
        new_ms = MindState(timestamp=now, entries=entries)
        new_ms_sha = self.store.mindstate_sha(new_ms)

        # Compare against HEAD
        if head_now:
            old_ck = self.store.read_checkpoint(head_now)
            if old_ck.mindstate_sha == new_ms_sha:
                if merged_note:
                    # Merge resolved to exactly HEAD's state — adopt it so the
                    # index base is fresh and status reads clean.
                    self._rebuild_index()
                return None  # nothing changed
            old_ms = self.store.read_mindstate(old_ck.mindstate_sha)
        else:
            old_ms = MindState(timestamp=now, entries=[])

        self.store.write_mindstate(new_ms)

        # Compute diff
        old_map = {e.slug: e.mnem_sha for e in old_ms.entries}
        new_map = {e.slug: e.mnem_sha for e in new_ms.entries}
        diff = DiffSummary(
            added=[s for s in new_map if s not in old_map],
            removed=[s for s in old_map if s not in new_map],
            modified=[s for s in old_map if s in new_map and old_map[s] != new_map[s]],
            unchanged=[s for s in old_map if s in new_map and old_map[s] == new_map[s]],
        )

        if message is None:
            parts = []
            if diff.added:
                sample = ', '.join(diff.added[:3])
                suffix = '...' if len(diff.added) > 3 else ''
                parts.append(f'Added {len(diff.added)}: {sample}{suffix}')
            if diff.modified:
                sample = ', '.join(diff.modified[:3])
                suffix = '...' if len(diff.modified) > 3 else ''
                parts.append(f'Updated {len(diff.modified)}: {sample}{suffix}')
            if diff.removed:
                sample = ', '.join(diff.removed[:3])
                suffix = '...' if len(diff.removed) > 3 else ''
                parts.append(f'Removed {len(diff.removed)}: {sample}{suffix}')
            message = '; '.join(parts) or 'No changes'

        if merged_note:
            message = merged_note + message

        ck = Checkpoint(
            mindstate_sha=new_ms_sha,
            timestamp=now,
            trigger=trigger,
            message=message,
            author=self._author(),
            session_id=str(uuid.uuid4()),
            parent_sha=head_now,
            diff_summary=diff,
        )
        ck_sha = self.store.write_checkpoint(ck)
        thread = self.current_thread()
        self._set_ref(thread, ck_sha)
        self._rebuild_index()

        # Incremental chain-count update — O(1) instead of a history walk
        from .toon import format_ts
        cached = self._read_counts().get(thread)
        if head_now is None:
            self._update_count_cache(thread, ck_sha, 1, format_ts(now))
        elif cached and cached.get('head') == head_now:
            self._update_count_cache(
                thread, ck_sha, int(cached['count']) + 1,
                cached.get('first_ts', format_ts(now)),
            )
        return ck_sha

    # ── History ───────────────────────────────────────────────────────────────

    def log(self, limit: int = 10, thread: str = None, skip: int = 0) -> list[Checkpoint]:
        """Return checkpoint chain from HEAD, newest first.

        skip: number of newest checkpoints to page past (git log --skip).
        """
        result = []
        sha = self.head_sha(thread)
        skipped = 0
        while sha and len(result) < limit:
            try:
                ck = self.store.read_checkpoint(sha)
            except Exception:
                break
            if skipped < skip:
                skipped += 1
            else:
                result.append(ck)
            sha = ck.parent_sha
        return result

    # ── Chain-count cache (long-history scaling) ──────────────────────────────

    @property
    def _counts_path(self) -> Path:
        return self.path / 'cache' / 'counts.json'

    def _read_counts(self) -> dict:
        try:
            return json.loads(self._counts_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_counts(self, counts: dict):
        self._counts_path.parent.mkdir(parents=True, exist_ok=True)
        self._counts_path.write_text(json.dumps(counts))

    def _update_count_cache(self, thread: str, head: str, count: int, first_ts: str):
        counts = self._read_counts()
        counts[thread] = {'head': head, 'count': count, 'first_ts': first_ts}
        self._write_counts(counts)

    def chain_info(self, thread: str = None) -> tuple[int, Optional[datetime]]:
        """(checkpoint count, root timestamp) for a thread, O(1) when cached.

        The cache is keyed to the current head SHA — any mismatch (older
        version wrote history, squash, manual surgery) falls back to a full
        walk and repopulates it.
        """
        thread = thread or self.current_thread()
        head = self.head_sha(thread)
        if head is None:
            return 0, None

        cached = self._read_counts().get(thread)
        if cached and cached.get('head') == head:
            try:
                from .toon import _parse_ts
                return int(cached['count']), _parse_ts(cached['first_ts'])
            except (KeyError, ValueError):
                pass

        # Cache miss — full walk, then repopulate
        count = 0
        first_ts = None
        sha = head
        while sha:
            try:
                ck = self.store.read_checkpoint(sha)
            except Exception:
                break
            count += 1
            first_ts = ck.timestamp
            sha = ck.parent_sha
        if first_ts is not None:
            from .toon import format_ts
            self._update_count_cache(thread, head, count, format_ts(first_ts))
        return count, first_ts

    def diff(self, sha1: str = None, sha2: str = None) -> DiffSummary:
        """Diff two checkpoints. Defaults to HEAD^ → HEAD."""
        sha2 = sha2 or self.head_sha()
        if sha2 is None:
            return DiffSummary()

        if sha1 is None:
            ck2 = self.store.read_checkpoint(sha2)
            sha1 = ck2.parent_sha

        if sha1 is None:
            old_ms = MindState(timestamp=datetime.now(timezone.utc), entries=[])
        else:
            ck1 = self.store.read_checkpoint(sha1)
            old_ms = self.store.read_mindstate(ck1.mindstate_sha)

        ck2 = self.store.read_checkpoint(sha2)
        new_ms = self.store.read_mindstate(ck2.mindstate_sha)

        old_map = {e.slug: e.mnem_sha for e in old_ms.entries}
        new_map = {e.slug: e.mnem_sha for e in new_ms.entries}

        return DiffSummary(
            added=[s for s in new_map if s not in old_map],
            removed=[s for s in old_map if s not in new_map],
            modified=[s for s in old_map if s in new_map and old_map[s] != new_map[s]],
            unchanged=[s for s in old_map if s in new_map and old_map[s] == new_map[s]],
        )

    def diff_full(self, sha1: str = None, sha2: str = None) -> list[tuple[str, str, Optional[Mnemonic], Optional[Mnemonic]]]:
        """Return detailed diff: list of (slug, status, old_mnem, new_mnem).

        status: 'added' | 'removed' | 'modified' | 'unchanged'
        """
        sha2 = sha2 or self.head_sha()
        if sha2 is None:
            return []

        if sha1 is None:
            ck2 = self.store.read_checkpoint(sha2)
            sha1 = ck2.parent_sha

        if sha1 is None:
            old_ms = MindState(timestamp=datetime.now(timezone.utc), entries=[])
        else:
            ck1 = self.store.read_checkpoint(sha1)
            old_ms = self.store.read_mindstate(ck1.mindstate_sha)

        ck2 = self.store.read_checkpoint(sha2)
        new_ms = self.store.read_mindstate(ck2.mindstate_sha)

        old_map = {e.slug: e.mnem_sha for e in old_ms.entries}
        new_map = {e.slug: e.mnem_sha for e in new_ms.entries}
        all_slugs = sorted(set(old_map) | set(new_map))

        result = []
        for slug in all_slugs:
            old_sha = old_map.get(slug)
            new_sha = new_map.get(slug)
            old_m = self.store.read_mnemonic(old_sha) if old_sha else None
            new_m = self.store.read_mnemonic(new_sha) if new_sha else None

            if old_sha is None:
                status = 'added'
            elif new_sha is None:
                status = 'removed'
            elif old_sha != new_sha:
                status = 'modified'
            else:
                status = 'unchanged'
            result.append((slug, status, old_m, new_m))

        return result

    # ── Rollback ──────────────────────────────────────────────────────────────

    def resolve_ref(self, ref: str) -> Optional[str]:
        """Resolve 'HEAD', 'HEAD~n', or a checkpoint SHA prefix to a full SHA."""
        ref = ref.strip()
        upper = ref.upper()
        if upper == 'HEAD':
            return self.head_sha()
        if upper.startswith('HEAD~'):
            try:
                n = int(ref[5:])
            except ValueError:
                return None
            sha = self.head_sha()
            for _ in range(n):
                if not sha:
                    return None
                try:
                    sha = self.store.read_checkpoint(sha).parent_sha
                except Exception:
                    return None
            return sha
        # SHA prefix — resolve via the object store's fan-out directories
        # (O(1) in history length; the old chain walk was O(n) per lookup).
        if len(ref) >= 4 and all(c in '0123456789abcdef' for c in ref.lower()):
            full = self.store.resolve_sha(ref.lower())
            if full and self.store.exists(full):
                try:
                    self.store.read_checkpoint(full)  # must be a checkpoint
                    return full
                except Exception:
                    return None
        return None

    def rollback(self, ref: str, dry_run: bool = False) -> tuple[Optional[str], DiffSummary]:
        """Restore the memory state to checkpoint `ref` (git-revert style).

        Creates a NEW checkpoint whose MindState equals the target's —
        history is preserved, no objects are deleted.
        Returns (new_checkpoint_sha, diff current→target). The sha is None
        on dry_run or when the state already matches the target.
        """
        target_sha = self.resolve_ref(ref)
        if target_sha is None:
            raise ValueError(f'cannot resolve ref: {ref}')
        target_ck = self.store.read_checkpoint(target_sha)
        target_ms = self.store.read_mindstate(target_ck.mindstate_sha)
        target_index = {e.slug: e.mnem_sha for e in target_ms.entries}

        current = self.get_index()
        diff = DiffSummary(
            added=[s for s in target_index if s not in current],
            removed=[s for s in current if s not in target_index],
            modified=[s for s in current if s in target_index and current[s] != target_index[s]],
            unchanged=[s for s in current if s in target_index and current[s] == target_index[s]],
        )
        if dry_run:
            return None, diff

        with self._lock():
            self._write_index(target_index)
            new_sha = self.commit(
                message=f'rollback to {target_sha[:8]}', trigger='rollback',
            )
        if new_sha and self.memories_dir.exists():
            self.write_flat()
        return new_sha, diff

    # ── Thread management ─────────────────────────────────────────────────────

    def thread_create(self, name: str, description: str = '') -> Thread:
        head = self.head_sha()
        if head is None:
            raise ValueError('No HEAD checkpoint to branch from')
        self._set_ref(name, head)
        ck = self.store.read_checkpoint(head)
        return Thread(name=name, head_sha=head, created_at=ck.timestamp, description=description)

    def thread_list(self) -> list[Thread]:
        threads_dir = self.path / 'refs' / 'threads'
        result = []
        for p in threads_dir.rglob('*'):
            if p.is_file():
                name = str(p.relative_to(threads_dir))
                sha = p.read_text().strip()
                try:
                    ck = self.store.read_checkpoint(sha)
                    result.append(Thread(name=name, head_sha=sha, created_at=ck.timestamp))
                except Exception:
                    result.append(Thread(name=name, head_sha=sha, created_at=datetime.now(timezone.utc)))
        return result

    def thread_switch(self, name: str):
        ref = self.path / 'refs' / 'threads' / name
        if not ref.exists():
            raise ValueError(f'Thread {name!r} does not exist')
        with self._lock():
            (self.path / 'HEAD').write_text(f'threads/{name}\n')
            self._rebuild_index()

    # ── Merge (multi-agent: thread-per-agent workflows) ───────────────────────

    def merge_base(self, sha_a: str, sha_b: str) -> Optional[str]:
        """Nearest common ancestor of two checkpoints (None if unrelated)."""
        ancestors: set[str] = set()
        sha = sha_a
        while sha:
            ancestors.add(sha)
            try:
                sha = self.store.read_checkpoint(sha).parent_sha
            except Exception:
                break
        sha = sha_b
        while sha:
            if sha in ancestors:
                return sha
            try:
                sha = self.store.read_checkpoint(sha).parent_sha
            except Exception:
                break
        return None

    def merge_thread(self, other: str, message: str = None) -> tuple[Optional[str], list[str], DiffSummary]:
        """Merge another thread's memory state into the current thread.

        Three-way merge against the nearest common ancestor; conflicts resolve
        to the newest mnemonic (edit beats delete). Returns
        (new_checkpoint_sha_or_None, conflicted_slugs, diff_vs_before).
        History of both threads is preserved — this only advances the current
        thread with a merge checkpoint.
        """
        theirs_head = self.head_sha(other)
        if theirs_head is None:
            raise ValueError(f'Thread {other!r} does not exist')

        with self._lock():
            ours_head = self.head_sha()
            if ours_head is None:
                raise ValueError('Current thread has no checkpoint')

            base_sha = self.merge_base(ours_head, theirs_head)
            base_map = self._mindstate_map(base_sha)
            ours_map = self.get_index()          # includes staged changes
            theirs_map = self._mindstate_map(theirs_head)

            merged, conflicts = self._merge_maps(base_map, theirs_map, ours_map)

            before = dict(ours_map)
            diff = DiffSummary(
                added=[s for s in merged if s not in before],
                removed=[s for s in before if s not in merged],
                modified=[s for s in before if s in merged and before[s] != merged[s]],
                unchanged=[s for s in before if s in merged and before[s] == merged[s]],
            )

            self._write_index(merged)
            msg = message or (
                f'merge thread {other!r} ({theirs_head[:8]})'
                + (f' — {len(conflicts)} conflict{"s" if len(conflicts) != 1 else ""} resolved'
                   if conflicts else '')
            )
            new_sha = self.commit(message=msg, trigger='merge')
        if new_sha and self.memories_dir.exists():
            self.write_flat()
        return new_sha, conflicts, diff

    # ── Integrity ─────────────────────────────────────────────────────────────

    def fsck(self, rebuild_index: bool = False) -> list[str]:
        """Verify repository integrity. Returns list of error messages."""
        errors = []
        index = self.get_index()
        for slug, sha in index.items():
            if not self.store.exists(sha):
                errors.append(f'MISSING mnemonic object: {slug} → {sha[:8]}')
        head = self.head_sha()
        if head and not self.store.exists(head):
            errors.append(f'MISSING HEAD checkpoint: {head[:8]}')
        if rebuild_index:
            self._rebuild_index()
        return errors

    # ── Resume (session-start orientation) ────────────────────────────────────

    def resume_context(self, checkpoints: int = 5, recent: int = 10,
                       project: Optional[str] = None) -> dict:
        """A bounded digest of 'where we left off' for session start.

        Structured for an AI agent picking up work: last checkpoints (what
        happened), staged-but-uncommitted changes (work in flight), recently
        updated memories (what changed lately), and critical memories (rules
        that always apply). Deliberately compact — a resume primer, not a dump.

        project: when given and the store has memories for it, the recent
        list is drawn from that project first — a session in project A should
        not open with project B's latest work.
        """
        thread = self.current_thread()
        head = self.head_sha()

        # Recent checkpoint history
        cks = self.log(limit=checkpoints)
        ck_list = []
        for ck in cks:
            d = ck.diff_summary
            ck_list.append({
                'sha': (ck.sha or '')[:8],
                'timestamp': ck.timestamp,
                'trigger': ck.trigger,
                'author': ck.author,
                'message': ck.message,
                'added': len(d.added) if d else 0,
                'modified': len(d.modified) if d else 0,
                'removed': len(d.removed) if d else 0,
            })

        # Staged (uncommitted) work in flight
        index = self.get_index()
        committed = self._mindstate_map(head)
        staged = {
            'new': sorted(s for s in index if s not in committed),
            'updated': sorted(s for s in index if s in committed and index[s] != committed[s]),
            'removed': sorted(s for s in committed if s not in index),
        }

        # Recently updated memories (by mnemonic timestamp) + critical set
        from .project import project_affinity
        mnemonics = self.list()
        by_recency = sorted(mnemonics, key=lambda m: m.timestamp, reverse=True)
        if project:
            # Exact workspace first, then the same project tree (a session in
            # BITS/bits_back still counts BITS memories as its own), then
            # global (unscoped) memories. Other projects' scoped memories are
            # NEVER pulled in as filler — a new client project's first
            # session must not open with another client's content.
            exact = [m for m in by_recency
                     if project_affinity(m.project, project) == 2]
            family = [m for m in by_recency
                      if project_affinity(m.project, project) == 1]
            unscoped = [m for m in by_recency if not m.project]
            pool = exact + family + unscoped
            project_is_new = not (exact or family)
        else:
            pool = by_recency
            project_is_new = False
        recent_mems = [
            {'slug': m.slug, 'type': m.type_code, 'priority': m.priority,
             'timestamp': m.timestamp, 'rule': m.rule, 'project': m.project}
            for m in pool[:recent]
        ]
        critical_pool = mnemonics
        if project:
            # Critical rules follow the same scoping: this project's tree
            # plus global rules — not every project's always-apply set.
            critical_pool = [
                m for m in mnemonics
                if not m.project or project_affinity(m.project, project) >= 1
            ]
        critical = [
            {'slug': m.slug, 'rule': m.rule}
            for m in sorted(critical_pool, key=lambda m: m.slug)
            if m.priority == 3
        ]

        # Core operating guide (type 'co') — a per-project navigation aid that
        # is ALWAYS injected in full (its body, not the clipped rule), so any
        # host instantly knows which tools/skills to reach for even when its
        # own CLAUDE.md/skills aren't configured. Per-project scoped (Q3): a
        # session only sees its own project tree's core, never another's; with
        # no project context, only unscoped core shows. It is a fallback aid,
        # NOT authority — the repo's own rules win on conflict.
        if project:
            core_pool = [m for m in mnemonics
                         if project_affinity(m.project, project) >= 1]
        else:
            core_pool = [m for m in mnemonics if not m.project]
        core = [
            {'slug': m.slug, 'rule': m.rule, 'body': m.body}
            for m in sorted(core_pool, key=lambda m: m.slug)
            if m.type_code == 'co'
        ]

        count, first_ts = self.chain_info(thread)
        return {
            'thread': thread,
            'project': project,
            'project_is_new': project_is_new,
            'head': (head or '')[:8],
            'checkpoint_count': count,
            'history_since': first_ts,
            'total_memories': len(mnemonics),
            'checkpoints': ck_list,
            'staged': staged,
            'recent_memories': recent_mems,
            'critical_memories': critical,
            'core_memories': core,
            'maintenance': self.maintenance_hint(count),
        }

    #: Above this many checkpoints, surface a maintenance hint in resume/status.
    MAINTENANCE_CHECKPOINTS = 500
    #: Above this store size, surface a maintenance hint.
    MAINTENANCE_BYTES = 50 * 1024 * 1024

    def maintenance_hint(self, checkpoint_count: int = None) -> Optional[str]:
        """One-line self-maintenance signal, or None while healthy.

        The primary operator of memgit is an AI agent — it won't read docs to
        learn when to compact, so the store tells it at the moment of use.
        Cheap: cached count check first, then one stat per object file.
        """
        if checkpoint_count is None:
            checkpoint_count, _ = self.chain_info()
        if checkpoint_count > self.MAINTENANCE_CHECKPOINTS:
            return (f'history has {checkpoint_count} checkpoints — run '
                    f'`memgit gc --squash-keep {self.MAINTENANCE_CHECKPOINTS // 2}` '
                    f'to compact (archives what it collapses; current state untouched)')
        _, byts = self.disk_usage()
        if byts > self.MAINTENANCE_BYTES:
            return (f'store is {byts // (1024 * 1024)} MB — run `memgit gc` '
                    f'to sweep unreachable objects')
        return None

    # ── GC (space reclamation) ────────────────────────────────────────────────

    def disk_usage(self) -> tuple[int, int]:
        """(object_count, total_bytes) of the object store."""
        count = 0
        total = 0
        for p in self.store.objects_dir.rglob('*'):
            if p.is_file():
                count += 1
                total += p.stat().st_size
        return count, total

    def _reachable_shas(self) -> set[str]:
        """Every object SHA reachable from any thread ref, tag, or the staging index."""
        reachable: set[str] = set()

        ref_shas: list[str] = []
        for refs_dir in (self.path / 'refs' / 'threads', self.path / 'refs' / 'tags'):
            if refs_dir.is_dir():
                for p in refs_dir.rglob('*'):
                    if p.is_file():
                        ref_shas.append(p.read_text().strip())

        for start in ref_shas:
            sha = start
            while sha and sha not in reachable:
                reachable.add(sha)
                try:
                    ck = self.store.read_checkpoint(sha)
                except Exception:
                    break
                if ck.mindstate_sha and ck.mindstate_sha not in reachable:
                    reachable.add(ck.mindstate_sha)
                    try:
                        ms = self.store.read_mindstate(ck.mindstate_sha)
                        for e in ms.entries:
                            reachable.add(e.mnem_sha)
                    except Exception:
                        pass
                sha = ck.parent_sha

        # Staged-but-uncommitted mnemonics must survive
        for sha in self.get_index().values():
            reachable.add(sha)
        return reachable

    def gc(self, dry_run: bool = False, reflog_keep: int = 1000) -> dict:
        """Reclaim space: delete unreachable objects, trim reflogs.

        Conservative by design — only sweeps objects that are provably
        unreachable from every thread ref, tag, and the staging index.
        Reachable history is never touched. Run after `squash` to actually
        free the collapsed checkpoints' storage.
        """
        with self._lock():
            reachable = self._reachable_shas()

            objects_before, bytes_before = self.disk_usage()
            deleted = 0
            bytes_freed = 0
            for p in sorted(self.store.objects_dir.rglob('*')):
                if not p.is_file():
                    continue
                sha = p.parent.parent.name + p.parent.name + p.name
                if sha in reachable:
                    continue
                deleted += 1
                bytes_freed += p.stat().st_size
                if not dry_run:
                    p.unlink()

            if not dry_run:
                # Drop now-empty fan-out directories
                for p in sorted(self.store.objects_dir.rglob('*'), reverse=True):
                    if p.is_dir():
                        try:
                            p.rmdir()
                        except OSError:
                            pass

            # Trim reflogs: cap length and drop entries whose checkpoint is gone
            reflog_trimmed = 0
            logs_dir = self.path / 'logs' / 'threads'
            if logs_dir.is_dir():
                for lf in logs_dir.rglob('*'):
                    if not lf.is_file():
                        continue
                    lines = lf.read_text().splitlines()
                    kept = [
                        ln for ln in lines[-reflog_keep:]
                        if len(ln.split()) == 2 and ln.split()[1] in reachable
                    ]
                    if len(kept) < len(lines):
                        reflog_trimmed += len(lines) - len(kept)
                        if not dry_run:
                            lf.write_text('\n'.join(kept) + ('\n' if kept else ''))

        return {
            'objects_before': objects_before,
            'objects_deleted': deleted,
            'objects_after': objects_before - (0 if dry_run else deleted),
            'bytes_before': bytes_before,
            'bytes_freed': bytes_freed,
            'reflog_entries_trimmed': reflog_trimmed,
            'dry_run': dry_run,
        }

    # ── Flat memories/ directory (git-native sync) ────────────────────────────

    @property
    def memories_dir(self) -> Path:
        return self.path.parent / 'memories'

    def write_flat(self):
        """Write every indexed memory as a readable .toon file under memories/.

        This is the git sync surface — users can `git push` this directory to
        share memories across machines and teammates. Each file is human-readable
        and diffable with standard git tools.
        """
        from .toon import serialize_mnemonic
        mdir = self.memories_dir
        mdir.mkdir(exist_ok=True)

        index = self.get_index()
        current_slugs: set[str] = set()

        for slug, sha in index.items():
            try:
                m = self.store.read_mnemonic(sha)
                toon_text = serialize_mnemonic(m)
                (mdir / f'{slug}.toon').write_text(toon_text + '\n')
                current_slugs.add(slug)
            except Exception:
                pass

        # Remove stale files for deleted memories
        for f in mdir.glob('*.toon'):
            if f.stem not in current_slugs:
                f.unlink()

    def import_flat(self) -> int:
        """Import memories from memories/ flat files into the object store.

        Used after a `git pull` to absorb teammate memory updates.
        Returns the number of memories imported.
        """
        from .toon import parse_toon
        from .models import Mnemonic as MnemType
        mdir = self.memories_dir
        if not mdir.exists():
            return 0
        count = 0
        for f in sorted(mdir.glob('*.toon')):
            try:
                objs = parse_toon(f.read_text())
                for obj in objs:
                    if isinstance(obj, MnemType):
                        self.add(obj)
                        count += 1
            except Exception:
                pass
        return count

    # ── Git integration ───────────────────────────────────────────────────────

    def git_init(self) -> bool:
        """Run `git init` in the store root (parent of .memgit/).

        Creates a .gitignore that tracks memories/ but ignores the binary
        object blobs. Returns True if successful."""
        store_root = self.path.parent
        gitignore = store_root / '.gitignore'
        if not gitignore.exists():
            gitignore.write_text(
                '# memgit object blobs — large and redundant with memories/\n'
                '.memgit/objects/\n'
                '.memgit/logs/\n'
                '*.pyc\n'
            )
        try:
            if not (store_root / '.git').exists():
                subprocess.run(['git', 'init'], cwd=store_root, check=True,
                               capture_output=True)
            return True
        except Exception:
            return False

    def git_status(self) -> Optional[str]:
        """Return git status output for the store root, or None if not a git repo."""
        store_root = self.path.parent
        if not (store_root / '.git').exists():
            return None
        try:
            r = subprocess.run(['git', 'status', '--short'], cwd=store_root,
                               capture_output=True, text=True, check=True)
            return r.stdout.strip()
        except Exception:
            return None

    def git_push(self, remote: str = 'origin', branch: str = 'main',
                 message: str = None) -> tuple[bool, str]:
        """Write flat files then `git add + commit + push`.

        Returns (success, output_message).
        """
        store_root = self.path.parent
        if not (store_root / '.git').exists():
            return False, 'Not a git repo — run `memgit git init` first'
        self.write_flat()
        head_sha = self.head_sha() or 'none'
        commit_msg = message or f'memgit: checkpoint {head_sha[:8]}'
        try:
            subprocess.run(['git', 'add', 'memories/', '.memgit/refs/'], cwd=store_root,
                           check=True, capture_output=True)
            r = subprocess.run(
                ['git', 'diff', '--cached', '--quiet'],
                cwd=store_root, capture_output=True,
            )
            if r.returncode == 0:
                return True, 'Nothing to push (no changes since last git commit)'
            subprocess.run(['git', 'commit', '-m', commit_msg], cwd=store_root,
                           check=True, capture_output=True)
            subprocess.run(['git', 'push', '-u', remote, branch], cwd=store_root,
                           check=True, capture_output=True)
            return True, f'Pushed to {remote}/{branch}'
        except subprocess.CalledProcessError as e:
            return False, e.stderr.decode() if e.stderr else str(e)

    def git_pull(self, remote: str = 'origin', branch: str = 'main') -> tuple[bool, str, int]:
        """Pull from git remote then import flat files.

        Returns (success, message, memories_imported).
        """
        store_root = self.path.parent
        if not (store_root / '.git').exists():
            return False, 'Not a git repo', 0
        try:
            subprocess.run(['git', 'pull', remote, branch], cwd=store_root,
                           check=True, capture_output=True)
            count = self.import_flat()
            if count > 0:
                sha = self.commit(f'pull: imported {count} memories from {remote}/{branch}')
                return True, f'Pulled {count} memories', count
            return True, 'Already up to date', 0
        except subprocess.CalledProcessError as e:
            return False, e.stderr.decode() if e.stderr else str(e), 0

    # ── Squash (scale to 10k+ commits) ───────────────────────────────────────

    def squash(
        self,
        keep_last: int = None,
        older_than_days: int = None,
        dry_run: bool = False,
    ) -> dict:
        """Squash old checkpoints into a single baseline checkpoint.

        Like `git rebase -i --autosquash`, but for memory history. Keeps the
        full current memory state; collapses old checkpoint metadata.

        Args:
            keep_last: Keep this many recent checkpoints; squash the rest.
            older_than_days: Squash all checkpoints older than N days.
            dry_run: Preview only, no changes.

        Returns dict with squash summary.
        """
        with self._lock():
            return self._squash_locked(keep_last, older_than_days, dry_run)

    def _squash_locked(
        self,
        keep_last: int = None,
        older_than_days: int = None,
        dry_run: bool = False,
    ) -> dict:
        all_cks = self.log(limit=10_000)
        if len(all_cks) < 3:
            return {'squashed': 0, 'kept': len(all_cks), 'dry_run': dry_run}

        # Determine the cut point
        now = datetime.now(timezone.utc)
        cut_idx = None

        if keep_last is not None:
            cut_idx = keep_last
        elif older_than_days is not None:
            cutoff = now - timedelta(days=older_than_days)
            for i, ck in enumerate(all_cks):
                if ck.timestamp < cutoff:
                    cut_idx = i
                    break
        else:
            cut_idx = max(1, len(all_cks) // 2)  # default: halve history

        if cut_idx is None or cut_idx >= len(all_cks):
            return {'squashed': 0, 'kept': len(all_cks), 'dry_run': dry_run}

        kept_cks = all_cks[:cut_idx]          # newest N checkpoints, keep as-is
        squashed_cks = all_cks[cut_idx:]      # older ones, collapse to one baseline

        baseline_ck = squashed_cks[0]         # oldest of the squashed set = the baseline

        summary = {
            'kept': len(kept_cks),
            'squashed': len(squashed_cks),
            'baseline_sha': baseline_ck.sha[:8] if baseline_ck.sha else '?',
            'baseline_ts': baseline_ck.timestamp.strftime('%Y-%m-%d'),
            'dry_run': dry_run,
        }

        if dry_run:
            return summary

        # Step 0: Archive the collapsed checkpoints' metadata before rewriting.
        # Compaction must be lossless-in-substance: the objects go away (via gc)
        # but the one-line record of each checkpoint survives in an append-only,
        # greppable log that gc never touches.
        archive = self.path / 'logs' / 'archive' / self.current_thread()
        archive.parent.mkdir(parents=True, exist_ok=True)
        from .toon import format_ts
        with open(archive, 'a') as f:
            for ck in reversed(squashed_cks):  # oldest first
                d = ck.diff_summary
                delta = (f'+{len(d.added)} ~{len(d.modified)} -{len(d.removed)}'
                         if d else '')
                msg = ck.message.replace('\t', ' ').replace('\n', ' ')
                f.write(f'{(ck.sha or "?")[:16]}\t{format_ts(ck.timestamp)}\t'
                        f'{ck.trigger}\t{ck.author}\t{delta}\t{msg}\n')

        # Step 1: Write a new "squash root" checkpoint that has no parent —
        # this is the baseline. It carries the MindState from the oldest squashed
        # checkpoint so the memory content at that point in time is preserved.
        squash_root = Checkpoint(
            mindstate_sha=baseline_ck.mindstate_sha,
            timestamp=baseline_ck.timestamp,
            trigger='squash',
            message=f'squash root: {len(squashed_cks)} older checkpoints collapsed',
            author=baseline_ck.author,
            session_id=baseline_ck.session_id,
            parent_sha=None,   # no parent — this is the new root
            diff_summary=DiffSummary(),
        )
        squash_root_sha = self.store.write_checkpoint(squash_root)

        # Step 2: Rewrite kept chain so oldest_kept.parent → squash_root
        oldest_kept = kept_cks[-1]
        remap: dict[str, str] = {}

        rewritten_oldest = Checkpoint(
            mindstate_sha=oldest_kept.mindstate_sha,
            timestamp=oldest_kept.timestamp,
            trigger=oldest_kept.trigger,
            message=f'(squashed {len(squashed_cks)} older checkpoints) {oldest_kept.message}',
            author=oldest_kept.author,
            session_id=oldest_kept.session_id,
            parent_sha=squash_root_sha,
            diff_summary=oldest_kept.diff_summary,
        )
        remap[oldest_kept.sha] = self.store.write_checkpoint(rewritten_oldest)

        # Step 3: Walk newer checkpoints, updating each parent pointer
        for ck in reversed(kept_cks[:-1]):
            parent = remap.get(ck.parent_sha, ck.parent_sha)
            updated = Checkpoint(
                mindstate_sha=ck.mindstate_sha,
                timestamp=ck.timestamp,
                trigger=ck.trigger,
                message=ck.message,
                author=ck.author,
                session_id=ck.session_id,
                parent_sha=parent,
                diff_summary=ck.diff_summary,
            )
            remap[ck.sha] = self.store.write_checkpoint(updated)

        # Step 4: Update HEAD. Keep the index CONTENT untouched — staged
        # (uncommitted) work must survive a squash; only the base checkpoint
        # pointer moves to the rewritten head (same state, new sha).
        newest_kept_sha = remap.get(kept_cks[0].sha, kept_cks[0].sha)
        thread = self.current_thread()
        staged_index = self.get_index()
        self._set_ref(thread, newest_kept_sha)
        self._write_index(staged_index, base_sha=newest_kept_sha)

        # History was rewritten — refresh the chain-count cache
        self._update_count_cache(
            thread, newest_kept_sha, len(kept_cks) + 1,
            format_ts(baseline_ck.timestamp),
        )

        summary['new_head'] = newest_kept_sha[:8]
        summary['archive'] = str(archive)
        return summary

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Compute token-savings statistics for the memory store."""
        from .tokens import all_memories_tokens, memory_tokens, token_cost_usd

        mnemonics = self.list()
        if not mnemonics:
            return {'total': 0}

        full_tokens = all_memories_tokens(mnemonics)
        avg_mem_tokens = full_tokens / len(mnemonics) if mnemonics else 0

        # Cost of a typical search: top-8 memories of average size.
        # (Deterministic — simulated queries under-fill the top-k on misses
        # and inflate the savings figure.)
        avg_search_tokens = round(avg_mem_tokens * min(8, len(mnemonics)))

        critical = [m for m in mnemonics if m.priority == 3]
        critical_tokens = sum(memory_tokens(m) for m in critical)

        by_type: dict[str, int] = {}
        for m in mnemonics:
            by_type[m.type_code] = by_type.get(m.type_code, 0) + 1

        by_project: dict[str, int] = {}
        for m in mnemonics:
            key = m.project or '(global)'
            by_project[key] = by_project.get(key, 0) + 1

        ck_count, first_ts = self.chain_info()   # O(1) via cache, not a walk
        last = self.log(limit=1)
        obj_count, obj_bytes = self.disk_usage()

        return {
            'total': len(mnemonics),
            'by_type': by_type,
            'by_project': by_project,
            'priority_counts': {
                3: sum(1 for m in mnemonics if m.priority == 3),
                2: sum(1 for m in mnemonics if m.priority == 2),
                1: sum(1 for m in mnemonics if m.priority == 1),
            },
            'full_tokens': full_tokens,
            'avg_mem_tokens': round(avg_mem_tokens),
            'avg_search_tokens': avg_search_tokens,
            'critical_tokens': critical_tokens,
            'reduction_pct': round(100 * (1 - avg_search_tokens / full_tokens)) if full_tokens else 0,
            'weekly_savings_tokens': (full_tokens - avg_search_tokens) * 10,  # 10 sessions/week
            'weekly_savings_usd': round(token_cost_usd((full_tokens - avg_search_tokens) * 10), 4),
            'checkpoint_count': ck_count,
            'first_checkpoint_ts': first_ts,
            'last_checkpoint_ts': last[0].timestamp if last else None,
            'object_count': obj_count,
            'disk_bytes': obj_bytes,
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _author(self) -> str:
        # MEMGIT_AUTHOR lets each agent in a multi-agent job sign its own
        # checkpoints (e.g. MEMGIT_AUTHOR=researcher-1).
        env_override = os.environ.get('MEMGIT_AUTHOR')
        if env_override:
            return env_override
        try:
            cfg = _read_config(self.path / 'config')
            return cfg.get('core', {}).get('author', _env_author())
        except Exception:
            return _env_author()


# ── Config helpers ────────────────────────────────────────────────────────────

def _env_author() -> str:
    return os.environ.get('USER', os.environ.get('USERNAME', 'unknown'))


def _write_config(path: Path, data: dict):
    lines = []
    for section, values in data.items():
        lines.append(f'[{section}]')
        for k, v in values.items():
            if isinstance(v, str):
                lines.append(f'{k} = "{v}"')
            elif isinstance(v, (int, float)):
                lines.append(f'{k} = {v}')
            elif isinstance(v, bool):
                lines.append(f'{k} = {"true" if v else "false"}')
        lines.append('')
    path.write_text('\n'.join(lines))


def _read_config(path: Path) -> dict:
    with open(path, 'rb') as f:
        return tomllib.load(f)
