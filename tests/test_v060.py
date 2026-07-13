"""v0.6.0 tests — supersession, trackers + status board, entity index,
recall depth hints, context-triggered recall, and the co/tr enum fixes.

Thesis under test: the passive layer (resume digest, recall blocks) must
truthfully advertise what the active layer (search/get) knows — counts that
lead nowhere or stale state in a digest would teach the model to ignore both.
"""

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from memgit.links import (
    entity_index,
    filter_active,
    normalize_slug_list,
    read_tagmap,
    resolve_head,
    superseded_by,
    superseded_slugs,
    tagmap_count,
    validate_relations,
    would_cycle,
    write_tagmap,
)
from memgit.models import Mnemonic
from memgit.repo import Repository

NOW = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)


def _mk(slug="test-mem", **kw):
    defaults = dict(type_code="pj", timestamp=NOW, rule="a rule", priority=2)
    defaults.update(kw)
    return Mnemonic(slug=slug, **defaults)


@pytest.fixture
def repo(tmp_path):
    return Repository.init(tmp_path)


def _run_hook(monkeypatch, capsys, fn, payload, repo):
    import memgit.hooks as hooks_mod
    monkeypatch.setattr(hooks_mod, "_find_repo", lambda: repo)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = fn()
    out = capsys.readouterr().out
    return rc, out


# ── WS1: co/tr enum hygiene ───────────────────────────────────────────────────

class TestEnumHygiene:
    def _invoke(self, args, repo, monkeypatch):
        from click.testing import CliRunner
        import memgit.cli as cli_mod
        monkeypatch.setattr(cli_mod, "_require_repo", lambda: repo)
        return CliRunner().invoke(cli_mod.cli, args)

    def test_list_type_co_and_tr_accepted(self, repo, monkeypatch):
        repo.add(_mk("core-proj", type_code="co", body="guide"))
        repo.add(_mk("deploy-status", type_code="tr", rule="deployed v2"))
        for tc, slug in (("co", "core-proj"), ("tr", "deploy-status")):
            res = self._invoke(["list", "--type", tc], repo, monkeypatch)
            assert res.exit_code == 0, res.output
            assert slug in res.output

    def test_search_type_co_accepted(self, repo, monkeypatch):
        repo.add(_mk("core-proj", type_code="co", rule="core operating guide"))
        res = self._invoke(["search", "operating guide", "--type", "co"],
                           repo, monkeypatch)
        assert res.exit_code == 0, res.output

    def test_graph_colors_and_labels_cover_all_types(self):
        from memgit.graph import _TYPE_COLOR, _TYPE_LABEL
        from memgit.toon import USER_TYPE_CODES
        assert USER_TYPE_CODES <= set(_TYPE_COLOR)
        assert USER_TYPE_CODES <= set(_TYPE_LABEL)

    def test_markdown_export_knows_tr(self):
        from memgit.toon import mnemonic_to_markdown
        md = mnemonic_to_markdown(_mk("x-status", type_code="tr"))
        assert "type: tracker" in md


# ── WS2: links.py graph logic ────────────────────────────────────────────────

