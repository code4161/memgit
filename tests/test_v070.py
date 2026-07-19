"""v0.7.0 tests — project isolation done right.

Thesis under test: recall is FILTER-by-default (a session sees its project
family + explicitly-global memories, nothing else), a save whose provenance
can't be determined is quarantined under `_unknown` rather than silently
becoming global, and the maintenance surfaces (`doctor`, cache GC, honest
stats, hook templates) keep the store trustworthy over months of real use.
"""

import io
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from memgit.models import Mnemonic
from memgit.project import (
    UNKNOWN_PROJECT,
    detect_project,
    project_affinity,
    same_project_family,
    scope_filter,
)
from memgit.repo import Repository

NOW = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)


def _mk(slug="test-mem", **kw):
    defaults = dict(type_code="pj", timestamp=NOW, rule="a rule", priority=2)
    defaults.update(kw)
    return Mnemonic(slug=slug, **defaults)


@pytest.fixture
def repo(tmp_path):
    return Repository.init(tmp_path / "store")


def _invoke(args, repo, monkeypatch, **kw):
    import memgit.cli as cli_mod
    monkeypatch.setattr(cli_mod, "_require_repo", lambda: repo)
    return CliRunner().invoke(cli_mod.cli, args, **kw)


# ── isolation semantics: explicit-global vs unknown provenance ───────────────

class TestUnknownProject:
    def test_unknown_never_family_matches_even_itself(self):
        assert same_project_family(UNKNOWN_PROJECT, UNKNOWN_PROJECT) is False
        assert same_project_family(UNKNOWN_PROJECT, "Any-Proj") is False
        assert same_project_family("Any-Proj", UNKNOWN_PROJECT) is False

    def test_unknown_affinity_is_zero_everywhere(self):
        assert project_affinity(UNKNOWN_PROJECT, UNKNOWN_PROJECT) == 0
        assert project_affinity(UNKNOWN_PROJECT, "X") == 0
        assert project_affinity("X", UNKNOWN_PROJECT) == 0

    def test_scope_filter_keeps_family_and_global_only(self):
        mems = [
            _mk("exact", project="My-Proj"),
            _mk("child", project="My-Proj-sub"),
            _mk("global", project=None),
            _mk("foreign", project="Other-Proj"),
            _mk("quarantined", project=UNKNOWN_PROJECT),
        ]
        scoped = {m.slug for m in scope_filter(mems, "My-Proj")}
        assert scoped == {"exact", "child", "global"}

    def test_scope_filter_without_project_is_identity(self):
        mems = [_mk("a", project="X"), _mk("b", project=UNKNOWN_PROJECT)]
        assert scope_filter(mems, None) == mems


