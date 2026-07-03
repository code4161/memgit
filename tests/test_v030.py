"""v0.3.0 tests — lossless body, project scoping, onboarding, import quality."""

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from memgit.cli import cli
from memgit.importer import (
    _parse_md,
    _project_label_from_munged,
    from_claude_code,
    project_label_from_path,
)
from memgit.models import Mnemonic
from memgit.repo import Repository
from memgit.scorer import score
from memgit.toon import (
    _esc,
    _unesc,
    mnemonic_to_markdown,
    parse_toon,
    serialize_mnemonic,
)


NOW = datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc)


def _mk(slug="test-mem", **kw):
    defaults = dict(type_code="pj", timestamp=NOW, rule="a rule", priority=2)
    defaults.update(kw)
    return Mnemonic(slug=slug, **defaults)


@pytest.fixture
def repo(tmp_path):
    return Repository.init(tmp_path)


# ── TOON escaping + new fields ───────────────────────────────────────────────

class TestToonEscaping:
    def test_esc_unesc_roundtrip(self):
        for s in ["plain", "two\nlines", "back\\slash", "mix\\n literal\nand real",
                  "trailing\\", "\n\n\n", "a\\\\nb"]:
            assert _unesc(_esc(s)) == s

    def test_multiline_body_roundtrip(self):
        body = "## Heading\n\n- point one\n- point two\n\ncode `x\\y`"
        m = _mk(body=body, project="Personal-business")
        parsed = parse_toon(serialize_mnemonic(m))[0]
        assert parsed.body == body
        assert parsed.project == "Personal-business"

    def test_multiline_rule_roundtrip(self):
        m = _mk(rule="line1\nline2")
        parsed = parse_toon(serialize_mnemonic(m))[0]
        assert parsed.rule == "line1\nline2"

    def test_canonical_roundtrip_with_body(self):
        m = _mk(body="detail\nmore", project="X", desc="a desc")
        parsed = parse_toon(serialize_mnemonic(m, canonical=True))[0]
        assert parsed.body == "detail\nmore"
        assert parsed.project == "X"
        assert parsed.desc == "a desc"

    def test_old_shape_sha_stable(self):
        """Memories without body/project/backslashes serialize exactly as v0.2."""
        m = _mk(rule="simple rule", why="because", tags=["a", "b"])
        out = serialize_mnemonic(m, canonical=True)
        assert "BODY" not in out and "PROJ" not in out and "\\" not in out

    def test_markdown_export_uses_body(self):
        m = _mk(body="full **body** here\n\nwith paragraphs", desc="short desc")
        md = mnemonic_to_markdown(m)
        assert "full **body** here" in md
        assert "description: short desc" in md


# ── project labels ───────────────────────────────────────────────────────────

class TestProjectLabels:
    def test_munged_label_strips_home(self):
        home_munged = str(Path.home()).replace("/", "-").replace(".", "-").replace(" ", "-")
        assert _project_label_from_munged(f"{home_munged}-Freelance-BITS") == "Freelance-BITS"

    def test_munged_label_foreign_prefix(self):
        assert _project_label_from_munged("-opt-work-thing") == "opt-work-thing"

    def test_label_from_path(self):
        label = project_label_from_path(Path.home() / "Freelance" / "BITS")
        assert label == "Freelance-BITS"

    def test_label_from_path_with_space_and_dot(self):
        label = project_label_from_path(Path.home() / "Personal business")
        assert label == "Personal-business"

    def test_home_itself_is_none(self):
        assert project_label_from_path(Path.home()) is None


# ── importer quality ─────────────────────────────────────────────────────────

MD = """---
name: crypto-module
description: separate crypto workspace on Binance
metadata:
  type: project
---

New `crypto/` workspace module, **separate from `trading/`**.

**Why:** 24/7 market needs its own capital pool.

## Detail section

Long detail line one.
Long detail line two with specifics that must survive.
"""


class TestImporter:
    def test_full_body_kept(self, tmp_path):
        f = tmp_path / "crypto-module.md"
        f.write_text(MD)
        m = _parse_md(f, project="Personal-business")
        assert m.body is not None
        assert "must survive" in m.body
        assert m.desc == "separate crypto workspace on Binance"
        assert m.project == "Personal-business"
        assert m.source == str(f)
        assert "\n" not in m.rule  # rule stays a one-liner

    def test_tags_derived_from_project(self, tmp_path):
        f = tmp_path / "x.md"
        f.write_text(MD)
        m = _parse_md(f, project="Freelance-BITS")
        assert "freelance" in m.tags and "bits" in m.tags
        assert "pj" not in m.tags  # no type-code junk tags

    def test_priority_frontmatter(self, tmp_path):
        f = tmp_path / "y.md"
        f.write_text(MD.replace("metadata:", "priority: critical\nmetadata:"))
        m = _parse_md(f)
        assert m.priority == 3

    def test_tiny_body_omitted(self, tmp_path):
        f = tmp_path / "z.md"
        f.write_text("---\nname: z\ndescription: d\n---\n\nshort fact")
        m = _parse_md(f)
        assert m.body is None

    def test_from_claude_code_sets_project(self, tmp_path, monkeypatch):
        home_munged = str(Path.home()).replace("/", "-").replace(".", "-").replace(" ", "-")
        proj_dir = tmp_path / f"{home_munged}-MyProj" / "memory"
        proj_dir.mkdir(parents=True)
        (proj_dir / "fact.md").write_text(MD)
        mems = from_claude_code(proj_dir)
        assert len(mems) == 1
        assert mems[0].project == "MyProj"


# ── scorer ───────────────────────────────────────────────────────────────────

