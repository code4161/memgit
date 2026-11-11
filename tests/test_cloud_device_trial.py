"""The cloud client names its store with a device id, and prints the trial from what
the server sends.

Since 2026-11-11 the server starts the 14-day trial at the second machine (or the first
teammate), counting distinct X-Memgit-Device ids, so a new account arrives with
trial_ends_at null. The client must send the same id on signup, login and refresh for
the life of the store, and must not print "trial until" a date that does not exist.
No network: httpx.MockTransport stands in for the API.
"""
import json
import time

import httpx
import pytest

from memgit.cloud.client import DEVICE_HEADER, ApiClient
from memgit.cloud.commands import trial_line
from memgit.cloud.state import CloudState
from memgit.repo import Repository

DAY = 86400


class Recorder:
    def __init__(self):
        self.seen: list[tuple[str, str | None]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.seen.append((request.url.path, request.headers.get(DEVICE_HEADER)))
        p = request.url.path
        tokens = {"access": "a2", "refresh": "r2"}
        if p == "/v1/auth/refresh":
            return httpx.Response(200, json=tokens)
        if p == "/v1/auth/signup":
            return httpx.Response(201, json={"user": {"id": "u"}, **tokens})
        if p == "/v1/auth/login":
            return httpx.Response(200, json={"user": {"id": "u"}, **tokens})
        if request.headers.get("Authorization") == "Bearer a2":
            return httpx.Response(200, json={"email": "x@y"})
        return httpx.Response(401, json={"detail": "expired"})


@pytest.fixture
def cstate(tmp_path):
    return CloudState(Repository.init(tmp_path / "store").path)


def _client(cstate, rec):
    api = ApiClient("https://api.test", cstate)
    api._http = httpx.Client(base_url="https://api.test", transport=httpx.MockTransport(rec.handler))
    return api


def test_device_id_is_made_once_and_survives_logout(cstate):
    first = cstate.device_id()
    assert len(first) == 32 and cstate.device_path.exists()
    assert (cstate.device_path.stat().st_mode & 0o777) == 0o600
    cstate.save_creds(access="a", refresh="r")
    cstate.clear_creds()
    assert cstate.device_id() == first


def test_two_stores_have_different_ids(tmp_path):
    a = CloudState(Repository.init(tmp_path / "a").path).device_id()
    b = CloudState(Repository.init(tmp_path / "b").path).device_id()
    assert a != b


def test_signup_login_and_refresh_send_the_same_device_id(cstate):
    rec = Recorder()
    api = _client(cstate, rec)
    api.signup("x@y", "k" * 16, "s" * 8, "pub", "priv")
    api.login("x@y", "k" * 16)
    cstate.save_creds(access="expired", refresh="r1")
    api.access, api.refresh = "expired", "r1"
    assert api.me() == {"email": "x@y"}
    by_path = {p: h for p, h in rec.seen}
    dev = cstate.device_id()
    assert by_path["/v1/auth/signup"] == dev
    assert by_path["/v1/auth/login"] == dev
    assert by_path["/v1/auth/refresh"] == dev
    # ordinary authenticated calls do not carry it
    assert [h for p, h in rec.seen if p == "/v1/me"] == [None, None]


def test_trial_line_before_the_trial_starts():
    deadline = int(time.time()) + 30 * DAY
    line = trial_line({"trial_ends_at": None, "trial_deadline_at": deadline, "trial_days": 14})
    day = time.strftime("%Y-%m-%d", time.localtime(deadline))
    assert line == ("The 14-day trial starts when a second machine connects to this account "
                    f"or a teammate joins your team, and on {day} if neither has happened by then.")
    assert "until" not in line and "left" not in line


def test_trial_line_once_started_and_after_it_ends():
    ends = int(time.time()) + 10 * DAY
    day = time.strftime("%Y-%m-%d", time.localtime(ends))
    assert trial_line({"trial_ends_at": ends}) == f"Trial runs until {day}."
    past = int(time.time()) - 2 * DAY
    assert trial_line({"trial_ends_at": past}).startswith("Trial ended ")


def test_trial_line_from_an_older_server_without_the_new_fields():
    assert trial_line({"trial_ends_at": None}).startswith("The 14-day trial starts when")