class TestSupersessionGraph:
    def test_basic_superseded_set(self):
        mems = [_mk("old"), _mk("new", supersedes=["old"])]
        assert superseded_slugs(mems) == {"old"}

    def test_self_reference_ignored(self):
        mems = [_mk("solo", supersedes=["solo"])]
        assert superseded_slugs(mems) == set()

    def test_unknown_target_is_inert(self):
        mems = [_mk("new", supersedes=["never-existed"])]
        assert superseded_slugs(mems) == set()

    def test_chain_hides_all_but_head(self):
        mems = [_mk("c"), _mk("b", supersedes=["c"]), _mk("a", supersedes=["b"])]
        assert superseded_slugs(mems) == {"b", "c"}
        assert [m.slug for m in filter_active(mems)] == ["a"]
        assert resolve_head("c", mems) == "a"

    def test_fork_resolves_to_newest(self):
        mems = [
            _mk("x"),
            _mk("y1", supersedes=["x"], timestamp=NOW),
            _mk("y2", supersedes=["x"], timestamp=NOW + timedelta(hours=1)),
        ]
        assert superseded_by("x", mems) == ["y1", "y2"]
        assert resolve_head("x", mems) == "y2"

    def test_cycle_terminates_in_resolve_head(self):
        # a↔b cycle written by hand (write paths reject it; import can't)
        mems = [_mk("a", supersedes=["b"]), _mk("b", supersedes=["a"])]
        assert resolve_head("a", mems) in {"a", "b"}  # terminates, no hang

    def test_would_cycle_two_and_three_node(self):
        mems = [_mk("b", supersedes=["a"]), _mk("a")]
        assert would_cycle("a", ["b"], mems) == ["b"]  # a→b→a
        mems3 = [_mk("c", supersedes=["b"]), _mk("b", supersedes=["a"]), _mk("a")]
        assert would_cycle("a", ["c"], mems3) == ["c"]  # a→c→b→a
        assert would_cycle("fresh", ["a"], mems3) == []

    def test_removing_superseder_resurrects(self, repo):
        repo.add(_mk("old", rule="stale fact"))
        repo.add(_mk("new", rule="fresh fact", supersedes=["old"]))
        assert superseded_slugs(repo.list()) == {"old"}
        repo.remove("new")
        assert superseded_slugs(repo.list()) == set()


class TestValidateRelations:
    def test_normalize_accepts_list_and_csv(self):
        assert normalize_slug_list("a, b ,a,") == ["a", "b"]
        assert normalize_slug_list(["a", " b "]) == ["a", "b"]
        assert normalize_slug_list(None) == []

    def test_self_ref_stripped_and_cycle_dropped(self, repo):
        repo.add(_mk("b", supersedes=["a"]))
        repo.add(_mk("a"))
        sup, rel, warnings = validate_relations(
            "a", ["a", "b"], ["a", "x"], repo.list())
        assert sup == []                      # self stripped, cycle dropped
        assert rel == ["x"]                   # self stripped, unknown kept
        assert any("cycle" in w for w in warnings)

    def test_unknown_kept_with_warning(self, repo):
        repo.add(_mk("live"))
        sup, _rel, warnings = validate_relations(
            "new", ["live", "ghost"], None, repo.list())
        assert sup == ["live", "ghost"]
        assert warnings == ["unknown slug: ghost (kept)"]


# ── WS2: write paths + persistence ───────────────────────────────────────────

class TestSupersessionWritePaths:
    def test_cli_add_supersedes_persists(self, repo, monkeypatch):
        from click.testing import CliRunner
        import memgit.cli as cli_mod
        monkeypatch.setattr(cli_mod, "_require_repo", lambda: repo)
        repo.add(_mk("old-fact"))
        res = CliRunner().invoke(cli_mod.cli, [
            "add", "new-fact", "the corrected fact",
            "--supersedes", "old-fact,ghost", "--related", "old-fact",
            "--project", ""])
        assert res.exit_code == 0, res.output
        m = repo.get("new-fact")
        # TOON serializes relation lists sorted; order is not semantic
        assert set(m.supersedes) == {"old-fact", "ghost"}
        assert m.related == ["old-fact"]

    def test_toon_round_trip_preserves_relations(self, repo):
        repo.add(_mk("old"))
        repo.add(_mk("new", supersedes=["old"], related=["other"]))
        repo.commit(message="seed")
        again = Repository(repo.path).get("new")
        assert again.supersedes == ["old"]
        assert again.related == ["other"]

    def test_pre_060_object_shas_stable(self, repo):
        """A memory without relations serializes byte-identically to 0.5.0."""
        from memgit.toon import serialize_mnemonic
        m = _mk("plain", rule="no relations here", tags=["x"])
        assert "~SUP" not in serialize_mnemonic(m)
        assert "~REL" not in serialize_mnemonic(m)
        sha1 = repo.add(m)
        sha2 = repo.add(_mk("plain", rule="no relations here", tags=["x"]))
        assert sha1 == sha2

    def test_http_put_supersedes(self, repo, monkeypatch):
        import memgit.http_server as http_mod
        monkeypatch.setattr(http_mod, "_load_repo", lambda sp: repo)
        repo.add(_mk("old"))
        handler = object.__new__(http_mod.MemgitHandler)
        handler.path = "/memories/new-mem"
        body = json.dumps({"rule": "corrected", "supersedes": ["old", "ghost"],
                           "body": "full detail"}).encode()
        handler.rfile = io.BytesIO(body)
        handler.headers = {"Content-Length": str(len(body))}
        captured = {}
        handler._json_response = lambda data, status=200: captured.update(data)
        handler.do_PUT()
        m = repo.get("new-mem")
        assert set(m.supersedes) == {"old", "ghost"}
        assert m.body == "full detail"
        assert captured["warnings"] == ["unknown slug: ghost (kept)"]