class TestDetectProject:
    def test_env_wins_over_everything(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MEMGIT_PROJECT", "Forced")
        assert detect_project(cwd=tmp_path) == "Forced"

    def test_cwd_argument_beats_claude_project_dir(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR",
                           str(Path.home() / "Other" / "Place"))
        got = detect_project(cwd=Path.home() / "Freelance" / "BITS")
        assert got == "Freelance-BITS"

    def test_claude_project_dir_beats_process_cwd(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR",
                           str(Path.home() / "Freelance" / "BITS"))
        monkeypatch.setattr(Path, "cwd",
                            staticmethod(lambda: Path.home() / "Elsewhere"))
        assert detect_project() == "Freelance-BITS"

    def test_none_when_nothing_yields_a_label(self, monkeypatch):
        monkeypatch.setattr(Path, "cwd", staticmethod(lambda: Path.home()))
        assert detect_project() is None


class TestWriteSurfaceQuarantine:
    def test_cli_add_quarantines_when_undetectable(self, repo, monkeypatch):
        import memgit.project as project_mod
        monkeypatch.setattr(project_mod, "detect_project", lambda cwd=None: None)
        res = _invoke(["add", "orphan-fact", "some rule"], repo, monkeypatch)
        assert res.exit_code == 0, res.output
        assert repo.get("orphan-fact").project == UNKNOWN_PROJECT
        assert "quarantined" in res.output

    def test_cli_add_global_flag_is_explicit_global(self, repo, monkeypatch):
        res = _invoke(["add", "everywhere-fact", "applies everywhere",
                       "--global"], repo, monkeypatch)
        assert res.exit_code == 0, res.output
        assert repo.get("everywhere-fact").project is None

    def test_cli_add_global_and_project_are_exclusive(self, repo, monkeypatch):
        res = _invoke(["add", "x", "r", "--global", "--project", "P"],
                      repo, monkeypatch)
        assert res.exit_code != 0
        assert "mutually exclusive" in res.output

    def test_cli_add_detected_project_still_applied(self, repo, monkeypatch):
        import memgit.project as project_mod
        monkeypatch.setattr(project_mod, "detect_project",
                            lambda cwd=None: "My-Proj")
        res = _invoke(["add", "scoped-fact", "r"], repo, monkeypatch)
        assert res.exit_code == 0, res.output
        assert repo.get("scoped-fact").project == "My-Proj"

    def test_http_put_quarantines_and_empty_string_is_global(self, repo, monkeypatch):
        import memgit.http_server as http_mod
        import memgit.project as project_mod
        monkeypatch.setattr(http_mod, "_load_repo", lambda sp: repo)

        def put(slug, payload):
            handler = object.__new__(http_mod.MemgitHandler)
            handler.path = f"/memories/{slug}"
            raw = json.dumps(payload).encode()
            handler.rfile = io.BytesIO(raw)
            handler.headers = {"Content-Length": str(len(raw))}
            captured = {}
            handler._json_response = lambda data, status=200: captured.update(data)
            handler.do_PUT()
            return captured

        monkeypatch.setattr(project_mod, "detect_project", lambda cwd=None: None)
        out = put("http-orphan", {"rule": "no provenance"})
        assert repo.get("http-orphan").project == UNKNOWN_PROJECT
        assert any("quarantined" in w for w in out.get("warnings", []))

        out = put("http-global", {"rule": "explicitly global", "project": ""})
        assert repo.get("http-global").project is None
        assert "warnings" not in out

    def test_list_marks_unknown_and_lint_flags_it(self, repo, monkeypatch):
        repo.add(_mk("mystery", project=UNKNOWN_PROJECT))
        res = _invoke(["list"], repo, monkeypatch)
        assert "?project" in res.output
        lint = _invoke(["lint"], repo, monkeypatch)
        assert lint.exit_code == 1
        assert "unknown provenance" in lint.output


# ── filter-by-default recall + search ────────────────────────────────────────

class TestScopedScoring:
    def _pool(self):
        return [
            _mk("mine-zebpay", rule="zebpay stop orders need STOP_LIMIT",
                project="My-Proj", tags=["zebpay"]),
            _mk("sub-zebpay", rule="zebpay perp wallet funding note",
                project="My-Proj-sub", tags=["zebpay"]),
            _mk("global-zebpay", rule="zebpay caps INR withdrawals",
                project=None, tags=["zebpay"]),
            _mk("foreign-zebpay", rule="zebpay foreign project secret",
                project="Other-Proj", tags=["zebpay"]),
            _mk("quarantined-zebpay", rule="zebpay quarantined note",
                project=UNKNOWN_PROJECT, tags=["zebpay"]),
        ]

    def test_scope_project_prefilters_candidates(self):
        from memgit.scorer import score
        results = score("zebpay", self._pool(), top_k=10,
                        scope_project="My-Proj")
        slugs = {r.mnemonic.slug for r in results}
        assert slugs == {"mine-zebpay", "sub-zebpay", "global-zebpay"}

    def test_no_scope_returns_everything(self):
        from memgit.scorer import score
        results = score("zebpay", self._pool(), top_k=10)
        assert len(results) == 5

    def test_cli_search_scoped_by_default_and_all_projects_widens(
            self, repo, monkeypatch):
        import memgit.project as project_mod
        monkeypatch.setattr(project_mod, "detect_project",
                            lambda cwd=None: "My-Proj")
        for m in self._pool():
            repo.add(m)
        res = _invoke(["search", "zebpay"], repo, monkeypatch)
        assert "mine-zebpay" in res.output
        assert "foreign-zebpay" not in res.output
        assert "quarantined-zebpay" not in res.output

        res_all = _invoke(["search", "zebpay", "--all-projects", "--json"],
                          repo, monkeypatch)
        out = json.loads(res_all.output)
        by_slug = {r["slug"]: r for r in out}
        assert "foreign-zebpay" in by_slug
        # every hit carries its project label
        assert by_slug["foreign-zebpay"]["project"] == "Other-Proj"
        assert by_slug["global-zebpay"]["project"] is None

    def test_cli_search_project_stays_hard_filter(self, repo, monkeypatch):
        import memgit.project as project_mod
        monkeypatch.setattr(project_mod, "detect_project",
                            lambda cwd=None: "My-Proj")
        for m in self._pool():
            repo.add(m)
        res = _invoke(["search", "zebpay", "--project", "Other-Proj", "--json"],
                      repo, monkeypatch)
        out = json.loads(res.output)
        assert [r["slug"] for r in out] == ["foreign-zebpay"]

    def test_prompt_recall_scoped_pool_and_hint(self, repo, monkeypatch, capsys):
        """Foreign memories neither inject nor inflate the depth hint."""
        from memgit.hooks import prompt_recall
        import memgit.hooks as hooks_mod
        repo.add(_mk("global-zebpay", rule="ZebPay caps INR withdrawals at 10L/day",
                     tags=["zebpay"]))
        for i in range(4):
            repo.add(_mk(f"foreign-zebpay-{i}", rule=f"other zebpay detail {i}",
                         project="Other-Proj", tags=["zebpay"]))
        repo.commit(message="seed")
        monkeypatch.setenv("MEMGIT_PROJECT", "My-Proj")
        monkeypatch.setattr(hooks_mod, "_find_repo", lambda: repo)
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
            "prompt": "what are the zebpay withdrawal caps and limits?",
            "cwd": "/tmp", "session_id": "scope1"})))
        prompt_recall()
        out = capsys.readouterr().out
        assert "global-zebpay" in out
        assert "foreign-zebpay" not in out
        # 4 on-topic memories exist store-wide, but ALL are foreign — a
        # depth hint advertising them would lead a scoped search nowhere.
        assert "more saved on" not in out


