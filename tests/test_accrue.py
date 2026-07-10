"""v0.5.0 — self-improving core guide: usage ledger + guarded auto-grow.
Guardrails under test: navigation-pointers-only, rules never promoted,
curated text preserved, budget cap, decay, project scope, self-heal."""

from datetime import datetime, timedelta, timezone

import pytest

from memgit.models import Mnemonic
from memgit.repo import Repository
from memgit.usage import read_usage, record_hits, reset_usage, usage_score
from memgit.delivery import (
    AUTO_START, AUTO_END, compute_auto_section, refresh_core_body, split_curated,
)

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
PROJ = "Alpha"


@pytest.fixture
def repo(tmp_path):
    return Repository.init(tmp_path)


def _add(repo, slug, rule, type_code="fb", priority=2, project=PROJ):
    repo.add(Mnemonic(type_code=type_code, slug=slug, timestamp=NOW,
                      rule=rule, priority=priority, project=project))


class TestLedger:
    def test_record_and_read(self, repo):
        record_hits(repo, ["a", "b"], now=NOW)
        record_hits(repo, ["a"], now=NOW)
        u = read_usage(repo)
        assert u["a"]["hits"] == 2 and u["b"]["hits"] == 1

    def test_reset(self, repo):
        record_hits(repo, ["a"], now=NOW)
        reset_usage(repo)
        assert read_usage(repo) == {}

    def test_score_decays_with_age(self):
        fresh = {"hits": 4, "last_used": NOW.isoformat()}
        old = {"hits": 4, "last_used": (NOW - timedelta(days=28)).isoformat()}
        assert usage_score(fresh, NOW) > usage_score(old, NOW)
        # 2 half-lives (28d) -> ~1/4 of the hit count
        assert usage_score(old, NOW) == pytest.approx(1.0, abs=0.01)


class TestAutoSection:
    def test_promotes_high_usage_as_pointer(self, repo):
        _add(repo, "freq", "Use the widget pipeline")
        record_hits(repo, ["freq"] * 3, now=NOW)
        out = compute_auto_section(repo, PROJ, NOW)
        assert "[freq]" in out and "widget pipeline" in out

    def test_never_promotes_critical_rules(self, repo):
        _add(repo, "rule", "A critical rule", priority=3)
        record_hits(repo, ["rule"] * 9, now=NOW)
        assert compute_auto_section(repo, PROJ, NOW) == ""

    def test_never_promotes_conventions(self, repo):
        _add(repo, "conv", "naming convention", type_code="cn")
        record_hits(repo, ["conv"] * 9, now=NOW)
        assert compute_auto_section(repo, PROJ, NOW) == ""

    def test_project_scoped(self, repo):
        _add(repo, "other", "belongs to Beta", project="Beta")
        record_hits(repo, ["other"] * 9, now=NOW)
        assert compute_auto_section(repo, PROJ, NOW) == ""

    def test_dedups_against_curated(self, repo):
        _add(repo, "dup", "Already stated in the curated guide")
        record_hits(repo, ["dup"] * 5, now=NOW)
        curated = "# Guide\nAlready stated in the curated guide here."
        assert compute_auto_section(repo, PROJ, NOW, curated) == ""

    def test_budget_caps_item_count(self, repo):
        for i in range(20):
            _add(repo, f"m{i}", f"fact number {i} about things")
            record_hits(repo, [f"m{i}"] * (i + 1), now=NOW)
        out = compute_auto_section(repo, PROJ, NOW)
        pointer_lines = [l for l in out.splitlines() if l.startswith("- [")]
        assert len(pointer_lines) <= 6


class TestRefreshBody:
    def test_preserves_curated_region(self, repo):
        _add(repo, "freq", "widget pipeline")
        record_hits(repo, ["freq"] * 3, now=NOW)
        body = refresh_core_body("CURATED — keep me.", repo, PROJ, NOW)
        assert body.startswith("CURATED — keep me.")
        assert AUTO_START in body and AUTO_END in body
        assert split_curated(body) == "CURATED — keep me."

    def test_returns_none_when_unchanged(self, repo):
        _add(repo, "freq", "widget pipeline")
        record_hits(repo, ["freq"] * 3, now=NOW)
        body = refresh_core_body("CURATED", repo, PROJ, NOW)
        assert refresh_core_body(body, repo, PROJ, NOW) is None

    def test_drops_auto_block_when_usage_gone(self, repo):
        _add(repo, "freq", "widget pipeline")
        record_hits(repo, ["freq"] * 3, now=NOW)
        body = refresh_core_body("CURATED", repo, PROJ, NOW)
        assert AUTO_START in body
        reset_usage(repo)
        healed = refresh_core_body(body, repo, PROJ, NOW)
        assert healed is not None and AUTO_START not in healed
        assert healed.strip() == "CURATED"