# ── WS2: suppression surfaces ────────────────────────────────────────────────

class TestSuppression:
    def _seed_chain(self, repo):
        repo.add(_mk("stale-fact", rule="zebpay stop type is STOP_LOSS_LIMIT",
                     tags=["zebpay"]))
        repo.add(_mk("fresh-fact", rule="zebpay stop type is STOP_LIMIT not the advertised one",
                     tags=["zebpay"], supersedes=["stale-fact"]))
        repo.commit(message="seed")

    def test_cli_search_hides_and_flag_shows(self, repo, monkeypatch):
        from click.testing import CliRunner
        import memgit.cli as cli_mod
        monkeypatch.setattr(cli_mod, "_require_repo", lambda: repo)
        self._seed_chain(repo)
        res = CliRunner().invoke(cli_mod.cli, ["search", "zebpay stop type"])
        assert "fresh-fact" in res.output and "stale-fact" not in res.output
        res2 = CliRunner().invoke(cli_mod.cli, ["search", "zebpay stop type",
                                                "--include-superseded"])
        assert "stale-fact" in res2.output

    def test_prompt_recall_never_injects_superseded(self, repo, monkeypatch, capsys):
        from memgit.hooks import prompt_recall
        self._seed_chain(repo)
        rc, out = _run_hook(monkeypatch, capsys, prompt_recall, {
            "prompt": "what is the zebpay stop order type again?",
            "cwd": "/tmp", "session_id": "sup1"}, repo)
        assert "fresh-fact" in out
        assert "stale-fact" not in out

    def test_resume_pools_exclude_superseded(self, repo):
        self._seed_chain(repo)
        repo.add(_mk("stale-crit", priority=3, supersedes=[]))
        repo.add(_mk("crit-fix", priority=3, supersedes=["stale-crit"]))
        ctx = repo.resume_context()
        recent = {m["slug"] for m in ctx["recent_memories"]}
        crit = {m["slug"] for m in ctx["critical_memories"]}
        assert "stale-fact" not in recent and "fresh-fact" in recent
        assert "stale-crit" not in crit and "crit-fix" in crit

    def test_list_annotates_but_shows(self, repo, monkeypatch):
        from click.testing import CliRunner
        import memgit.cli as cli_mod
        monkeypatch.setattr(cli_mod, "_require_repo", lambda: repo)
        self._seed_chain(repo)
        res = CliRunner().invoke(cli_mod.cli, ["list"])
        assert "stale-fact" in res.output          # audit view keeps it
        assert "⊘" in res.output                   # ...marked
        assert "1 superseded" in res.output

    def test_auto_section_skips_superseded_and_trackers(self, repo):
        from memgit.delivery import compute_auto_section
        from memgit.usage import record_hits
        self._seed_chain(repo)
        repo.add(_mk("x-status", type_code="tr", rule="live state"))
        repo.commit(message="more")
        record_hits(repo, ["stale-fact", "fresh-fact", "x-status"])
        auto = compute_auto_section(repo, None, NOW)
        assert "stale-fact" not in auto
        assert "x-status" not in auto
        assert "fresh-fact" in auto


# ── WS3: trackers + status board ─────────────────────────────────────────────

