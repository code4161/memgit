"""The MCP server's self-cleanup and SDK compatibility guard (added 2026-09-06).

Two defects sat behind these tests. A stdio server lives as long as its host,
and an AI host stays open all day: measured on the developer's machine, six
servers with living parents aged over seven hours, two still holding 126 MB and
112 MB because nothing released the caches. And `mcp>=1.0.0` with no upper
bound resolved to the SDK's 2.x line, which removed the decorators this server
is built on, so every fresh install crashed before serving one request.
"""

import time

import pytest

from memgit import mcp_server as ms
from memgit import store


class TestOrphanDetection:
    def test_reparented_to_init_is_orphaned(self):
        assert ms.is_orphaned(ppid=1, original_ppid=4321) is True

    def test_living_parent_is_not_orphaned(self):
        assert ms.is_orphaned(ppid=4321, original_ppid=4321) is False

    def test_a_new_but_living_parent_is_not_orphaned(self):
        assert ms.is_orphaned(ppid=9999, original_ppid=4321) is False

    def test_a_server_started_by_init_is_never_called_orphaned(self):
        """Otherwise a daemonised install would shut itself down on first tick."""
        assert ms.is_orphaned(ppid=1, original_ppid=1) is False

    def test_unknown_original_parent_is_never_called_orphaned(self):
        assert ms.is_orphaned(ppid=1, original_ppid=None) is False


class TestIdleEviction:
    def test_evicts_once_past_the_threshold(self):
        assert ms.should_evict(1000.0, threshold=900.0) is True

    def test_does_not_evict_while_recently_used(self):
        assert ms.should_evict(10.0, threshold=900.0) is False

    def test_a_zero_threshold_disables_eviction(self):
        assert ms.should_evict(99999.0, threshold=0) is False


class TestHousekeepingTick:
    def setup_method(self):
        store.clear_object_cache()
        ms.note_activity()

    def teardown_method(self):
        store.clear_object_cache()

    def test_orphaned_beats_everything_else(self, monkeypatch):
        monkeypatch.setattr(ms, "_original_ppid", 4321)
        assert ms.housekeeping_tick(ppid=1) == "orphaned"

    def test_idle_with_a_populated_cache_evicts_it(self, monkeypatch):
        monkeypatch.setattr(ms, "_original_ppid", 4321)
        store.object_cache()["deadbeef"] = object()
        ms._last_activity = time.monotonic() - (ms.IDLE_EVICT_SECONDS + 1)
        assert ms.housekeeping_tick(ppid=4321) == "evicted"
        assert not store.object_cache()

    def test_idle_with_an_empty_cache_does_nothing(self, monkeypatch):
        monkeypatch.setattr(ms, "_original_ppid", 4321)
        ms._last_activity = time.monotonic() - (ms.IDLE_EVICT_SECONDS + 1)
        assert ms.housekeeping_tick(ppid=4321) == "idle"

    def test_a_busy_server_keeps_its_cache(self, monkeypatch):
        monkeypatch.setattr(ms, "_original_ppid", 4321)
        store.object_cache()["deadbeef"] = object()
        ms.note_activity()
        assert ms.housekeeping_tick(ppid=4321) == "idle"
        assert store.object_cache(), 'an in-use server must not lose its cache'

    def test_note_activity_defers_an_eviction_that_was_due(self, monkeypatch):
        monkeypatch.setattr(ms, "_original_ppid", 4321)
        store.object_cache()["deadbeef"] = object()
        ms._last_activity = time.monotonic() - (ms.IDLE_EVICT_SECONDS + 1)
        ms.note_activity()
        assert ms.housekeeping_tick(ppid=4321) == "idle"
        assert store.object_cache()


class TestSdkGuard:
    def test_passes_on_an_sdk_with_the_decorators(self):
        ms._require_compatible_sdk()   # the pinned SDK the tests run against

    def test_exits_with_a_readable_message_on_an_incompatible_sdk(self, monkeypatch, capsys):
        class Stripped:
            """An SDK Server with the 2.x surface: no list_tools, no call_tool."""

        monkeypatch.setattr(ms, "Server", Stripped)
        with pytest.raises(SystemExit) as exc:
            ms._require_compatible_sdk()
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "not compatible" in err
        assert "mcp>=1.0.0,<2" in err, 'the message must name the fix, not just the fault'
        assert "memgit-npm-venv" in err, 'the npm route breaks the same way and needs its own step'