class TestScopedResumeCheckpoints:
    def _seed(self, repo):
        repo.add(_mk("a-fact", project="Proj-A"))
        repo.commit(message="save: a-fact [pj]")
        repo.add(_mk("b-fact", project="Proj-B"))
        repo.commit(message="save: b-fact [pj]")
        repo.add(_mk("g-fact", project=None))
        repo.commit(message="save: g-fact [pj]")

    def test_checkpoints_scoped_to_project_family_plus_global(self, repo):
        self._seed(repo)
        msgs = [c["message"] for c in
                repo.resume_context(project="Proj-A")["checkpoints"]]
        assert any("a-fact" in m for m in msgs)
        assert any("g-fact" in m for m in msgs)
        assert not any("b-fact" in m for m in msgs)

    def test_unresolvable_checkpoints_dropped_when_scoped(self, repo):
        self._seed(repo)
        repo.remove("b-fact")
        repo.commit(message="drop b")  # removal: b-fact no longer resolvable
        msgs = [c["message"] for c in
                repo.resume_context(project="Proj-A")["checkpoints"]]
        assert "drop b" not in msgs
        assert "Initial checkpoint" not in msgs  # empty diff → unresolvable

    def test_no_project_keeps_full_history(self, repo):
        self._seed(repo)
        msgs = [c["message"] for c in
                repo.resume_context(project=None)["checkpoints"]]
        assert any("b-fact" in m for m in msgs)
        assert "Initial checkpoint" in msgs

    def test_bulk_commit_kept_if_any_slug_is_ours(self, repo):
        repo.add(_mk("a-fact", project="Proj-A"))
        repo.add(_mk("b-fact", project="Proj-B"))
        repo.commit(message="sync: +2 (a-fact, b-fact)")
        msgs = [c["message"] for c in
                repo.resume_context(project="Proj-A")["checkpoints"]]
        assert msgs == ["sync: +2 (a-fact, b-fact)"]


class TestTagmapUnknown:
    def test_unknown_has_own_key_and_is_never_counted(self, repo):
        from memgit.links import read_tagmap, tagmap_count
        repo.add(_mk("g1", tags=["topic"]))
        repo.add(_mk("g2", tags=["topic"]))
        repo.add(_mk("q1", tags=["topic"], project=UNKNOWN_PROJECT))
        repo.commit(message="seed")
        tm = read_tagmap(repo)
        assert tm["topic"].get(UNKNOWN_PROJECT) == 1   # own bucket, not ""
        assert tm["topic"].get("") == 2                 # explicit-global bucket
        assert tagmap_count(tm, "topic", "Any-Proj") == 2
        assert tagmap_count(tm, "topic", None) == 2

    def test_entity_index_excludes_unknown(self):
        from memgit.links import entity_index
        mems = ([_mk(f"g{i}", tags=["topic"]) for i in range(2)]
                + [_mk(f"q{i}", tags=["topic"], project=UNKNOWN_PROJECT)
                   for i in range(5)])
        assert entity_index(mems, None) == [("topic", 2)]
        assert entity_index(mems, "Some-Proj") == [("topic", 2)]


