"""Tests for the savings counterfactual.

`memgit metrics` refuses to print a savings figure because the naive
counterfactual is unobservable. `memgit savings` prices a STATED one instead,
so the tests that matter are the ones that keep it honest: a fact no file
carries must never become a token number, and the matcher must not credit a
large file merely for being large.
"""

from datetime import datetime, timezone

from memgit import savings as sv
from memgit import store
from memgit.models import Mnemonic
from memgit.repo import Repository


def mem(slug, rule, project='Proj'):
    return Mnemonic(type_code='lx', slug=slug, timestamp=datetime.now(timezone.utc),
                    rule=rule, project=project)


def build(tmp_path, files: dict) -> Repository:
    for name, text in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
    return Repository.init(tmp_path)


class TestPassageMatching:
    def test_a_fact_stated_in_a_passage_is_found(self, tmp_path):
        corpus_text = ('unrelated preamble\n' * 5 +
                       'The zebra deployment pipeline restarts nightly at midnight.\n' +
                       'more unrelated text\n' * 5)
        build(tmp_path, {'notes.md': corpus_text})
        c = sv.FileCorpus(tmp_path)
        terms = sv._terms('zebra deployment pipeline restarts nightly midnight')
        cost, where = c.cost_to_find(terms, 0.5, 3)
        assert cost is not None and where == ['notes.md']

    def test_a_fact_in_no_file_returns_none_not_zero(self, tmp_path):
        build(tmp_path, {'notes.md': 'nothing whatsoever about the subject\n' * 20})
        c = sv.FileCorpus(tmp_path)
        terms = sv._terms('quokka orbital telemetry cadence recalibration')
        cost, where = c.cost_to_find(terms, 0.5, 3)
        assert cost is None
        assert where == []

    def test_a_big_file_does_not_match_by_being_big(self, tmp_path):
        """The bug this replaced: whole-file term overlap made the largest doc
        in a repo 'contain' almost every memory, because a long document holds
        half the vocabulary of anything. The terms must co-occur in a passage."""
        scattered = []
        for i, word in enumerate(['zebra', 'deployment', 'restarts', 'midnight']):
            scattered.append(word + '\n' + ('filler words here for padding\n' * 120))
        build(tmp_path, {'huge.md': ''.join(scattered)})
        c = sv.FileCorpus(tmp_path)
        terms = sv._terms('zebra deployment restarts midnight')
        cost, _ = c.cost_to_find(terms, 0.75, 3)
        assert cost is None, 'terms scattered across a long file must not count as the fact'

    def test_reads_parameter_controls_how_many_files_are_paid_for(self, tmp_path):
        line = 'The zebra deployment pipeline restarts nightly at midnight.\n'
        build(tmp_path, {f'doc{i}.md': line * 40 for i in range(4)})
        c = sv.FileCorpus(tmp_path)
        terms = sv._terms('zebra deployment pipeline restarts nightly midnight')
        one, w1 = c.cost_to_find(terms, 0.5, 1)
        three, w3 = c.cost_to_find(terms, 0.5, 3)
        assert len(w1) == 1 and len(w3) == 3
        assert three > one


class TestMeasure:
    def setup_method(self):
        store.clear_object_cache()

    def teardown_method(self):
        store.clear_object_cache()

    def test_unrecoverable_memories_are_counted_never_priced(self, tmp_path):
        repo = build(tmp_path, {'readme.md': 'this project builds widgets\n' * 30})
        repo.add(mem('written-down', 'this project builds widgets and ships them'))
        repo.add(mem('never-written', 'quokka orbital telemetry cadence recalibration failed'))
        from memgit import usage
        usage.record_hits(repo, ['written-down', 'never-written'])
        r = sv.measure(repo, tmp_path, project='Proj')
        assert r['memories_considered'] == 2
        assert r['unrecoverable_from_files'] == 1
        assert 'never-written' in r['unrecoverable_slugs']
        # the unpriced one contributes nothing to either side of the comparison
        assert r['recoverable_from_files'] == 1
        assert r['without_memgit_tokens'] > 0

    def test_a_store_with_no_recalls_reports_nothing_rather_than_zero_saving(self, tmp_path):
        repo = build(tmp_path, {'readme.md': 'widgets\n'})
        repo.add(mem('unused', 'nobody has ever recalled this'))
        r = sv.measure(repo, tmp_path, project='Proj')
        assert r['memories_considered'] == 0
        assert r['ratio'] is None

    def test_saving_scales_with_recall_count(self, tmp_path):
        repo = build(tmp_path, {'readme.md': 'the zebra deployment restarts nightly\n' * 40})
        repo.add(mem('zebra-fact', 'the zebra deployment restarts nightly'))
        from memgit import usage
        usage.record_hits(repo, ['zebra-fact'])
        one = sv.measure(repo, tmp_path, project='Proj')
        for _ in range(4):
            usage.record_hits(repo, ['zebra-fact'])
        five = sv.measure(repo, tmp_path, project='Proj')
        assert five['recalls_counted'] == 5 * one['recalls_counted']
        assert five['saved_tokens'] == 5 * one['saved_tokens']

    def test_dependency_directories_are_not_read(self, tmp_path):
        build(tmp_path, {'node_modules/pkg/index.js': 'zebra deployment restarts nightly\n' * 50,
                         'readme.md': 'nothing relevant\n'})
        c = sv.FileCorpus(tmp_path)
        assert all('node_modules' not in str(p) for p, _, _ in c.files)


def test_tracked_files_survives_unreadable_paths(tmp_path, monkeypatch):
    """An unreadable entry is one fewer place a fact could hide, not a crash.

    `memgit savings` died with an unhandled PermissionError raised by `is_file()`
    on /proc/1/map_files when run from / inside a container (2026-09-06). pathlib
    swallows permission errors while SCANNING a directory, so an unreadable dir
    alone does not reproduce it — the stat on an individual entry is what threw.
    This forces exactly that.
    """
    from pathlib import Path
    from memgit import savings

    (tmp_path / "readable.md").write_text("a readable fact about penguins")
    (tmp_path / "landmine.md").write_text("stat on this one explodes")

    real_is_file = Path.is_file

    def exploding_is_file(self, *a, **kw):
        if self.name == "landmine.md":
            raise PermissionError(1, "Operation not permitted", str(self))
        return real_is_file(self, *a, **kw)

    monkeypatch.setattr(Path, "is_file", exploding_is_file)

    found = savings._tracked_files(tmp_path)

    names = {p.name for p in found}
    assert "readable.md" in names, "the walk must continue past the bad entry"
    assert "landmine.md" not in names
