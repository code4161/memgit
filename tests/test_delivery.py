"""v0.5.0 — cross-host delivery of the core guide + skill-seed ingestion.
Guarantees: dedicated memgit-owned files, user content never disturbed,
idempotent, host size caps respected."""

from pathlib import Path

import pytest

from memgit.delivery import (
    MARKER_START, MARKER_END, TARGETS_BY_LABEL,
    Target, is_present, deliver, build_seed, collect_skills, _upsert_marker_block,
)

BODY = "# Core operating guide\n\nUse the X skill for X.\n"


@pytest.fixture
def project(tmp_path):
    (tmp_path / "proj").mkdir()
    return tmp_path / "proj"


@pytest.fixture
def home(tmp_path):
    (tmp_path / "home").mkdir()
    return tmp_path / "home"


class TestDedicatedFiles:
    def test_cursor_gets_alwaysapply_frontmatter(self, project, home):
        (project / ".cursor").mkdir()
        deliver(project, BODY, home=home)
        mdc = (project / ".cursor/rules/memgit.mdc").read_text()
        assert mdc.startswith("---")
        assert "alwaysApply: true" in mdc
        assert "Use the X skill for X." in mdc

    def test_windsurf_gets_always_on_trigger(self, project, home):
        (project / ".windsurf").mkdir()
        deliver(project, BODY, home=home)
        md = (project / ".windsurf/rules/memgit.md").read_text()
        assert "trigger: always_on" in md

    def test_only_detected_hosts_written(self, project, home):
        (project / ".cursor").mkdir()  # only Cursor present
        results = {r.label: r for r in deliver(project, BODY, home=home)}
        assert "Cursor" in results
        assert "Roo Code" not in results  # no signature -> skipped

    def test_all_hosts_forces_every_target(self, project, home):
        labels = {r.label for r in deliver(project, BODY, all_hosts=True, home=home)}
        assert labels == set(TARGETS_BY_LABEL)

    def test_idempotent_second_write_is_unchanged(self, project, home):
        deliver(project, BODY, all_hosts=True, home=home)
        second = deliver(project, BODY, all_hosts=True, home=home)
        assert all(r.action == "unchanged" for r in second)


class TestSharedAgentsFile:
    def test_user_content_preserved_and_block_added(self, project, home):
        agents = project / "AGENTS.md"
        agents.write_text("# Mine\nUser instructions.\n")
        deliver(project, BODY, hosts=["Codex"], home=home)
        text = agents.read_text()
        assert "User instructions." in text          # preserved
        assert MARKER_START in text and MARKER_END in text
        assert "Use the X skill for X." in text

    def test_upsert_replaces_only_marked_region(self):
        existing = f"KEEP ME\n{MARKER_START}\nold\n{MARKER_END}\nKEEP ME TOO\n"
        out = _upsert_marker_block(existing, "new body")
        assert "KEEP ME" in out and "KEEP ME TOO" in out
        assert "old" not in out
        assert "new body" in out
        assert out.count(MARKER_START) == 1  # no duplicate block

    def test_upsert_tolerates_backslashes_in_body(self):
        out = _upsert_marker_block("", r"path\to\thing and \1 group")
        assert r"path\to\thing" in out


class TestDetection:
    def test_present_via_home_signature(self, project, home):
        (home / ".cursor").mkdir()
        assert is_present(TARGETS_BY_LABEL["Cursor"], project, home) is True

    def test_absent_when_no_signature(self, project, home):
        assert is_present(TARGETS_BY_LABEL["Roo Code"], project, home) is False


class TestSizeCap:
    def test_over_cap_is_flagged_not_written(self, project, home):
        (project / ".windsurf").mkdir()
        huge = "x" * 20000  # Windsurf cap is 12000
        results = {r.label: r for r in deliver(project, huge, hosts=["Windsurf"], home=home)}
        assert results["Windsurf"].action == "over-cap"
        assert not (project / ".windsurf/rules/memgit.md").exists()


class TestSeed:
    def test_seed_ingests_skill_name_and_description(self, project, home):
        skill = home / ".claude/skills/demo/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: demo\ndescription: Does a demo.\n---\nbody")
        seed = build_seed(project, home=home)
        assert "demo" in seed
        assert "Does a demo." in seed

    def test_seed_lists_existing_project_rules(self, project, home):
        (project / "CLAUDE.md").write_text("rules")
        seed = build_seed(project, home=home)
        assert "CLAUDE.md" in seed

    def test_collect_skills_project_overrides_home(self, project, home):
        for base, desc in ((home, "home version"), (project, "project version")):
            s = base / ".claude/skills/dup/SKILL.md"
            s.parent.mkdir(parents=True)
            s.write_text(f"---\nname: dup\ndescription: {desc}\n---")
        skills = dict(collect_skills(project, home=home))
        assert skills["dup"] == "project version"
