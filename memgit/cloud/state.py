"""Local cloud state under <store>/.memgit/cloud/ — credentials + sync bookkeeping.

Two files, both 0600, both JSON:
  credentials.json — api_url, email, tokens, decrypted user private key, cached team keys.
                     Deleted by `memgit cloud logout`. MEMGIT_CLOUD_NO_CACHE=1 keeps keys
                     out of it (passphrase will be re-prompted per command).
  state.json       — repo link (team_id/repo_id) + per-thread {synced_remote_head, version},
                     memgit-cloud's equivalent of git's remote-tracking refs.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


class CloudState:
    def __init__(self, memgit_dir: Path):
        self.dir = memgit_dir / 'cloud'
        self.creds_path = self.dir / 'credentials.json'
        self.state_path = self.dir / 'state.json'

    def _read(self, path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _write(self, path: Path, data: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(path)

    # credentials -------------------------------------------------------------
    @property
    def creds(self) -> dict:
        return self._read(self.creds_path)

    def save_creds(self, **updates) -> dict:
        data = self.creds
        data.update(updates)
        self._write(self.creds_path, data)
        return data

    def clear_creds(self) -> None:
        self.creds_path.unlink(missing_ok=True)

    def cache_keys_allowed(self) -> bool:
        return os.environ.get('MEMGIT_CLOUD_NO_CACHE', '') not in ('1', 'true', 'yes')

    # sync state --------------------------------------------------------------
    @property
    def state(self) -> dict:
        return self._read(self.state_path)

    def save_state(self, **updates) -> dict:
        data = self.state
        data.update(updates)
        self._write(self.state_path, data)
        return data

    def link(self) -> tuple[str, str] | None:
        s = self.state
        if s.get('team_id') and s.get('repo_id'):
            return s['team_id'], s['repo_id']
        return None

    def thread_state(self, thread: str) -> dict:
        return self.state.get('threads', {}).get(thread, {})

    def set_thread_state(self, thread: str, synced_remote_head: str | None, version: int) -> None:
        data = self.state
        data.setdefault('threads', {})[thread] = {
            'synced_remote_head': synced_remote_head,
            'version': version,
        }
        self._write(self.state_path, data)
