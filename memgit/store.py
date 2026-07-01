"""Content-addressed object store.

Objects are stored at .memgit/objects/{sha[0:2]}/{sha[2:4]}/{sha[4:]}
Each file is gzip-compressed: first line is type, rest is TOON content.

SHA computation per spec:
  Mnemonic  → SHA-256(canonical TOON text)
  MindState → SHA-256(sorted "slug:sha\\n" pairs)
  Checkpoint → SHA-256("CKPT1\\n" + JSON of core fields)
"""

from __future__ import annotations
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

from .models import Checkpoint, DiffSummary, MindState, MindStateEntry, Mnemonic
from .toon import (
    format_ts,
    parse_toon,
    serialize_checkpoint,
    serialize_mindstate,
    serialize_mnemonic,
)


class ObjectStore:
    def __init__(self, root: Path):
        self.root = root
        self.objects_dir = root / 'objects'

    def _obj_path(self, sha: str) -> Path:
        return self.objects_dir / sha[:2] / sha[2:4] / sha[4:]

    def resolve_sha(self, abbrev: str) -> str | None:
        """Resolve an abbreviated SHA (≥4 chars) to the full 64-char SHA.

        Returns the full SHA if exactly one match, None if not found or ambiguous.
        If abbrev is already 64 chars, returns it as-is.
        """
        if len(abbrev) >= 64:
            return abbrev
        if len(abbrev) < 4:
            return None
        prefix2 = abbrev[:2]
        prefix4 = abbrev[2:4]
        rest_prefix = abbrev[4:]
        search_dir = self.objects_dir / prefix2 / prefix4
        if not search_dir.exists():
            return None
        matches = [
            prefix2 + prefix4 + p.name
            for p in search_dir.iterdir()
            if p.is_file() and p.name.startswith(rest_prefix)
        ]
        return matches[0] if len(matches) == 1 else None

    def _write(self, sha: str, type_name: str, toon_content: str):
        path = self._obj_path(sha)
        if path.exists():
            return  # content-addressed: same SHA = same content
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, 'wt', encoding='utf-8') as f:
            f.write(f'{type_name}\n{toon_content}')

    def _read(self, sha: str) -> tuple[str, str]:
        path = self._obj_path(sha)
        if not path.exists() and len(sha) < 64:
            full = self.resolve_sha(sha)
            if full:
                path = self._obj_path(full)
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            data = f.read()
        idx = data.index('\n')
        return data[:idx], data[idx + 1:]

    def exists(self, sha: str) -> bool:
        if self._obj_path(sha).exists():
            return True
        if len(sha) < 64:
            return self.resolve_sha(sha) is not None
        return False

    # ── Mnemonic ──────────────────────────────────────────────────────────────

    def mnemonic_sha(self, m: Mnemonic) -> str:
        canonical = serialize_mnemonic(m, canonical=True)
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    def write_mnemonic(self, m: Mnemonic) -> str:
        sha = self.mnemonic_sha(m)
        m.sha = sha
        canonical = serialize_mnemonic(m, canonical=True)
        self._write(sha, 'mnem', canonical)
        return sha

    def read_mnemonic(self, sha: str) -> Mnemonic:
        type_name, content = self._read(sha)
        assert type_name == 'mnem', f'Expected mnem, got {type_name}'
        objs = parse_toon(content)
        if not objs:
            raise ValueError(f'Failed to parse mnemonic {sha[:8]}')
        m = objs[0]
        assert isinstance(m, Mnemonic), f'Expected Mnemonic, got {type(m)}'
        m.sha = sha
        return m

    # ── MindState ─────────────────────────────────────────────────────────────

    def mindstate_sha(self, ms: MindState) -> str:
        entries = sorted(ms.entries, key=lambda e: e.slug)
        lines = [f'{e.slug}:{e.mnem_sha}' for e in entries]
        content = '\n'.join(lines)
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def write_mindstate(self, ms: MindState) -> str:
        sha = self.mindstate_sha(ms)
        ms.sha = sha
        toon = serialize_mindstate(ms)
        self._write(sha, 'ms', toon)
        return sha

    def read_mindstate(self, sha: str) -> MindState:
        type_name, content = self._read(sha)
        assert type_name == 'ms', f'Expected ms, got {type_name}'
        objs = parse_toon(content)
        if not objs:
            return MindState(timestamp=datetime.now(timezone.utc), sha=sha)
        ms = objs[0]
        assert isinstance(ms, MindState), f'Expected MindState, got {type(ms)}'
        ms.sha = sha
        return ms

    # ── Checkpoint ────────────────────────────────────────────────────────────

    def checkpoint_sha(self, ck: Checkpoint) -> str:
        data = {
            'parent_sha': ck.parent_sha,
            'mindstate_sha': ck.mindstate_sha,
            'timestamp': format_ts(ck.timestamp),
            'trigger': ck.trigger,
            'message': ck.message,
            'author': ck.author,
        }
        content = 'CKPT1\n' + json.dumps(data, sort_keys=True)
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def write_checkpoint(self, ck: Checkpoint) -> str:
        sha = self.checkpoint_sha(ck)
        ck.sha = sha
        toon = serialize_checkpoint(ck)
        self._write(sha, 'ck', toon)
        return sha

    def read_checkpoint(self, sha: str) -> Checkpoint:
        type_name, content = self._read(sha)
        assert type_name == 'ck', f'Expected ck, got {type_name}'
        objs = parse_toon(content)
        if not objs:
            raise ValueError(f'Failed to parse checkpoint {sha[:8]}')
        ck = objs[0]
        assert isinstance(ck, Checkpoint), f'Expected Checkpoint, got {type(ck)}'
        ck.sha = sha  # override with full sha from the store path
        return ck

    # ── Stats ─────────────────────────────────────────────────────────────────

    def object_count(self) -> int:
        count = 0
        for p in self.objects_dir.rglob('*'):
            if p.is_file():
                count += 1
        return count
