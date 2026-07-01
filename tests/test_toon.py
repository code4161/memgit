"""Tests for TOON parser and serializer."""

import pytest
from datetime import datetime, timezone

from memgit.models import Mnemonic, MindState, MindStateEntry, Checkpoint, DiffSummary
from memgit.toon import (
    parse_toon, serialize_mnemonic, serialize_mindstate, serialize_checkpoint,
    format_ts,
)


def ts(s='2026-06-14T08:22Z'):
    from memgit.toon import _parse_ts
    return _parse_ts(s)


# ── Mnemonic round-trip ────────────────────────────────────────────────────────

def test_feedback_roundtrip():
    toon = """TOON1|fb|ig-pipeline-no-fallback|2026-06-14T08:22Z
#instagram #pipeline
RULE:abort+log on orchestration fail — never ship weak fallback post
WHY:day12 morning; claude timeout → generic content posted live
WHEN:any IG posting pipeline, pre-publish gate check"""

    objs = parse_toon(toon)
    assert len(objs) == 1
    m = objs[0]
    assert isinstance(m, Mnemonic)
    assert m.slug == 'ig-pipeline-no-fallback'
    assert m.type_code == 'fb'
    assert 'abort+log' in m.rule
    assert 'day12' in m.why
    assert 'IG posting' in m.when
    assert 'instagram' in m.tags
    assert 'pipeline' in m.tags

    # re-serialize and re-parse
    again = parse_toon(serialize_mnemonic(m))
    assert len(again) == 1
    m2 = again[0]
    assert m2.slug == m.slug
    assert m2.rule == m.rule
    assert m2.why == m.why
    assert m2.when == m.when


def test_user_memory_with_priority():
    toon = """TOON1|us|profile-main|2026-01-01T00:00Z|!3
#engineer #author
RULE:AI/full-stack engineer; GRC/compliance corporate lane; book author
WHO:Python+TypeScript,new-to-React,₹50L-by-dec26"""

    objs = parse_toon(toon)
    m = objs[0]
    assert m.type_code == 'us'
    assert m.priority == 3
    assert m.who == 'Python+TypeScript,new-to-React,₹50L-by-dec26'


def test_reference_memory():
    toon = """TOON1|rf|linear-bugs-ingest|2026-06-01T10:00Z
#linear #bugs
WHERE:linear.app → project "INGEST"
RULE:all pipeline bugs tracked in Linear "INGEST" project"""

    objs = parse_toon(toon)
    m = objs[0]
    assert m.type_code == 'rf'
    assert m.where is not None
    assert 'INGEST' in m.where


def test_lesson_memory():
    toon = """TOON1|lx|eodhd-validate-before-buy|2026-06-29T09:00Z|!3
#vendor #trading
RULE:never buy a paid data API until NSE/BSE coverage is empirically proven
INC:2026-06-29; EODHD purchased ~₹5664; support confirmed zero NSE/BSE data
COST:₹5664 direct loss + 2 days debugging"""

    objs = parse_toon(toon)
    m = objs[0]
    assert m.type_code == 'lx'
    assert m.priority == 3
    assert m.inc is not None
    assert m.cost is not None
    assert '₹5664' in m.cost


def test_relationship_fields():
    toon = """TOON1|pj|upwork-automation-live|2026-06-28T10:14Z
RULE:upwork pipeline live
~REL:personal-assistant-skill,admin-panel
~SUP:old-upwork-notes
~SRC:https://example.com"""

    objs = parse_toon(toon)
    m = objs[0]
    assert 'personal-assistant-skill' in m.related
    assert 'admin-panel' in m.related
    assert 'old-upwork-notes' in m.supersedes
    assert m.source == 'https://example.com'


def test_multiple_objects_in_file():
    toon = """TOON1|fb|rule-a|2026-06-01T10:00Z
RULE:first rule

TOON1|us|profile|2026-06-01T10:00Z
RULE:second rule"""

    objs = parse_toon(toon)
    assert len(objs) == 2
    assert objs[0].slug == 'rule-a'
    assert objs[1].slug == 'profile'


def test_canonical_serialization_deterministic():
    m = Mnemonic(
        type_code='fb',
        slug='test-slug',
        timestamp=ts(),
        rule='the rule',
        why='the why',
        when='the when',
        tags=['beta', 'alpha'],
    )
    s1 = serialize_mnemonic(m, canonical=True)
    s2 = serialize_mnemonic(m, canonical=True)
    assert s1 == s2
    # Tags should be sorted
    assert s1.index('alpha') < s1.index('beta')


# ── MindState round-trip ───────────────────────────────────────────────────────

def test_mindstate_roundtrip():
    ms = MindState(
        timestamp=ts(),
        entries=[
            MindStateEntry(slug='rule-b', mnem_sha='a' * 64),
            MindStateEntry(slug='rule-a', mnem_sha='b' * 64),
        ],
        sha='c' * 64,
    )
    toon = serialize_mindstate(ms)
    objs = parse_toon(toon)
    assert len(objs) == 1
    ms2 = objs[0]
    assert isinstance(ms2, MindState)
    assert ms2.count == 2
    # Entries should be sorted by slug
    assert ms2.entries[0].slug == 'rule-a'
    assert ms2.entries[1].slug == 'rule-b'


# ── Checkpoint round-trip ─────────────────────────────────────────────────────

def test_checkpoint_roundtrip():
    ck = Checkpoint(
        mindstate_sha='m' * 64,
        timestamp=ts(),
        trigger='session_end',
        message='Added 2 memories',
        author='hari',
        session_id='sess-123',
        parent_sha='p' * 64,
        diff_summary=DiffSummary(added=['new-rule'], modified=['old-rule'], removed=[]),
        sha='c' * 64,
    )
    toon = serialize_checkpoint(ck)
    objs = parse_toon(toon)
    assert len(objs) == 1
    ck2 = objs[0]
    assert isinstance(ck2, Checkpoint)
    assert ck2.mindstate_sha == 'm' * 64
    assert ck2.trigger == 'session_end'
    assert ck2.message == 'Added 2 memories'
    assert ck2.author == 'hari'
    assert ck2.parent_sha == 'p' * 64
    assert 'new-rule' in ck2.diff_summary.added
    assert 'old-rule' in ck2.diff_summary.modified


def test_checkpoint_no_parent():
    ck = Checkpoint(
        mindstate_sha='m' * 64,
        timestamp=ts(),
        trigger='explicit',
        message='Initial',
        author='u',
        session_id='s',
        parent_sha=None,
        sha='c' * 64,
    )
    toon = serialize_checkpoint(ck)
    objs = parse_toon(toon)
    ck2 = objs[0]
    assert ck2.parent_sha is None