# ── core-guide + setup fixes ─────────────────────────────────────────────────

class TestHookTemplate:
    @pytest.fixture
    def fake_home(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        return home

    def test_stop_sync_hook_has_no_cd_prefix(self, fake_home):
        from memgit import cli as cli_mod
        res = CliRunner().invoke(cli_mod.cli, ["setup", "hooks"])
        assert res.exit_code == 0, res.output
        data = json.loads((fake_home / ".claude" / "settings.json").read_text())
        stop_cmds = [inner["command"]
                     for entry in data["hooks"]["Stop"]
                     for inner in entry["hooks"]]
        sync_cmds = [c for c in stop_cmds if " sync" in c]
        assert sync_cmds, stop_cmds
        assert all(not c.startswith("cd ") for c in sync_cmds)

    def test_base_cmd_uses_argv0_only_when_it_is_memgit(self, tmp_path, monkeypatch):
        from memgit.cli import _memgit_base_cmd
        binary = tmp_path / "memgit"
        binary.write_text("#!/bin/sh\n")
        monkeypatch.setattr("sys.argv", [str(binary), "setup", "hooks"])
        got = _memgit_base_cmd()
        assert got == [os.path.realpath(str(binary))]

    def test_base_cmd_falls_back_which_then_module(self, tmp_path, monkeypatch):
        import sys
        from memgit import cli as cli_mod
        monkeypatch.setattr("sys.argv", ["pytest"])  # not a memgit binary
        which_binary = tmp_path / "memgit"
        which_binary.write_text("#!/bin/sh\n")
        monkeypatch.setattr(cli_mod._shutil, "which",
                            lambda name: str(which_binary))
        assert cli_mod._memgit_base_cmd() == [os.path.realpath(str(which_binary))]
        monkeypatch.setattr(cli_mod._shutil, "which", lambda name: None)
        assert cli_mod._memgit_base_cmd() == [sys.executable, "-m", "memgit.cli"]


class TestStoreSelfCoreGuard:
    def test_refresh_skips_when_project_is_the_store(self, repo, monkeypatch):
        from memgit.cli import _refresh_core, _project_is_store
        from memgit.project import project_label_from_path
        store_label = project_label_from_path(repo.path.parent)
        assert store_label  # tmp store has a real label
        # a core guide staged FOR the store label must never auto-refresh
        repo.add(_mk(f"core-{store_label}", type_code="co",
                     project=store_label, body="guide"))
        assert _project_is_store(repo, store_label) is True
        assert _project_is_store(repo, store_label + "-memories") is True
        assert _project_is_store(repo, "Innocent-Proj") is False
        assert _refresh_core(repo, store_label) is False


class TestGeminiDelivery:
    def test_gemini_target_is_marker_block_in_gemini_md(self, tmp_path):
        from memgit.delivery import MARKER_START, MARKER_END, deliver
        project = tmp_path / "proj"
        (project / ".gemini").mkdir(parents=True)
        home = tmp_path / "home"
        home.mkdir()
        (project / "GEMINI.md").write_text("# Mine\nUser Gemini notes.\n")
        deliver(project, "GUIDE BODY", hosts=["Gemini CLI"], home=home)
        text = (project / "GEMINI.md").read_text()
        assert "User Gemini notes." in text
        assert MARKER_START in text and MARKER_END in text
        assert "GUIDE BODY" in text
        assert not (project / ".gemini" / "memgit.md").exists()

    def test_legacy_inert_file_deleted_on_sync(self, tmp_path):
        from memgit.delivery import deliver
        project = tmp_path / "proj"
        legacy = project / ".gemini" / "memgit.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("old inert guide")
        home = tmp_path / "home"
        home.mkdir()
        deliver(project, "BODY", hosts=["Gemini CLI"], home=home)
        assert not legacy.exists()
        assert (project / "GEMINI.md").exists()

    def test_gemini_created_when_usage_detected(self, tmp_path):
        from memgit.delivery import deliver
        project = tmp_path / "proj"
        (project / ".gemini").mkdir(parents=True)  # Gemini usage signature
        home = tmp_path / "home"
        home.mkdir()
        results = {r.label: r for r in deliver(project, "BODY", home=home)}
        assert results["Gemini CLI"].action == "created"
        assert (project / "GEMINI.md").exists()


class TestFrontmatterField:
    def test_folded_scalar_joins_all_lines(self):
        from memgit.delivery import _frontmatter_field
        text = ("---\nname: demo\ndescription: >-\n"
                "  First line of the description\n"
                "  and the second line too.\nallowed: x\n---\nbody")
        assert _frontmatter_field(text, "description") == \
            "First line of the description and the second line too."
        assert _frontmatter_field(text, "name") == "demo"

    def test_plain_multiline_value_joined(self):
        from memgit.delivery import _frontmatter_field
        text = ("---\ndescription: Starts here\n"
                "  continues indented here.\nname: demo\n---\n")
        assert _frontmatter_field(text, "description") == \
            "Starts here continues indented here."

    def test_literal_scalar_with_blank_line(self):
        from memgit.delivery import _frontmatter_field
        text = ("---\ndescription: |\n  Para one.\n\n  Para two.\n---\n")
        assert _frontmatter_field(text, "description") == "Para one. Para two."

    def test_single_line_still_works(self):
        from memgit.delivery import _frontmatter_field
        text = '---\ndescription: "Just one line."\n---\n'
        assert _frontmatter_field(text, "description") == "Just one line."


# ── token-efficiency + hygiene ───────────────────────────────────────────────

class TestResumeBudget:
    def test_large_store_digest_under_budget(self, repo):
        from memgit.cli import RESUME_BUDGET_CHARS, _format_resume_plain
        core_body = "## Core guide\n" + ("Navigation line that must survive. "
                                         * 60)
        repo.add(_mk("core-Big-Proj", type_code="co", project="Big-Proj",
                     body=core_body, rule="core operating guide"))
        for i in range(60):
            repo.add(_mk(
                f"memory-with-a-long-slug-{i}", project="Big-Proj",
                rule=f"fact {i}: " + "quite a lot of detail here " * 12,
                tags=[f"topic{i % 9}", "shared"],
                priority=3 if i % 3 == 0 else 2,
            ))
        for i in range(8):
            repo.add(_mk(f"entity-{i}-status", type_code="tr",
                         project="Big-Proj", rule="live state " * 10))
        repo.commit(message="seed")
        ctx = repo.resume_context(project="Big-Proj")
        text = _format_resume_plain(ctx)
        assert len(text) < RESUME_BUDGET_CHARS, len(text)
        # the core guide body and the status board are never trimmed
        assert "Navigation line that must survive." in text
        assert "## Status board" in text
        # and the caller's ctx is not mutated by trimming
        assert len(ctx["recent_memories"]) == 10

    def test_small_store_untrimmed(self, repo):
        from memgit.cli import _format_resume_plain
        repo.add(_mk("only-fact"))
        repo.commit(message="seed")
        text = _format_resume_plain(repo.resume_context())
        assert "only-fact" in text


class TestCacheGC:
    def _age_file(self, path, days):
        old = time.time() - days * 86400
        os.utime(path, (old, old))

    def test_gc_caches_sweeps_only_old_files(self, repo):
        d = repo.path / "cache" / "recall"
        d.mkdir(parents=True)
        (d / "ancient-session").write_text("x")
        (d / "fresh-session").write_text("y")
        self._age_file(d / "ancient-session", 45)
        deleted = repo.gc_caches()
        assert deleted == 1
        assert not (d / "ancient-session").exists()
        assert (d / "fresh-session").exists()

    def test_repo_gc_reports_cache_sweep(self, repo):
        d = repo.path / "cache" / "stop-guard"
        d.mkdir(parents=True)
        (d / "old").write_text("x")
        self._age_file(d / "old", 40)
        result = repo.gc()
        assert result["cache_files_deleted"] == 1

    def test_sync_runs_cache_gc_best_effort(self, repo, monkeypatch):
        d = repo.path / "cache" / "ctx-recall"
        d.mkdir(parents=True)
        (d / "stale").write_text("x")
        self._age_file(d / "stale", 40)
        monkeypatch.setattr("memgit.importer.from_claude_code", lambda: [])
        res = _invoke(["sync"], repo, monkeypatch)
        assert res.exit_code == 0, res.output
        assert not (d / "stale").exists()


class TestHonestStats:
    def test_cli_stats_renders_measured_numbers_only(self, repo, monkeypatch):
        for i in range(5):
            repo.add(_mk(f"m{i}", rule=f"rule number {i} with words"))
        repo.commit(message="seed")
        res = _invoke(["stats"], repo, monkeypatch)
        assert res.exit_code == 0, res.output
        assert "per-session injected" in res.output
        assert "estimate" in res.output
        # the fabricated block is gone
        for phrase in ("Weekly savings", "Annualised", "GPT-4o",
                       "dump all memories"):
            assert phrase not in res.output


class TestDoctor:
    def test_report_names_unknown_global_stale_and_orphans(self, repo, monkeypatch):
        from memgit.usage import record_hits
        repo.add(_mk("quarantined-one", project=UNKNOWN_PROJECT, tags=["alpha"]))
        repo.add(_mk("global-one", project=None, tags=["beta"]))
        repo.commit(message="seed")
        record_hits(repo, ["quarantined-one", "ghost-slug"])
        d = repo.path / "cache" / "recall"
        d.mkdir(parents=True)
        (d / "old").write_text("x")
        old = time.time() - 40 * 86400
        os.utime(d / "old", (old, old))
        res = _invoke(["doctor"], repo, monkeypatch)
        assert res.exit_code == 0, res.output
        assert "1 quarantined" in res.output
        assert "alpha" in res.output
        assert "1 explicitly global" in res.output
        assert "1 session-cache file(s)" in res.output
        assert "ghost-slug" in res.output

    def test_relabel_changes_only_project(self, repo, monkeypatch, tmp_path):
        ts = NOW - timedelta(days=30)
        repo.add(_mk("mislabeled", project=UNKNOWN_PROJECT, timestamp=ts,
                     rule="the fact", why="because", tags=["x", "y"],
                     body="full\ndetail", priority=3))
        repo.add(_mk("should-be-global", project="Wrong-Proj", timestamp=ts))
        repo.commit(message="seed")
        cks_before = len(repo.log(limit=100))

        mapping = tmp_path / "map.json"
        mapping.write_text(json.dumps({
            "mislabeled": "Right-Proj",
            "should-be-global": "",
            "no-such-slug": "X",
        }))
        res = _invoke(["doctor", "--relabel", str(mapping)], repo, monkeypatch)
        assert res.exit_code == 0, res.output
        assert "relabeled 2 memories" in res.output
        assert "no-such-slug" in res.output  # per-slug summary names the skip

        m = repo.get("mislabeled")
        assert m.project == "Right-Proj"
        assert m.timestamp == ts            # original timestamp preserved
        assert (m.rule, m.why, m.tags, m.body, m.priority) == \
            ("the fact", "because", ["x", "y"], "full\ndetail", 3)
        assert repo.get("should-be-global").project is None
        # exactly ONE checkpoint for the whole relabel
        cks = repo.log(limit=100)
        assert len(cks) == cks_before + 1
        assert cks[0].message == "doctor: relabel 2 memories"

    def test_prune_usage_and_sessions(self, repo, monkeypatch):
        from memgit.usage import read_usage, record_hits
        record_hits(repo, ["keep-me", "drop-me"])
        d = repo.path / "cache" / "recall"
        d.mkdir(parents=True)
        (d / "test-session-artifact").write_text("x")
        res = _invoke(["doctor", "--prune-usage", "drop-me",
                       "--prune-session", "test-session-artifact"],
                      repo, monkeypatch)
        assert res.exit_code == 0, res.output
        assert set(read_usage(repo)) == {"keep-me"}
        assert not (d / "test-session-artifact").exists()


class TestStoreEnvIsolation:
    def test_memgit_store_env_is_the_only_candidate(self, monkeypatch, tmp_path):
        from memgit.repo import default_store_candidates
        monkeypatch.setenv("MEMGIT_STORE", str(tmp_path / "s"))
        assert default_store_candidates() == [tmp_path / "s"]

    def test_hooks_find_repo_honors_env(self, monkeypatch, tmp_path):
        from memgit.hooks import _find_repo
        store = tmp_path / "env-store"
        Repository.init(store)
        monkeypatch.setenv("MEMGIT_STORE", str(store))
        found = _find_repo()
        assert found is not None
        assert found.path == store / ".memgit"