class TestTrackers:
    def test_status_board_scoped_sorted_capped(self, repo):
        for i in range(10):
            repo.add(_mk(f"e{i}-status", type_code="tr",
                         rule=f"state {i}",
                         timestamp=NOW + timedelta(minutes=i)))
        repo.add(_mk("other-proj-status", type_code="tr",
                     project="Other-Project", rule="not ours"))
        ctx = repo.resume_context(project="My-Proj")
        slugs = [t["slug"] for t in ctx["tracker_memories"]]
        assert len(slugs) == 8                     # capped
        assert slugs[0] == "e9-status"             # newest first
        assert "other-proj-status" not in slugs    # never leaks cross-project

    def test_plain_resume_renders_board_with_freshness(self, repo):
        from memgit.cli import _format_resume_plain
        repo.add(_mk("deploy-status", type_code="tr",
                     rule="v2 shipped, awaiting CI"))
        text = _format_resume_plain(repo.resume_context())
        assert "## Status board" in text
        assert "memgit is authoritative" in text
        assert "deploy-status (upd 07-13): v2 shipped, awaiting CI" in text

    def test_no_trackers_no_board(self, repo):
        from memgit.cli import _format_resume_plain
        repo.add(_mk("plain-fact"))
        assert "## Status board" not in _format_resume_plain(repo.resume_context())

    def test_same_slug_resave_updates_board(self, repo):
        repo.add(_mk("mig-status", type_code="tr", rule="step 1 of 3"))
        repo.add(_mk("mig-status", type_code="tr", rule="step 3 of 3 DONE",
                     timestamp=NOW + timedelta(hours=2)))
        board = repo.resume_context()["tracker_memories"]
        assert len(board) == 1
        assert board[0]["rule"] == "step 3 of 3 DONE"


# ── WS4: entity index + depth hints ──────────────────────────────────────────

class TestEntityIndex:
    def test_counts_threshold_ordering_cap(self):
        mems = ([_mk(f"a{i}", tags=["alpha"]) for i in range(3)]
                + [_mk(f"b{i}", tags=["beta"]) for i in range(2)]
                + [_mk("solo", tags=["lonely"])]
                + [_mk(f"t{i}", tags=[f"tag{i}"]) for i in range(20)])
        idx = entity_index(mems, None)
        assert idx[0] == ("alpha", 3)
        assert ("beta", 2) in idx
        assert all(tag != "lonely" for tag, _n in idx)   # count 1 dropped
        assert len(idx) <= 8

    def test_project_label_tag_excluded(self):
        mems = [_mk(f"m{i}", tags=["My-Proj", "real-topic"], project="My-Proj")
                for i in range(3)]
        idx = entity_index(mems, "My-Proj")
        tags = [t for t, _ in idx]
        assert "real-topic" in tags and "My-Proj" not in tags

    def test_superseded_excluded_from_counts(self):
        mems = [_mk("old1", tags=["topic"]), _mk("old2", tags=["topic"]),
                _mk("new", tags=["topic"], supersedes=["old1", "old2"])]
        assert entity_index(mems, None) == []  # only 1 active left → below bar

    def test_plain_resume_renders_index_last(self, repo):
        from memgit.cli import _format_resume_plain
        for i in range(3):
            repo.add(_mk(f"m{i}", tags=["dynamo"]))
        text = _format_resume_plain(repo.resume_context())
        assert "## Memory index — depth beyond this digest" in text
        assert "dynamo (3)" in text
        assert 'search_memories(' in text
        # index sits after every other section (recency position)
        assert text.index("Memory index") > text.index("Recently updated")

    def test_recall_depth_hint_and_no_dedup_pollution(self, repo, monkeypatch, capsys):
        from memgit.hooks import prompt_recall
        repo.add(_mk("zebpay-caps", rule="ZebPay caps INR withdrawals at 10L/day",
                     tags=["zebpay"]))
        for i in range(3):
            repo.add(_mk(f"zebpay-extra-{i}", rule=f"other zebpay detail {i}",
                         tags=["zebpay"]))
        repo.commit(message="seed")
        rc, out = _run_hook(monkeypatch, capsys, prompt_recall, {
            "prompt": "what are the zebpay withdrawal caps and limits?",
            "cwd": "/tmp", "session_id": "hint1"}, repo)
        assert "more saved on 'zebpay'" in out
        assert 'search_memories("zebpay")' in out
        # hinted-but-not-shown slugs must NOT be marked seen: a later prompt
        # matching them should still inject
        seen = (repo.path / "cache" / "recall" / "hint1").read_text()
        injected = {l.strip() for l in seen.splitlines()}
        assert len(injected) <= 3

    def test_no_hint_when_depth_below_two(self, repo, monkeypatch, capsys):
        from memgit.hooks import prompt_recall
        repo.add(_mk("zebpay-caps", rule="ZebPay caps INR withdrawals at 10L/day",
                     tags=["zebpay"]))
        repo.commit(message="seed")
        rc, out = _run_hook(monkeypatch, capsys, prompt_recall, {
            "prompt": "what are the zebpay withdrawal caps and limits?",
            "cwd": "/tmp", "session_id": "hint2"}, repo)
        assert "zebpay-caps" in out
        assert "more saved on" not in out


