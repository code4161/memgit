"""Repository operations — init, add, commit, log, diff, show, squash, flat-export."""

from __future__ import annotations
import os
import subprocess
import tomllib
import uuid
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


class Repository:
    """A memgit repository rooted at `.memgit/`."""

    def __init__(self, memgit_dir: Path):
        self.path = memgit_dir
        self.store = ObjectStore(memgit_dir)

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
        # SHA prefix — walk the chain; ambiguous prefixes resolve to None
        matches: list[str] = []
        sha = self.head_sha()
        while sha:
            if sha.startswith(ref):
                matches.append(sha)
            try:
                sha = self.store.read_checkpoint(sha).parent_sha
            except Exception:
                break
        return matches[0] if len(matches) == 1 else None

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

        # Step 4: Update HEAD
        newest_kept_sha = remap.get(kept_cks[0].sha, kept_cks[0].sha)
        self._set_ref(self.current_thread(), newest_kept_sha)
        self._rebuild_index()

        summary['new_head'] = newest_kept_sha[:8]
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

        checkpoints = self.log(limit=10_000)

        return {
            'total': len(mnemonics),
            'by_type': by_type,
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
            'checkpoint_count': len(checkpoints),
            'first_checkpoint_ts': checkpoints[-1].timestamp if checkpoints else None,
            'last_checkpoint_ts': checkpoints[0].timestamp if checkpoints else None,
        }

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
