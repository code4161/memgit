"""v0.4.1 — command aliases + did-you-mean on the root group."""

from datetime import datetime, timezone

import pytest
from click.testing import CliRunner

from memgit import cli as cli_mod
from memgit.models import Mnemonic
from memgit.repo import Repository

NOW = datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def repo(tmp_path):
    return Repository.init(tmp_path)


def _mk(slug, **kw):
    defaults = dict(type_code="pj", timestamp=NOW, rule="a rule", priority=2)
    defaults.update(kw)
    return Mnemonic(slug=slug, **defaults)


class TestDeleteAlias:
    @pytest.mark.parametrize("verb", ["delete", "rm", "del"])
    def test_alias_removes_like_remove(self, verb, repo, monkeypatch):
        repo.add(_mk("doomed-fact"))
        monkeypatch.setattr(cli_mod, "_require_repo", lambda: repo)

        result = CliRunner().invoke(cli_mod.cli, [verb, "doomed-fact"])

        assert result.exit_code == 0
        assert "removed" in result.output
        assert "doomed-fact" not in repo.get_index()

    def test_alias_miss_matches_remove_wording(self, repo, monkeypatch):
        monkeypatch.setattr(cli_mod, "_require_repo", lambda: repo)
        result = CliRunner().invoke(cli_mod.cli, ["delete", "never-existed"])
        assert result.exit_code == 0
        assert "not found" in result.output


class TestDidYouMean:
    def test_typo_suggests_closest_command(self):
        result = CliRunner().invoke(cli_mod.cli, ["remve", "x"])
        assert result.exit_code == 2
        assert "Did you mean 'remove'?" in result.output

    def test_far_typo_suggests_search(self):
        result = CliRunner().invoke(cli_mod.cli, ["serch"])
        assert result.exit_code == 2
        assert "Did you mean 'search'?" in result.output

    def test_garbage_gets_no_suggestion(self):
        result = CliRunner().invoke(cli_mod.cli, ["zzzzzzzz"])
        assert result.exit_code == 2
        assert "Did you mean" not in result.output

    def test_real_commands_unaffected(self):
        result = CliRunner().invoke(cli_mod.cli, ["--help"])
        assert result.exit_code == 0
        assert "remove" in result.output