# ── WS5: context-triggered recall ────────────────────────────────────────────

class TestContextRecall:
    def _seed(self, repo, n=3, tag="dynamo"):
        for i in range(n):
            repo.add(_mk(f"{tag}-mem-{i}", tags=[tag]))
        repo.commit(message="seed")  # commit rebuilds the tagmap

    def test_tagmap_rebuilt_at_commit(self, repo):
        self._seed(repo)
        tm = read_tagmap(repo)
        assert tagmap_count(tm, "dynamo", None) == 3

    def test_tagmap_excludes_superseded(self, repo):
        self._seed(repo, n=3)
        repo.add(_mk("dynamo-new", tags=["dynamo"],
                     supersedes=["dynamo-mem-0", "dynamo-mem-1"]))
        repo.commit(message="supersede")
        assert tagmap_count(read_tagmap(repo), "dynamo", None) == 2

    def test_injects_on_matching_path(self, repo, monkeypatch, capsys):
        from memgit.hooks import context_recall
        self._seed(repo)
        rc, out = _run_hook(monkeypatch, capsys, context_recall, {
            "tool_input": {"file_path": "/Users/x/reports/dynamo-8a8f4ec-audit.md"},
            "cwd": "/tmp", "session_id": "ctx1"}, repo)
        assert rc == 0
        payload = json.loads(out)
        note = payload["hookSpecificOutput"]["additionalContext"]
        assert "3 memories tagged 'dynamo'" in note
        assert 'search_memories("dynamo")' in note

    def test_silent_below_count_or_no_match(self, repo, monkeypatch, capsys):
        from memgit.hooks import context_recall
        self._seed(repo, n=2)  # below CTX_MIN_TAG_COUNT
        rc, out = _run_hook(monkeypatch, capsys, context_recall, {
            "tool_input": {"file_path": "/x/dynamo-file.md"},
            "cwd": "/tmp", "session_id": "ctx2"}, repo)
        assert out == ""
        self._seed(repo, n=3, tag="zebpay")
        rc, out = _run_hook(monkeypatch, capsys, context_recall, {
            "tool_input": {"file_path": "/x/unrelated/thing.py"},
            "cwd": "/tmp", "session_id": "ctx2"}, repo)
        assert out == ""

    def test_per_tag_dedup_and_session_cap(self, repo, monkeypatch, capsys):
        from memgit.hooks import context_recall
        for tag in ("alpha", "beta", "gamma", "delta"):
            self._seed(repo, n=3, tag=tag)
        payload = lambda tag, sid: {
            "tool_input": {"file_path": f"/x/{tag}/notes.md"},
            "cwd": "/tmp", "session_id": sid}
        rc, out1 = _run_hook(monkeypatch, capsys, context_recall,
                             payload("alpha", "cap1"), repo)
        assert "alpha" in out1
        rc, out_dup = _run_hook(monkeypatch, capsys, context_recall,
                                payload("alpha", "cap1"), repo)
        assert out_dup == ""                      # same tag, same session
        for tag in ("beta", "gamma"):
            rc, out = _run_hook(monkeypatch, capsys, context_recall,
                                payload(tag, "cap1"), repo)
            assert tag in out
        rc, out4 = _run_hook(monkeypatch, capsys, context_recall,
                             payload("delta", "cap1"), repo)
        assert out4 == ""                         # hard cap 3/session

    def test_skips_tag_already_hinted_by_prompt_recall(self, repo, monkeypatch, capsys):
        from memgit.hooks import context_recall
        self._seed(repo, n=3, tag="zebpay")
        hint_dir = repo.path / "cache" / "recall-hints"
        hint_dir.mkdir(parents=True, exist_ok=True)
        (hint_dir / "ctx5").write_text("zebpay")
        rc, out = _run_hook(monkeypatch, capsys, context_recall, {
            "tool_input": {"file_path": "/x/zebpay/notes.md"},
            "cwd": "/tmp", "session_id": "ctx5"}, repo)
        assert out == ""


