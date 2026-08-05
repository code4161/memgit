"""v0.8.1 — retrieval that can be proved, and adoption that starts itself.

Covers the five changes that came out of the 2026-08-05 cross-host audit:
  * scorer: SHA-keyed tokenization cache, additive stem field, usage term
  * project: free-text project labels folded onto the real workspace label
  * links:   identifier-shaped tags are never advertised as topics
  * hooks:   depth hints name a concrete memory instead of only counting
  * cli:     a project's first core guide is created without being asked
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from memgit.models import Mnemonic


def mem(slug, rule, **kw):
    kw.setdefault("type_code", "lx")
    kw.setdefault("timestamp", datetime.now(timezone.utc))
    m = Mnemonic(slug=slug, rule=rule, **kw)
    m.sha = kw.get("sha") or ("0" * 8 + slug)
    return m


# ── scorer: tokenization cache ───────────────────────────────────────────────

class TestTokenCache:
    def test_same_sha_reuses_tokens(self):
        from memgit import scorer
        scorer.clear_token_cache()
        m = mem("deploy-guide", "how to deploy the app")
        first = scorer._field_tokens(m)
        second = scorer._field_tokens(m)
        assert first is second, "identical SHA must hit the cache, not re-tokenize"

    def test_changed_content_misses_cache(self):
        from memgit import scorer
        scorer.clear_token_cache()
        a = mem("x", "alpha beta")
        b = mem("x", "gamma delta")
        b.sha = "different-sha"
        assert scorer._field_tokens(a)["rule"] != scorer._field_tokens(b)["rule"]

    def test_no_sha_still_works(self):
        from memgit import scorer
        m = mem("y", "some rule text")
        m.sha = None
        assert scorer._field_tokens(m)["rule"] == ["some", "rule", "text"]


# ── scorer: stemming ─────────────────────────────────────────────────────────

class TestStemming:
    @pytest.mark.parametrize("word,stem", [
        ("deployment", "deploy"), ("deployments", "deploy"),
        ("posting", "post"), ("proposals", "proposal"),
        ("categories", "category"), ("ranked", "rank"),
    ])
    def test_folds_common_suffixes(self, word, stem):
        from memgit.scorer import _stem
        assert _stem(word) == stem

    @pytest.mark.parametrize("word", ["sing", "ties", "less", "api", "css", "s3"])
    def test_short_tokens_untouched(self, word):
        from memgit.scorer import _stem
        assert _stem(word) == word

    def test_idempotent(self):
        from memgit.scorer import _stem
        for w in ("deployment", "postings", "categories", "running"):
            assert _stem(_stem(w)) == _stem(w)

    def test_stem_field_is_additive_not_destructive(self):
        """Raw fields must survive — folding them was measured worse."""
        from memgit import scorer
        scorer.clear_token_cache()
        m = mem("deployment-vercel", "deployment runs on vercel")
        fields = scorer._field_tokens(m)
        assert "deployment" in fields["rule"], "raw term must remain"
        assert "deploy" in fields[scorer.STEM_FIELD], "stem must be added alongside"

    def test_stem_field_excluded_from_doc_len(self):
        """doc_len and avg_len must agree, or every score silently shifts."""
        from memgit import scorer
        scorer.clear_token_cache()
        m = mem("a-b", "alpha beta gamma")
        fields = scorer._field_tokens(m)
        assert scorer.STEM_FIELD in fields
        assert scorer._doc_len(fields) == sum(
            len(v) for k, v in fields.items() if k != scorer.STEM_FIELD)

    def test_stemmed_query_finds_unstemmed_memory(self):
        from memgit import scorer
        scorer.clear_token_cache()
        pool = [
            mem("deployment-vercel", "deployment of the portfolio runs on vercel"),
            mem("unrelated-thing", "crypto perpetual futures margin"),
        ]
        got = scorer.score("how do I deploy the portfolio", pool, top_k=2)
        assert got and got[0].mnemonic.slug == "deployment-vercel"

    def test_exact_match_still_outranks_stem_match(self):
        """Precision guard: a real term beats a stem-only hit."""
        from memgit import scorer
        scorer.clear_token_cache()
        pool = [
            mem("exact-one", "deploy the service"),
            mem("stem-only", "deployment of the service"),
        ]
        got = scorer.score("deploy", pool, top_k=2)
        assert got[0].mnemonic.slug == "exact-one"


# ── scorer: usage term ───────────────────────────────────────────────────────

class TestUsageTerm:
    def test_multiplier_is_bounded_and_monotone(self):
        from memgit.scorer import usage_multiplier, _USAGE_BOOST_MAX
        assert usage_multiplier(0) == 1.0
        assert usage_multiplier(-5) == 1.0
        assert 1.0 < usage_multiplier(3) < usage_multiplier(50) < _USAGE_BOOST_MAX

    def test_unused_memory_is_never_penalized(self):
        """A brand-new correction must not sink below an old favourite."""
        from memgit import scorer
        scorer.clear_token_cache()
        pool = [mem("fresh", "alpha beta gamma")]
        without = scorer.score("alpha beta", pool, top_k=1)[0].score
        with_usage = scorer.score("alpha beta", pool, top_k=1, usage={})[0].score
        assert with_usage == without

    def test_usage_breaks_a_tie(self):
        from memgit import scorer
        scorer.clear_token_cache()
        pool = [mem("cold", "alpha beta gamma"), mem("hot", "alpha beta gamma")]
        now = datetime.now(timezone.utc)
        usage = {"hot": {"hits": 40, "last_used": now.isoformat()}}
        got = scorer.score("alpha beta", pool, top_k=2, usage=usage, now=now)
        assert got[0].mnemonic.slug == "hot"

    def test_recency_term_is_gone(self):
        """Removed after measuring hit@1 -0.020 / MRR -0.018. Do not restore
        without numbers from `memgit eval`."""
        from memgit import scorer
        assert not hasattr(scorer, "recency_multiplier")
        old = mem("old", "alpha beta gamma",
                  timestamp=datetime.now(timezone.utc) - timedelta(days=400))
        new = mem("new", "alpha beta gamma")
        scorer.clear_token_cache()
        got = scorer.score("alpha beta gamma", [old, new], top_k=2)
        assert got[0].score == pytest.approx(got[1].score)


# ── project: label folding ───────────────────────────────────────────────────

class TestCanonicalProject:
    def test_folds_short_label_onto_workspace_label(self):
        from memgit.project import canonical_project
        assert canonical_project("log-report", {"Downloads-log-report": 850}) \
            == "Downloads-log-report"

    def test_established_label_is_never_folded_away(self):
        """The live FittyMe case: 90 memories under the SHORT label and 1 under
        the long one. Always-fold-to-longest would have moved 90 onto the 1."""
        from memgit.project import canonical_project
        known = {"Freelance-FittyMe": 1, "FittyMe": 90}
        assert canonical_project("FittyMe", known) == "FittyMe"

    def test_exact_label_unchanged(self):
        from memgit.project import canonical_project
        known = {"Downloads-log-report": 850, "log-report": 45}
        assert canonical_project("log-report", known) == "log-report"

    def test_ambiguous_label_left_alone(self):
        """Guessing wrong files a memory under the wrong project."""
        from memgit.project import canonical_project
        known = {"a-log-report": 5, "b-log-report": 5}
        assert canonical_project("log-report", known) == "log-report"

    def test_unknown_label_untouched(self):
        from memgit.project import canonical_project
        assert canonical_project("brand-new", {"Other": 3}) == "brand-new"

    def test_quarantine_and_empty_pass_through(self):
        from memgit.project import canonical_project, UNKNOWN_PROJECT
        assert canonical_project(UNKNOWN_PROJECT, {"X-y": 1}) == UNKNOWN_PROJECT
        assert canonical_project(None, {"X-y": 1}) is None

    def test_plain_iterable_still_accepted(self):
        from memgit.project import canonical_project
        assert canonical_project("log-report", ["Downloads-log-report"]) \
            == "Downloads-log-report"

    def test_substring_without_segment_boundary_does_not_match(self):
        from memgit.project import canonical_project
        assert canonical_project("port", {"Downloads-log-report": 850}) == "port"

    def test_known_projects_counts_and_excludes_quarantine(self):
        from memgit.project import known_projects, UNKNOWN_PROJECT
        mems = [mem("a", "x", project="P"), mem("d", "x", project="P"),
                mem("b", "y", project=UNKNOWN_PROJECT),
                mem("c", "z", project=None)]
        assert known_projects(mems) == {"P": 2}


# ── links: noise tags ────────────────────────────────────────────────────────

class TestNoiseTags:
    @pytest.mark.parametrize("tag", [
        "89e1fd7", "8a8f4ec", "a85deba", "c3e9081", "2026", "2026-07",
        "2026-07-21", "42", "x", "",
    ])
    def test_identifier_shapes_are_noise(self, tag):
        from memgit.links import is_noise_tag
        assert is_noise_tag(tag, set())

    @pytest.mark.parametrize("tag", [
        "crypto", "instagram", "trading", "added", "decade", "faced", "mcp",
    ])
    def test_real_topics_survive(self, tag):
        from memgit.links import is_noise_tag
        assert not is_noise_tag(tag, set())

    def test_all_letter_hex_word_is_kept_deliberately(self):
        """The SHA test requires a digit. 'decade', 'faced' and 'added' are
        spelled entirely from a-f, and deleting them as topics would be a
        worse failure than letting the rare digit-free SHA through."""
        from memgit.links import is_noise_tag
        assert not is_noise_tag("deadbeef", set())
        assert not is_noise_tag("decade", set())

    def test_project_label_parts_are_noise(self):
        from memgit.links import is_noise_tag, label_noise
        noise = label_noise("Personal-business")
        assert is_noise_tag("personal", noise)
        assert is_noise_tag("business", noise)
        assert not is_noise_tag("crypto", noise)

    def test_entity_index_drops_sha_tags(self):
        from memgit.links import entity_index
        mems = [mem(f"m{i}", "rule text", tags=["89e1fd7", "crypto"], project="P")
                for i in range(3)]
        tags = {t for t, _ in entity_index(mems, "P")}
        assert "crypto" in tags and "89e1fd7" not in tags


# ── hooks: depth hint payload ────────────────────────────────────────────────

class TestDepthHint:
    def _pool(self, n=4):
        return [mem(f"crypto-fact-{i}",
                    f"crypto detail number {i} that matters a great deal here",
                    tags=["crypto"], project="P", priority=3 if i == 0 else 2)
                for i in range(n)]

    def test_hint_names_a_specific_memory(self):
        from memgit.hooks import _depth_hint
        from memgit.scorer import ScoredMnemonic
        pool = self._pool()
        results = [ScoredMnemonic(pool[3], 20.0, ["rule"])]
        line, tag = _depth_hint(results, pool, set(), "P")
        assert tag == "crypto"
        assert "including [crypto-fact-0]" in line, \
            "a bare count converted at 20.5%; the hint must name something"
        assert 'search_memories("crypto")' in line

    def test_no_hint_when_depth_is_one(self):
        from memgit.hooks import _depth_hint
        from memgit.scorer import ScoredMnemonic
        pool = self._pool(2)
        results = [ScoredMnemonic(pool[0], 20.0, ["rule"])]
        line, tag = _depth_hint(results, pool, set(), "P")
        assert line is None and tag is None

    def test_sha_tag_is_never_advertised(self):
        from memgit.hooks import _depth_hint
        from memgit.scorer import ScoredMnemonic
        pool = [mem(f"m{i}", "some rule", tags=["89e1fd7"], project="P")
                for i in range(5)]
        results = [ScoredMnemonic(pool[0], 20.0, ["rule"])]
        line, tag = _depth_hint(results, pool, set(), "P")
        assert line is None and tag is None

    def test_hint_is_deterministic(self):
        from memgit.hooks import _depth_hint
        from memgit.scorer import ScoredMnemonic
        pool = self._pool()
        results = [ScoredMnemonic(pool[3], 20.0, ["rule"])]
        a = _depth_hint(results, pool, set(), "P")
        b = _depth_hint(results, list(reversed(pool)), set(), "P")
        assert a == b


# ── delivery: Antigravity + project-only detection ───────────────────────────

class TestAntigravityDelivery:
    def test_agents_md_target_detects_antigravity(self):
        from memgit.delivery import TARGETS_BY_LABEL
        t = TARGETS_BY_LABEL["Codex / Antigravity"]
        assert t.rel_path == "AGENTS.md"
        assert ".antigravity" in t.detect
        assert ".gemini/config" in t.detect
        assert ".codex" in t.detect, "Codex must keep working from the same target"

    def test_only_one_target_writes_agents_md(self):
        """Two targets on one path would clobber each other's marker block."""
        from memgit.delivery import TARGETS
        assert sum(1 for t in TARGETS if t.rel_path == "AGENTS.md") == 1

    def test_project_only_ignores_home_signature(self, tmp_path):
        from memgit.delivery import TARGETS_BY_LABEL, is_present
        home = tmp_path / "home"
        (home / ".cursor").mkdir(parents=True)
        root = tmp_path / "repo"
        root.mkdir()
        cursor = TARGETS_BY_LABEL["Cursor"]
        assert is_present(cursor, root, home) is True
        assert is_present(cursor, root, home, project_only=True) is False

    def test_project_only_honours_project_signature(self, tmp_path):
        from memgit.delivery import TARGETS_BY_LABEL, is_present
        home = tmp_path / "home"
        home.mkdir()
        root = tmp_path / "repo"
        (root / ".cursor").mkdir(parents=True)
        cursor = TARGETS_BY_LABEL["Cursor"]
        assert is_present(cursor, root, home, project_only=True) is True