class TestScorer:
    def test_body_is_searchable(self):
        hit = _mk("with-body", rule="generic thing", body="zebpay decimal string quirk")
        miss = _mk("no-body", rule="generic thing")
        results = score("zebpay decimal", [hit, miss], top_k=5)
        assert results and results[0].mnemonic.slug == "with-body"

    def test_project_boost_orders_ties(self):
        a = _mk("same-a", rule="deploy uses rsync", project="ProjA")
        b = _mk("same-b", rule="deploy uses rsync", project="ProjB")
        results = score("deploy rsync", [a, b], top_k=2, boost_project="ProjB")
        assert results[0].mnemonic.slug == "same-b"

    def test_no_boost_without_project(self):
        a = _mk("a", rule="deploy uses rsync")
        results = score("deploy", [a], top_k=1, boost_project=None)
        assert results


# ── repo: resume project-awareness, stats ────────────────────────────────────

class TestRepoProject:
    def test_resume_prefers_project(self, repo):
        repo.add(_mk("other-1", rule="other project mem", project="Other",
                     timestamp=datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)))
        repo.add(_mk("mine-1", rule="my project mem", project="Mine",
                     timestamp=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)))
        repo.commit("seed")
        ctx = repo.resume_context(project="Mine")
        assert ctx["project"] == "Mine"
        assert ctx["recent_memories"][0]["slug"] == "mine-1"  # older but mine → first

    def test_resume_no_project_matches_falls_back(self, repo):
        repo.add(_mk("g-1", rule="global"))
        repo.commit("seed")
        ctx = repo.resume_context(project="Nothing-Here")
        assert ctx["recent_memories"][0]["slug"] == "g-1"

    def test_stats_by_project(self, repo):
        repo.add(_mk("a", project="P1"))
        repo.add(_mk("b", project="P1"))
        repo.add(_mk("c"))
        repo.commit("seed")
        s = repo.stats()
        assert s["by_project"] == {"P1": 2, "(global)": 1}

    def test_body_persists_through_store(self, repo):
        repo.add(_mk("deep", body="line1\nline2\nline3"))
        repo.commit("seed")
        got = repo.get("deep")
        assert got.body == "line1\nline2\nline3"


# ── CLI: onboard, add --body/--project, collision staging ───────────────────

class TestCli:
    def _runner_repo(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        Repository.init(tmp_path)
        return CliRunner()

    def test_onboard_prints_brief(self, tmp_path, monkeypatch):
        r = self._runner_repo(tmp_path, monkeypatch)
        res = r.invoke(cli, ["onboard", "--project", "MyProj"])
        assert res.exit_code == 0
        assert "bootstrap memory for MyProj" in res.output
        assert "blank slate" in res.output
        assert "save_memory" in res.output

    def test_onboard_counts_existing(self, tmp_path, monkeypatch):
        r = self._runner_repo(tmp_path, monkeypatch)
        repo = Repository.find(tmp_path)
        repo.add(_mk("x", project="MyProj"))
        res = r.invoke(cli, ["onboard", "--project", "MyProj"])
        assert "has 1 memories" in res.output
        assert "blank slate" not in res.output

    def test_add_with_body_and_project(self, tmp_path, monkeypatch):
        r = self._runner_repo(tmp_path, monkeypatch)
        res = r.invoke(cli, ["add", "my-fact", "the rule",
                             "--body", "long\ndetail", "--project", "P1"])
        assert res.exit_code == 0
        repo = Repository.find(tmp_path)
        m = repo.get("my-fact")
        assert m.body == "long\ndetail"
        assert m.project == "P1"

    def test_stage_imported_collision_reslugs(self, tmp_path, monkeypatch):
        from memgit.cli import _stage_imported
        monkeypatch.chdir(tmp_path)
        repo = Repository.init(tmp_path)
        repo.add(_mk("auth-decision", rule="proj A auth", project="ProjA"))
        incoming = [_mk("auth-decision", rule="proj B auth", project="ProjB")]
        count, skipped, renamed = _stage_imported(repo, incoming)
        assert count == 1 and skipped == 0
        assert renamed == ["auth-decision--projb"]
        assert repo.get("auth-decision").project == "ProjA"
        assert repo.get("auth-decision--projb").rule == "proj B auth"

    def test_stage_imported_same_project_updates(self, tmp_path, monkeypatch):
        from memgit.cli import _stage_imported
        monkeypatch.chdir(tmp_path)
        repo = Repository.init(tmp_path)
        repo.add(_mk("fact", rule="old", project="P"))
        _stage_imported(repo, [_mk("fact", rule="new", project="P")])
        assert repo.get("fact").rule == "new"

    def test_sync_auto_message_names_changes(self, tmp_path, monkeypatch):
        from memgit.cli import _staged_diff_message
        monkeypatch.chdir(tmp_path)
        repo = Repository.init(tmp_path)
        repo.add(_mk("brand-new", rule="x"))
        msg = _staged_diff_message(repo)
        assert msg == "sync: +1 (brand-new)"


# ── MCP project detection ────────────────────────────────────────────────────

class TestMcpDetect:
    def test_env_override(self, monkeypatch):
        from memgit.mcp_server import _detect_project
        monkeypatch.setenv("MEMGIT_PROJECT", "Forced-Label")
        assert _detect_project() == "Forced-Label"

    def test_cwd_detection(self, monkeypatch, tmp_path):
        from memgit.mcp_server import _detect_project
        monkeypatch.delenv("MEMGIT_PROJECT", raising=False)
        target = Path.home() / "Freelance" / "BITS"
        monkeypatch.setattr(Path, "cwd", staticmethod(lambda: target))
        assert _detect_project() == "Freelance-BITS"