# ── WS7: core-guide seed nudge ───────────────────────────────────────────────

class TestCoreNudge:
    def test_nudge_when_memories_but_no_guide(self, repo):
        from memgit.cli import _format_resume_plain
        for i in range(10):
            repo.add(_mk(f"m{i}", project="My-Proj"))
        ctx = repo.resume_context(project="My-Proj")
        assert ctx["core_missing"] is True
        assert "memgit core seed" in _format_resume_plain(ctx)

    def test_no_nudge_when_guide_exists_or_project_small(self, repo):
        for i in range(10):
            repo.add(_mk(f"m{i}", project="My-Proj"))
        repo.add(_mk("core-My-Proj", type_code="co", project="My-Proj",
                     body="guide"))
        assert repo.resume_context(project="My-Proj")["core_missing"] is False
        # small project: below the 10-memory bar
        for i in range(3):
            repo.add(_mk(f"s{i}", project="Small-Proj"))
        assert repo.resume_context(project="Small-Proj")["core_missing"] is False
        # brand-new project: the project_is_new nudge owns that case
        assert repo.resume_context(project="Empty-Proj")["core_missing"] is False


# ── token budget: the digest must stay bounded ───────────────────────────────

class TestTokenBudget:
    def _big_store(self, repo, criticals=True):
        # Realistic shapes: rules ~90 chars, a handful of criticals.
        for i in range(200):
            repo.add(_mk(
                f"mem-{i}", rule=f"fact number {i}: " + "detail " * 10,
                tags=[f"topic{i % 10}", "shared"],
                priority=3 if criticals and i % 40 == 0 else 2,
            ))
        repo.commit(message="seed")  # a real store has ~no staged work

    def test_new_sections_cost_bounded(self, repo):
        """Status board + memory index + closing line together must stay a
        footnote (<~250 tokens) — they exist to convert, not to consume."""
        from memgit.cli import _format_resume_plain
        self._big_store(repo)
        base = len(_format_resume_plain(repo.resume_context()))
        for i in range(9):  # 9 trackers → board caps at 8
            repo.add(_mk(f"e{i}-status", type_code="tr",
                         rule="entity state line " * 3))
        repo.commit(message="trackers")
        with_new = len(_format_resume_plain(repo.resume_context()))
        added_tokens = (with_new - base) / 4
        assert added_tokens <= 250, f"new sections cost ~{added_tokens:.0f} tokens"

    def test_resume_bounded_on_large_store(self, repo):
        from memgit.cli import _format_resume_plain
        self._big_store(repo)
        for i in range(9):
            repo.add(_mk(f"e{i}-status", type_code="tr", rule="state " * 10))
        text = _format_resume_plain(repo.resume_context())
        approx_tokens = len(text) / 4  # chars/4 heuristic
        assert approx_tokens <= 900, f"digest too big: ~{approx_tokens:.0f} tokens"

    def test_server_description_pins_authority_framing(self):
        from memgit.mcp_server import _SERVER_DESCRIPTION, _TYPE_DESCRIPTIONS
        assert "AUTHORITY" in _SERVER_DESCRIPTION
        assert "supersedes" in _SERVER_DESCRIPTION
        assert "tr=tracker" in _TYPE_DESCRIPTIONS