class TestAntigravitySetupTarget:
    def test_shared_config_is_the_primary_path(self):
        from memgit.cli import _all_targets
        by_label = {t[0]: t[1] for t in _all_targets()}
        assert by_label["Antigravity"].parts[-2:] == ("config", "mcp_config.json"), \
            "Antigravity 2.x reads ~/.gemini/config/mcp_config.json"

    def test_legacy_paths_still_present(self):
        from memgit.cli import _all_targets
        labels = {t[0] for t in _all_targets()}
        assert "Antigravity (legacy 1.x)" in labels
        assert "Antigravity IDE (legacy 1.x)" in labels

    def test_legacy_labels_still_stamp_the_client(self):
        from memgit.cli import _client_slug
        assert _client_slug("Antigravity (legacy 1.x)") == "antigravity"
        assert _client_slug("Antigravity IDE (legacy 1.x)") == "antigravity"


# ── seed body: concrete evidence ─────────────────────────────────────────────

class TestSeedEvidence:
    def test_seed_without_repo_is_unchanged(self, tmp_path):
        from memgit.delivery import build_seed
        body = build_seed(tmp_path, home=tmp_path)
        assert "## memgit" in body
        assert "saved memories" not in body

    def test_seed_states_the_real_count(self, tmp_path):
        from memgit.delivery import build_seed

        class FakeRepo:
            def list(self):
                return [mem(f"m{i}", f"rule {i}", tags=["crypto", "trading"],
                            project="P") for i in range(9)]

        body = build_seed(tmp_path, home=tmp_path, repo=FakeRepo(), project="P")
        assert "**9 saved memories**" in body
        assert "crypto" in body

    def test_seed_stays_quiet_below_the_bar(self, tmp_path):
        from memgit.delivery import build_seed

        class FakeRepo:
            def list(self):
                return [mem("m0", "rule", project="P")]

        body = build_seed(tmp_path, home=tmp_path, repo=FakeRepo(), project="P")
        assert "saved memories" not in body


