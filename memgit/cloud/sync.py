"""Push/pull/sync between the local memgit store and an E2E-encrypted cloud repo.

Semantics mirror git with a remote-tracking record per thread (state.json):
  push  — upload the head's reachable closure (only objects the server lacks),
          then CAS the ref. Refused if the remote has checkpoints we haven't
          incorporated (synced_remote_head mismatch).
  pull  — fetch the remote closure, verify every object's memgit SHA after
          decrypting, then fast-forward, or three-way merge via a temporary
          thread when histories diverged (memgit checkpoints are single-parent,
          so "incorporated" is tracked in state.json, not by ancestry alone).
  sync  — pull then push.
"""
from __future__ import annotations

from ..repo import Repository
from . import crypto
from .client import ApiClient, RefConflict
from .state import CloudState

TEMP_MERGE_THREAD = 'cloud-incoming'


class SyncResult:
    def __init__(self, **kw):
        self.pushed = kw.get('pushed', 0)
        self.fetched = kw.get('fetched', 0)
        self.action = kw.get('action', 'up-to-date')  # up-to-date|pushed|fast-forward|merged|created
        self.head = kw.get('head')
        self.conflicts = kw.get('conflicts', [])


class SyncEngine:
    def __init__(self, repo: Repository, api: ApiClient, cstate: CloudState,
                 team_key: bytes, repo_id: str):
        self.repo = repo
        self.store = repo.store
        self.api = api
        self.cstate = cstate
        self.team_key = team_key
        self.repo_id = repo_id

    # ── DAG helpers ──────────────────────────────────────────────────────────
    def _closure(self, head: str) -> list[str]:
        """All object SHAs reachable from a checkpoint head (cks, mindstates, mnemonics)."""
        seen: set[str] = set()
        out: list[str] = []
        ck_sha = head
        while ck_sha and ck_sha not in seen:
            seen.add(ck_sha)
            out.append(ck_sha)
            ck = self.store.read_checkpoint(ck_sha)
            if ck.mindstate_sha and ck.mindstate_sha not in seen:
                seen.add(ck.mindstate_sha)
                out.append(ck.mindstate_sha)
                ms = self.store.read_mindstate(ck.mindstate_sha)
                for e in ms.entries:
                    if e.mnem_sha not in seen:
                        seen.add(e.mnem_sha)
                        out.append(e.mnem_sha)
            ck_sha = ck.parent_sha
        return out

    def _is_ancestor(self, ancestor: str, descendant: str) -> bool:
        sha = descendant
        while sha:
            if sha == ancestor:
                return True
            try:
                sha = self.store.read_checkpoint(sha).parent_sha
            except Exception:
                return False
        return False

    def _raw(self, sha: str) -> bytes:
        type_name, content = self.store._read(sha)
        return f'{type_name}\n{content}'.encode('utf-8')

    def _verify_and_write(self, sha_hex: str, raw: bytes) -> None:
        """Parse a decrypted object, recompute its type-specific memgit SHA, store it."""
        from ..toon import parse_toon
        text = raw.decode('utf-8')
        idx = text.index('\n')
        type_name, content = text[:idx], text[idx + 1:]
        objs = parse_toon(content)
        if not objs:
            raise ValueError(f'cannot parse pulled object {sha_hex[:8]}')
        obj = objs[0]
        computed = {
            'mnem': lambda: self.store.mnemonic_sha(obj),
            'ms': lambda: self.store.mindstate_sha(obj),
            'ck': lambda: self.store.checkpoint_sha(obj),
        }.get(type_name)
        if computed is None:
            raise ValueError(f'unknown object type {type_name!r} in {sha_hex[:8]}')
        if computed() != sha_hex:
            raise ValueError(f'integrity check failed for pulled object {sha_hex[:8]}')
        self.store._write(sha_hex, type_name, content)

    # ── remote ref helpers ───────────────────────────────────────────────────
    def _remote_ref(self, thread: str) -> tuple[str, dict | None]:
        ref_id = crypto.remote_id(self.team_key, thread)
        for r in self.api.list_refs(self.repo_id):
            if r['id' if 'id' in r else 'ref_id'] == ref_id:
                return ref_id, r
        return ref_id, None

    def _decrypt_head(self, ref: dict) -> str:
        return crypto.decrypt_meta(self.team_key, ref['value_enc'])

    # ── push ─────────────────────────────────────────────────────────────────
    def push(self, thread: str) -> SyncResult:
        head = self.repo.head_sha(thread)
        if head is None:
            return SyncResult(action='up-to-date')

        ref_id, ref = self._remote_ref(thread)
        version = ref['version'] if ref else 0
        remote_head = self._decrypt_head(ref) if ref else None
        if remote_head == head:
            self.cstate.set_thread_state(thread, head, version)
            return SyncResult(action='up-to-date', head=head)
        synced = self.cstate.thread_state(thread).get('synced_remote_head')
        if remote_head is not None and remote_head != synced:
            raise RefConflict({'current_version': version})

        shas = self._closure(head)
        ids = {crypto.remote_id(self.team_key, s): s for s in shas}
        missing = self.api.missing_objects(self.repo_id, list(ids))
        payload = [
            {'id': rid, 'data': crypto.encrypt_object(self.team_key, ids[rid], self._raw(ids[rid]))}
            for rid in missing
        ]
        pushed = self.api.upload_objects(self.repo_id, payload) if payload else 0

        new_version = self.api.put_ref(
            self.repo_id, ref_id,
            name_enc=crypto.encrypt_meta(self.team_key, thread),
            value_enc=crypto.encrypt_meta(self.team_key, head),
            expected_version=version,
        )['version']
        self.cstate.set_thread_state(thread, head, new_version)
        return SyncResult(action='pushed' if ref else 'created', pushed=pushed, head=head)

    # ── pull ─────────────────────────────────────────────────────────────────
    def pull(self, thread: str) -> SyncResult:
        ref_id, ref = self._remote_ref(thread)
        if ref is None:
            return SyncResult(action='up-to-date')
        remote_head = self._decrypt_head(ref)
        local_head = self.repo.head_sha(thread)

        fetched = self._fetch_closure(remote_head)

        if local_head == remote_head or (local_head and self._is_ancestor(remote_head, local_head)):
            # nothing new for us (equal, or we're strictly ahead)
            self.cstate.set_thread_state(thread, remote_head, ref['version'])
            return SyncResult(action='up-to-date', fetched=fetched, head=local_head)

        if local_head is None or self._is_ancestor(local_head, remote_head):
            self._fast_forward(thread, remote_head)
            self.cstate.set_thread_state(thread, remote_head, ref['version'])
            return SyncResult(action='fast-forward', fetched=fetched, head=remote_head)

        # diverged → merge via a temporary thread
        current = self.repo.current_thread()
        if current != thread:
            raise ValueError(
                f'thread {thread!r} diverged from remote but is not the current thread; '
                f'switch to it first (memgit thread switch {thread})'
            )
        self.repo._set_ref(TEMP_MERGE_THREAD, remote_head)
        try:
            new_sha, conflicts, _diff = self.repo.merge_thread(
                TEMP_MERGE_THREAD, message=f'merge cloud ({remote_head[:8]})'
            )
        finally:
            (self.repo.path / 'refs' / 'threads' / TEMP_MERGE_THREAD).unlink(missing_ok=True)
            (self.repo.path / 'logs' / 'threads' / TEMP_MERGE_THREAD).unlink(missing_ok=True)
        self.cstate.set_thread_state(thread, remote_head, ref['version'])
        return SyncResult(action='merged', fetched=fetched,
                          head=new_sha or self.repo.head_sha(thread), conflicts=conflicts)

    def _fetch_closure(self, remote_head: str) -> int:
        """Walk the remote checkpoint chain, fetching objects missing locally.

        Walks the full chain (local reads are cheap for history we already
        have) so an interrupted earlier pull can never leave permanent holes.
        Returns the number of objects fetched.
        """
        fetched = 0
        seen: set[str] = set()
        ck_sha = remote_head
        while ck_sha and ck_sha not in seen:
            seen.add(ck_sha)
            if not self.store.exists(ck_sha):
                fetched += self._fetch_objects([ck_sha])
            ck = self.store.read_checkpoint(ck_sha)
            if ck.mindstate_sha:
                if not self.store.exists(ck.mindstate_sha):
                    fetched += self._fetch_objects([ck.mindstate_sha])
                ms = self.store.read_mindstate(ck.mindstate_sha)
                mnems = [e.mnem_sha for e in ms.entries if not self.store.exists(e.mnem_sha)]
                fetched += self._fetch_objects(mnems)
            ck_sha = ck.parent_sha
        return fetched

    def _fetch_objects(self, shas: list[str]) -> int:
        if not shas:
            return 0
        rid_map = {crypto.remote_id(self.team_key, s): s for s in shas}
        objects = self.api.get_objects(self.repo_id, list(rid_map))
        if len(objects) < len(rid_map):
            got = {o['id'] for o in objects}
            missing = [rid_map[r][:8] for r in rid_map if r not in got]
            raise ValueError(f'remote is missing objects: {", ".join(missing)} — '
                             f'the pusher may not have finished; try again')
        for o in objects:
            sha_hex, raw = crypto.decrypt_object(self.team_key, o['data'])
            if sha_hex != rid_map[o['id']]:
                raise ValueError(f'object id mismatch for {sha_hex[:8]}')
            self._verify_and_write(sha_hex, raw)
        return len(objects)

    def _fast_forward(self, thread: str, new_head: str) -> None:
        with self.repo._lock():
            self.repo._set_ref(thread, new_head)
            if self.repo.current_thread() == thread:
                self.repo._rebuild_index()
            counts = self.repo._read_counts()
            if counts.pop(thread, None) is not None:
                self.repo._write_counts(counts)
        if self.repo.memories_dir.exists() and self.repo.current_thread() == thread:
            self.repo.write_flat()

    # ── sync ─────────────────────────────────────────────────────────────────
    def sync(self, thread: str) -> tuple[SyncResult, SyncResult]:
        pulled = self.pull(thread)
        pushed = self.push(thread)
        return pulled, pushed
