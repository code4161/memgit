"""Repository operations — init, add, commit, log, diff, show."""

from __future__ import annotations
import os
import tomllib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import (
    Checkpoint, DiffSummary, MindState, MindStateEntry, Mnemonic, Thread,
)
from .store import ObjectStore


class Repository:
    """A memgit repository rooted at `.memgit/`."""

    def __init__(self, memgit_dir: Path):
        self.path = memgit_dir
        self.store = ObjectStore(memgit_dir)

    # ── Discovery ─────────────────────────────────────────────────────────────

    @classmethod
    def find(cls, start: Path = None) -> Optional['Repository']:
        """Walk up from start looking for a `.memgit/` directory."""
        current = Path(start or Path.cwd())
        while True:
            candidate = current / '.memgit'
            if candidate.is_dir():
                return cls(candidate)
            parent = current.parent
            if parent == current:
                return None
            current = parent

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
            parts = line.split()
            if len(parts) == 2:
                result[parts[0]] = parts[1]
        return result

    def _write_index(self, index: dict[str, str]):
        thread = self.current_thread()
        head = self.head_sha() or 'none'
        lines = [
            '# TOON_INDEX v1',
            f'# thread: {thread}',
            f'# checkpoint: {head}',
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
        """Write a mnemonic and stage it in the index. Returns SHA."""
        sha = self.store.write_mnemonic(m)
        index = self.get_index()
        index[m.slug] = sha
        self._write_index(index)
        return sha

    def remove(self, slug: str) -> bool:
        """Remove a slug from the index (does not delete objects). Returns True if it existed."""
        index = self.get_index()
        if slug not in index:
            return False
        del index[slug]
        self._write_index(index)
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

    def commit(self, message: str = None, trigger: str = 'explicit') -> Optional[str]:
        """Checkpoint the current index. Returns checkpoint SHA or None if no changes."""
        now = datetime.now(timezone.utc)
        index = self.get_index()

        entries = [MindStateEntry(slug=s, mnem_sha=h) for s, h in index.items()]
        new_ms = MindState(timestamp=now, entries=entries)
        new_ms_sha = self.store.mindstate_sha(new_ms)

        # Compare against HEAD
        head = self.head_sha()
        if head:
            old_ck = self.store.read_checkpoint(head)
            if old_ck.mindstate_sha == new_ms_sha:
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

        ck = Checkpoint(
            mindstate_sha=new_ms_sha,
            timestamp=now,
            trigger=trigger,
            message=message,
            author=self._author(),
            session_id=str(uuid.uuid4()),
            parent_sha=head,
            diff_summary=diff,
        )
        ck_sha = self.store.write_checkpoint(ck)
        self._set_ref(self.current_thread(), ck_sha)
        self._rebuild_index()
        return ck_sha

    # ── History ───────────────────────────────────────────────────────────────

    def log(self, limit: int = 10, thread: str = None) -> list[Checkpoint]:
        """Return checkpoint chain from HEAD, newest first."""
        result = []
        sha = self.head_sha(thread)
        while sha and len(result) < limit:
            try:
                ck = self.store.read_checkpoint(sha)
            except Exception:
                break
            result.append(ck)
            sha = ck.parent_sha
        return result

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
        (self.path / 'HEAD').write_text(f'threads/{name}\n')
        self._rebuild_index()

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

    # ── Internal ──────────────────────────────────────────────────────────────

    def _author(self) -> str:
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