# ── eval harness ─────────────────────────────────────────────────────────────

class TestEvalHarness:
    def test_roundtrip_two_named_sets(self, tmp_path):
        from memgit.evaluate import EvalCase, save_evalset, load_evalset, evalset_path

        class R:
            path = tmp_path

        (tmp_path).mkdir(exist_ok=True)
        save_evalset(R(), [EvalCase(query="q1", expected=["a"])], "recall")
        save_evalset(R(), [EvalCase(query="q2", expected=["b"]),
                           EvalCase(query="q3", expected=["c"])], "synthetic")
        assert len(load_evalset(R(), "recall")) == 1
        assert len(load_evalset(R(), "synthetic")) == 2
        assert evalset_path(R(), "recall") != evalset_path(R(), "synthetic")

    def test_synthetic_query_strips_slug_words(self):
        """Leaving slug tokens in hands the ranker a 2.0-weighted freebie."""
        from memgit.evaluate import mine_synthetic

        class R:
            def list(self):
                return [mem("crypto-perp-stop", "always arm the stop",
                            why="the crypto perp stop was left naked for four "
                                "hours after a partial fill on the venue")]

        cases = mine_synthetic(R(), min_chars=20)
        assert len(cases) == 1
        q = cases[0].query.lower()
        assert cases[0].expected == ["crypto-perp-stop"]
        for word in ("crypto", "perp", "stop"):
            assert word not in q.split(), f"slug word {word!r} leaked into the query"

    def test_missing_expected_memory_is_skipped_not_a_miss(self, tmp_path):
        from memgit.evaluate import EvalCase, run_eval

        class R:
            path = tmp_path
            def list(self):
                return [mem("present", "alpha beta")]

        res = run_eval(R(), [EvalCase(query="alpha", expected=["deleted-slug"])])
        assert res.skipped == 1 and res.n == 0

    def test_relabelled_memory_is_stale_not_a_miss(self, tmp_path):
        """A `doctor --relabel` must never read as a ranking regression."""
        from memgit.evaluate import EvalCase, run_eval

        class R:
            path = tmp_path
            def list(self):
                return [mem("moved", "alpha beta", project="Downloads-log-report")]

        res = run_eval(R(), [EvalCase(query="alpha beta", expected=["moved"],
                                      project="log-report")])
        assert res.stale == 1 and res.n == 0 and res.skipped == 0

    def test_global_memory_is_never_stale(self, tmp_path):
        from memgit.evaluate import EvalCase, run_eval

        class R:
            path = tmp_path
            def list(self):
                return [mem("global-rule", "alpha beta", project=None)]

        res = run_eval(R(), [EvalCase(query="alpha beta", expected=["global-rule"],
                                      project="Anything")])
        assert res.stale == 0 and res.n == 1

    def test_metrics_on_a_known_ordering(self, tmp_path):
        from memgit.evaluate import EvalCase, run_eval
        from memgit import scorer
        scorer.clear_token_cache()

        class R:
            path = tmp_path
            def list(self):
                return [mem("target", "alpha beta gamma delta"),
                        mem("other", "zeta eta theta")]

        res = run_eval(R(), [EvalCase(query="alpha beta", expected=["target"])])
        assert res.n == 1 and res.hit_at_1 == 1.0 and res.mrr == 1.0

    def test_compare_reports_signed_deltas(self):
        from memgit.evaluate import EvalResult, compare
        before = EvalResult(n=10, hit_at_1=0.30, mrr=0.42)
        after = EvalResult(n=10, hit_at_1=0.31, mrr=0.40)
        d = compare(before, after)
        assert d["hit_at_1"] == pytest.approx(0.01)
        assert d["mrr"] == pytest.approx(-0.02)
