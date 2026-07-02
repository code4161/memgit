"""HTTP client for the memgit cloud API — auth, token refresh, and typed helpers.

Raises CloudError with a human-readable message on any API failure; callers
(commands.py) surface it and exit non-zero. Never touches the local object store.
"""
from __future__ import annotations

import httpx

DEFAULT_API_URL = 'https://api.memgit.dev'


class CloudError(Exception):
    pass


class ApiClient:
    def __init__(self, api_url: str, cloud_state=None):
        self.api_url = api_url.rstrip('/')
        self._state = cloud_state  # CloudState, for token persistence on refresh
        self._http = httpx.Client(base_url=self.api_url, timeout=30.0)
        self.access: str | None = None
        self.refresh: str | None = None
        if cloud_state:
            creds = cloud_state.creds
            self.access = creds.get('access')
            self.refresh = creds.get('refresh')

    def close(self) -> None:
        self._http.close()

    # ── low-level ────────────────────────────────────────────────────────────
    def _request(self, method: str, path: str, *, json=None, params=None, auth=True,
                 _retry=True) -> httpx.Response:
        headers = {}
        if auth:
            if not self.access:
                raise CloudError('not logged in — run: memgit cloud login')
            headers['Authorization'] = f'Bearer {self.access}'
        try:
            r = self._http.request(method, path, json=json, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise CloudError(f'cannot reach {self.api_url}: {e}') from e
        if r.status_code == 401 and auth and _retry and self.refresh:
            self._do_refresh()
            return self._request(method, path, json=json, params=params, auth=auth, _retry=False)
        return r

    def _check(self, r: httpx.Response, *allowed: int) -> dict:
        if r.status_code in (allowed or (200, 201)):
            return r.json() if r.content else {}
        try:
            detail = r.json().get('detail', r.text)
        except ValueError:
            detail = r.text
        raise CloudError(f'API error {r.status_code}: {detail}')

    def _do_refresh(self) -> None:
        r = self._http.post('/v1/auth/refresh', json={'refresh': self.refresh})
        if r.status_code != 200:
            raise CloudError('session expired — run: memgit cloud login')
        body = r.json()
        self.access, self.refresh = body['access'], body['refresh']
        if self._state:
            self._state.save_creds(access=self.access, refresh=self.refresh)

    def _set_tokens(self, body: dict) -> None:
        self.access, self.refresh = body['access'], body['refresh']

    # ── auth ─────────────────────────────────────────────────────────────────
    def signup(self, email: str, auth_key: str, kdf_salt: str,
               public_key: str, enc_private_key: str) -> dict:
        r = self._request('POST', '/v1/auth/signup', auth=False, json={
            'email': email, 'auth_key': auth_key, 'kdf_salt': kdf_salt,
            'public_key': public_key, 'enc_private_key': enc_private_key,
        })
        body = self._check(r, 201)
        self._set_tokens(body)
        return body

    def get_salt(self, email: str) -> str:
        r = self._request('GET', '/v1/auth/salt', auth=False, params={'email': email})
        return self._check(r, 200)['kdf_salt']

    def login(self, email: str, auth_key: str) -> dict:
        r = self._request('POST', '/v1/auth/login', auth=False,
                          json={'email': email, 'auth_key': auth_key})
        if r.status_code == 401:
            raise CloudError('invalid email or passphrase')
        body = self._check(r, 200)
        self._set_tokens(body)
        return body

    def me(self) -> dict:
        return self._check(self._request('GET', '/v1/me'), 200)

    # ── teams / invites / repos ──────────────────────────────────────────────
    def create_team(self, name_enc: str, wrapped_team_key: str) -> dict:
        return self._check(self._request('POST', '/v1/teams', json={
            'name_enc': name_enc, 'wrapped_team_key': wrapped_team_key}), 201)

    def my_teams(self) -> list[dict]:
        return self._check(self._request('GET', '/v1/teams'), 200)

    def team_detail(self, team_id: str) -> dict:
        return self._check(self._request('GET', f'/v1/teams/{team_id}'), 200)

    def create_invite(self, team_id: str, box: str, verifier: str,
                      uses: int = 10, expires_in_days: int = 14) -> dict:
        return self._check(self._request('POST', f'/v1/teams/{team_id}/invites', json={
            'box': box, 'verifier': verifier, 'uses': uses,
            'expires_in_days': expires_in_days}), 201)

    def preview_invite(self, invite_id: str, verifier: str) -> dict:
        return self._check(self._request('POST', f'/v1/invites/{invite_id}/preview',
                                         json={'verifier': verifier}), 200)

    def accept_invite(self, invite_id: str, verifier: str, wrapped_team_key: str) -> dict:
        return self._check(self._request('POST', f'/v1/invites/{invite_id}/accept', json={
            'verifier': verifier, 'wrapped_team_key': wrapped_team_key}), 201)

    def create_repo(self, team_id: str, name_enc: str) -> dict:
        return self._check(self._request('POST', f'/v1/teams/{team_id}/repos',
                                         json={'name_enc': name_enc}), 201)

    # ── refs / objects ───────────────────────────────────────────────────────
    def list_refs(self, repo_id: str) -> list[dict]:
        return self._check(self._request('GET', f'/v1/repos/{repo_id}/refs'), 200)

    def put_ref(self, repo_id: str, ref_id: str, name_enc: str, value_enc: str,
                expected_version: int) -> dict:
        r = self._request('PUT', f'/v1/repos/{repo_id}/refs/{ref_id}', json={
            'name_enc': name_enc, 'value_enc': value_enc,
            'expected_version': expected_version})
        if r.status_code == 409:
            raise RefConflict(r.json().get('detail', {}))
        return self._check(r, 200)

    def missing_objects(self, repo_id: str, ids: list[str]) -> list[str]:
        out: list[str] = []
        for i in range(0, len(ids), 500):
            r = self._request('POST', f'/v1/repos/{repo_id}/objects/missing',
                              json={'ids': ids[i:i + 500]})
            out.extend(self._check(r, 200)['missing'])
        return out

    def upload_objects(self, repo_id: str, objects: list[dict]) -> int:
        stored = 0
        for i in range(0, len(objects), 100):
            r = self._request('POST', f'/v1/repos/{repo_id}/objects',
                              json={'objects': objects[i:i + 100]})
            stored += self._check(r, 201)['stored']
        return stored

    def get_objects(self, repo_id: str, ids: list[str]) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(ids), 100):
            r = self._request('POST', f'/v1/repos/{repo_id}/objects/get',
                              json={'ids': ids[i:i + 100]})
            out.extend(self._check(r, 200)['objects'])
        return out


class RefConflict(CloudError):
    def __init__(self, detail: dict):
        self.current_version = detail.get('current_version', 0)
        self.value_enc = detail.get('value_enc')
        super().__init__('remote ref changed — pull first (memgit cloud sync)')
