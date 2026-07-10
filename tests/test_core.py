"""v0.5.0 — core operating guide (type 'co'): always-injected, full-body,
per-project scoped, and explicitly subordinate to the repo's own rules."""

from datetime import datetime, timezone

import pytest

from memgit.cli import _format_resume_plain
from memgit.models import Mnemonic
from memgit.repo import Repository
from memgit.toon import serialize_mnemonic, parse_toon

NOW = datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def repo(tmp_path):
    return Repository.init(tmp_path)


def _core(project, body="Use `memgit search` first. For X use the X skill."):
    return Mnemonic(
        type_code="co", slug=f"core-{project}", timestamp=NOW,
        rule="core operating guide", body=body, project=project, priority=2,
    )


class TestCoreType:
    def test_co_is_a_valid_type_roundtrips_through_toon(self):
        m = _core("Alpha")
        back = parse_toon(serialize_mnemonic(m))[0]
        assert back.type_code == "co"
        assert back.body == m.body


class TestResumeSelection:
    def test_core_surfaced_full_body_for_its_project(self, repo):
        repo.add(_core("Alpha", body="LINE ONE\nLINE TWO\nLINE THREE"))
        repo.commit(message="seed")
        ctx = repo.resume_context(project="Alpha")
        assert len(ctx["core_memories"]) == 1
        # full body, not the clipped rule
        assert ctx["core_memories"][0]["body"] == "LINE ONE\nLINE TWO\nLINE THREE"

    def test_core_is_per_project_scoped(self, repo):
        repo.add(_core("Alpha"))
        repo.commit(message="seed")
        # a session in a DIFFERENT project must not see Alpha's core
        ctx = repo.resume_context(project="Beta")
        assert ctx["core_memories"] == []

    def test_core_matches_project_family(self, repo):
        repo.add(_core("BITS"))
        repo.commit(message="seed")
        # a subproject in the same family counts the family core as its own
        ctx = repo.resume_context(project="BITS-bits_back")
        assert len(ctx["core_memories"]) == 1


class TestResumeRendering:
    def test_render_puts_core_first_with_precedence_header(self, repo):
        repo.add(_core("Alpha", body="ROUTING GUIDE BODY"))
        repo.commit(message="seed")
        text = _format_resume_plain(repo.resume_context(project="Alpha"))
        assert "## Core operating guide — always apply" in text
        assert "THOSE win" in text  # subordinate-to-repo-rules disclaimer
        assert "ROUTING GUIDE BODY" in text
        # core block appears before the checkpoints section
        assert text.index("ROUTING GUIDE BODY") < text.index("## Last checkpoints")

    def test_no_core_renders_no_section(self, repo):
        repo.add(Mnemonic(type_code="pj", slug="x", timestamp=NOW, rule="r"))
        repo.commit(message="seed")
        text = _format_resume_plain(repo.resume_context(project="Alpha"))
        assert "Core operating guide" not in text
