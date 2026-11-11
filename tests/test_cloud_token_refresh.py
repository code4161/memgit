"""Two processes of one store must not log each other out.

Measured 2026-11-11: a commit started the background sync worker while a typed
`memgit cloud sync` ran; both found the access token expired, both presented
the same single-use refresh token, and the slower one reported "session
expired" on a session that was fine.
"""
import httpx
import pytest

from memgit.cloud.client import ApiClient, CloudError
from memgit.cloud.state import CloudState
from memgit.repo import Repository


class Server:
    """Rotating refresh tokens: each is accepted once."""
    def __init__(self):
        self.valid_refresh = {"r1"}
        self.valid_access = set()
        self.n = 1

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/auth/refresh":
            import json
            tok = json.loads(request.content)["refresh"]
            if tok not in self.valid_refresh:
                return httpx.Response(401, json={"detail": "refresh token revoked"})
            self.valid_refresh.discard(tok)
            self.n += 1
            self.valid_refresh.add(f"r{self.n}")
            self.valid_access.add(f"a{self.n}")
            return httpx.Response(200, json={"access": f"a{self.n}", "refresh": f"r{self.n}"})
        if request.headers.get("Authorization", "")[7:] in self.valid_access:
            return httpx.Response(200, json={"email": "x@y"})
        return httpx.Response(401, json={"detail": "expired"})


def _client(cstate, server) -> ApiClient:
    api = ApiClient("https://api.test", cstate)
    api._http = httpx.Client(base_url="https://api.test", transport=httpx.MockTransport(server.handler))
    return api


@pytest.fixture
def cstate(tmp_path):
    repo = Repository.init(tmp_path / "store")
    state = CloudState(repo.path)
    state.save_creds(access="a-expired", refresh="r1")
    return state


def test_the_second_process_adopts_the_tokens_the_first_one_saved(cstate):
    server = Server()
    worker, command = _client(cstate, server), _client(cstate, server)
    assert worker.me() == {"email": "x@y"}       # refreshes r1 -> r2 and saves it
    assert command.me() == {"email": "x@y"}      # still holds r1; must not say "session expired"
    assert cstate.creds["refresh"] in server.valid_refresh


def test_a_session_that_really_ended_still_says_so(cstate, monkeypatch):
    server = Server()
    server.valid_refresh.clear()
    monkeypatch.setattr("memgit.cloud.client.time.sleep", lambda s: None)
    with pytest.raises(CloudError, match="session expired"):
        _client(cstate, server).me()
