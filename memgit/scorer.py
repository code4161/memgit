"""BM25-style relevance scoring for memory search.

Ranking is BM25 over weighted fields, then three bounded multipliers:
priority, project affinity, and measured usage. BM25 stays the primary signal
by construction — every multiplier is clamped inside roughly 0.8x-1.3x, the
same order as the long-standing priority boost, so a frequently-used memory
can nudge past a peer but can never outrank a materially better textual match.

Ranking changes here are measurable: `memgit eval` scores two frozen sets
(real recall events, and a non-circular synthetic set) so a change can be
shown to help rather than assumed to.
"""

from __future__ import annotations
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from .project import project_affinity

if TYPE_CHECKING:
    from .models import Mnemonic


_PRIORITY_BOOST = {1: 0.8, 2: 1.0, 3: 1.3}


@dataclass
class ScoredMnemonic:
    mnemonic: "Mnemonic"
    score: float
    matched_fields: list[str]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


# ── conservative stemming ─────────────────────────────────────────────────────
# Motivating miss (real store, real query): "how do I deploy the portfolio"
# failed to surface `deployment-vercel`, because BM25 saw `deploy` and
# `deployment` as unrelated terms. Suffix folding fixes that whole class —
# deploy/deployment, post/posting, proposal/proposals, rank/ranking.
#
# IMPORTANT — this is ADDITIVE, not destructive. Folding every field to stems
# was tried first and MEASURED WORSE on both eval sets (real-prompt hit@1
# -0.038, MRR -0.027; synthetic hit@1 -0.019), because collapsing tokens
# dilutes the slug and tag fields, which carry the highest precision. So stems
# live in their OWN low-weight pseudo-field alongside the raw fields: an exact
# term still scores at full field weight, and a stem-only match adds a small
# extra contribution. Recall can rise; precision cannot fall.
#
# Deliberately NOT Porter. Porter's later stages (ational->ate, iveness->ive)
# conflate words that mean different things in a technical store, and the
# stems it produces are unreadable in debug output. These suffixes cover the
# observed misses; anything more aggressive must earn its place on the harness.
#
# Guards: a suffix is only stripped when the remaining stem is >= _MIN_STEM
# characters, so `sing`->`s` and `ties`->`t` can't happen, and short tokens are
# returned untouched.
_MIN_STEM = 4
_SUFFIXES = ("ments", "ment", "ings", "ing", "ies", "ed", "es", "s")


def _stem(token: str) -> str:
    """Fold a token to its stem. Idempotent, ASCII-only, no dependencies."""
    if len(token) <= _MIN_STEM or token.isdigit():
        return token
    for suf in _SUFFIXES:
        if not token.endswith(suf):
            continue
        stem = token[: -len(suf)]
        if len(stem) < _MIN_STEM:
            continue
        if suf == "ies":
            return stem + "y"
        # `ing`/`ed` on a doubled consonant: running -> runn -> run. Only when
        # the doubling is a real consonant pair, so `less`/`fall` survive.
        if suf in ("ing", "ings", "ed") and len(stem) > _MIN_STEM \
                and stem[-1] == stem[-2] and stem[-1] not in "aeiou":
            return stem[:-1]
        return stem
    return token


def tokenize_stemmed(text: str) -> list[str]:
    return [_stem(t) for t in _tokenize(text)]


#: Name of the additive stem pseudo-field (see _FIELD_WEIGHT below).
STEM_FIELD = "_stems"


#: Tokenization is the dominant cost in scoring (measured: 76% of runtime,
#: because every memory was re-tokenized three times per query — once for
#: avg_doc_len, once for IDF, once for scoring). Memories are content-
#: addressed, so the SHA is a free cache key that can never go stale: a
#: changed memory is a different SHA and simply misses. Bounded so a long
#: -running server (`memgit serve`) can't grow it without limit.
_TOKEN_CACHE: dict[str, dict[str, list[str]]] = {}
_TOKEN_CACHE_MAX = 20000


def _field_tokens(m: "Mnemonic") -> dict[str, list[str]]:
    """Return tokenized fields, cached by content SHA where one exists."""
    key = m.sha
    if key is not None:
        hit = _TOKEN_CACHE.get(key)
        if hit is not None:
            return hit
    fields = {
        "slug": _tokenize(m.slug),
        "rule": _tokenize(m.rule or ""),
        "why": _tokenize(m.why or ""),
        "when": _tokenize(m.when or ""),
        "tags": _tokenize(" ".join(m.tags)),
        "desc": _tokenize(m.desc or ""),
        "body": _tokenize(m.body or ""),
    }
    # Stems of the high-signal fields only, as a separate low-weight field.
    # Body is excluded: it is long, already weighted 0.4, and stemming it adds
    # noise far faster than recall.
    stem_src = fields["slug"] + fields["rule"] + fields["why"] + fields["tags"]
    fields[STEM_FIELD] = [_stem(t) for t in stem_src]
    if key is not None:
        if len(_TOKEN_CACHE) >= _TOKEN_CACHE_MAX:
            _TOKEN_CACHE.clear()
        _TOKEN_CACHE[key] = fields
    return fields


def clear_token_cache() -> None:
    """Drop the tokenization cache (tests, and after a bulk rewrite)."""
    _TOKEN_CACHE.clear()


# Field importance multipliers
_FIELD_WEIGHT = {
    "slug": 2.0,
    "rule": 1.5,
    "tags": 1.8,
    "why": 1.0,
    "when": 0.8,
    "desc": 0.6,
    "body": 0.4,
    # Additive stem field: low enough that a stem-only match never outranks a
    # real term match, high enough to lift a memory that would otherwise be
    # invisible to the query ("deploy" -> `deployment-vercel`).
    # Weight chosen by sweep on `memgit eval` (0.25 / 0.35 / 0.5 / 0.8), not by
    # taste. 0.35 is the only setting that improves the real-prompt set without
    # moving the synthetic correctness floor; 0.8 was clearly worse.
    STEM_FIELD: 0.35,
}

# Score multipliers for memories belonging to the project being worked on.
# An affinity nudge, not a filter — global rules still surface everywhere.
# Exact workspace match nudges hardest; same project tree (a session in
# BITS/bits_back drawing on BITS memories, or vice versa) still nudges.
_PROJECT_BOOST_EXACT = 1.25
_PROJECT_BOOST_FAMILY = 1.15

# ── measured usage ────────────────────────────────────────────────────────────
# The store already measures which memories actually help: every surfaced
# memory increments cache/usage.json, and usage.usage_score() decays those
# hits on a 14-day half-life. Until 0.8.0 that signal fed only core-guide
# promotion — ranking ignored ground truth it was already collecting.
#
# The term is deliberately WEAK and bounded. A memory nobody has used is never
# punished below 1.0 (a brand-new correction must not be buried under an old
# favourite), and a heavily-used one tops out at a nudge.
#
# MEASURED (memgit eval, 400-case real-prompt set + 400-case synthetic set,
# store of 1,727 memories):
#   real-prompt set   hit@1 +0.015  recall@3 +0.020  MRR +0.016
#   ...de-confounded  hit@1  0.000  recall@3 +0.020  MRR +0.001
#   synthetic set     hit@1  0.000  recall@3 -0.006  MRR -0.002
# Small but never materially harmful, and positive on real prompts on both the
# full and the de-confounded slice. Kept at this weight, not raised, because
# nothing in the evidence justifies more.
#
# A RECENCY multiplier was built alongside this one and REMOVED before release:
# on the same harness it cost hit@1 -0.020 and MRR -0.018 on the real-prompt
# set while adding nothing on the synthetic set. Staleness is a write-time
# problem (supersession, conflict detection on save), not something a blunt
# global age multiplier fixes. Do not reintroduce it without numbers.
_USAGE_BOOST_MAX = 1.20        # asymptote for a heavily-, recently-used memory
_USAGE_HALF_SATURATION = 6.0   # decayed-usage score at which half the boost applies

# BM25 parameters
_K1 = 1.5
_B = 0.75


def usage_multiplier(decayed_hits: float) -> float:
    """Bounded boost from measured, recency-decayed usage.

    Saturating (hits / (hits + k)) rather than linear: the difference between
    0 and 5 decayed hits is meaningful signal, the difference between 200 and
    400 is not, and a linear term would let a single hot memory dominate every
    query it lexically touches.
    """
    if decayed_hits <= 0:
        return 1.0
    frac = decayed_hits / (decayed_hits + _USAGE_HALF_SATURATION)
    return 1.0 + (_USAGE_BOOST_MAX - 1.0) * frac


def _doc_len(fields: dict) -> int:
    """Length used for BM25 normalisation.

    The stem pseudo-field is a derived copy of fields already counted, so it is
    excluded here — and must be excluded from `avg_len` too. Counting it in one
    and not the other silently shifts every score (found the hard way).
    """
    return sum(len(toks) for name, toks in fields.items() if name != STEM_FIELD)


def _avg_doc_len(mnemonics: list["Mnemonic"], fields_by_id=None) -> float:
    if not mnemonics:
        return 1.0
    total = 0
    for m in mnemonics:
        fields = fields_by_id[id(m)] if fields_by_id is not None else _field_tokens(m)
        total += _doc_len(fields)
    return total / len(mnemonics)


def score(
    query: str,
    mnemonics: list["Mnemonic"],
    top_k: int = 10,
    boost_project: str = None,
    scope_project: str = None,
    usage: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> list[ScoredMnemonic]:
    """Score mnemonics against query and return top-k by relevance.

    boost_project: memories whose .project matches get a relevance nudge,
    so the current workspace's memories outrank same-text matches from
    other projects without hiding global rules.

    scope_project: PRE-FILTER the candidates to that project's family plus
    explicit-global memories before anything is computed — IDF is then
    derived from the scoped corpus, so a term common in a foreign project
    can't distort ranking here. This is the filter-by-default boundary;
    boost_project still orders within the scoped pool.

    usage: the ledger dict from usage.read_usage(). When supplied, a bounded
    boost is applied from each memory's recency-decayed hit count — ranking
    then learns from which memories actually got used. Omitted (None) means
    no usage term at all, so every existing caller keeps its exact behaviour.

    now: reference time for the usage and recency decays (tests pin this).
    """
    if scope_project:
        from .project import scope_filter
        mnemonics = scope_filter(mnemonics, scope_project)
    if not query.strip() or not mnemonics:
        return []

    query_terms = set(_tokenize(query))
    if not query_terms:
        return []
    # Stems only carry information where they differ from the raw term;
    # a stem identical to a term already matched would double-count it.
    query_stems = {_stem(t) for t in query_terms} - query_terms

    N = len(mnemonics)
    # Tokenize each memory exactly once per query; the cache above makes this
    # free across queries, this dict makes it free within one.
    fields_by_id = {id(m): _field_tokens(m) for m in mnemonics}
    avg_len = _avg_doc_len(mnemonics, fields_by_id)
    now = now or datetime.now(timezone.utc)
    if usage:
        from .usage import usage_score as _usage_score

    # Compute IDF per term across the corpus. Raw terms and stems are counted
    # in separate namespaces — they live in different fields, and a stem that
    # happens to equal another term must not inherit that term's IDF.
    df: dict[str, int] = {}
    df_stem: dict[str, int] = {}
    for m in mnemonics:
        seen: set[str] = set()
        seen_stem: set[str] = set()
        for name, toks in fields_by_id[id(m)].items():
            if name == STEM_FIELD:
                for tok in toks:
                    if tok in query_stems and tok not in seen_stem:
                        df_stem[tok] = df_stem.get(tok, 0) + 1
                        seen_stem.add(tok)
            else:
                for tok in toks:
                    if tok in query_terms and tok not in seen:
                        df[tok] = df.get(tok, 0) + 1
                        seen.add(tok)

    def _idf(n_t: int) -> float:
        return math.log((N - n_t + 0.5) / (n_t + 0.5) + 1)

    idf: dict[str, float] = {t: _idf(df.get(t, 0)) for t in query_terms}
    idf_stem: dict[str, float] = {t: _idf(df_stem.get(t, 0)) for t in query_stems}

    results: list[ScoredMnemonic] = []

    for m in mnemonics:
        fields = fields_by_id[id(m)]
        doc_len = _doc_len(fields)
        score_val = 0.0
        matched: list[str] = []
        norm_den = _K1 * (1 - _B + _B * doc_len / avg_len)

        for field_name, toks in fields.items():
            terms = query_stems if field_name == STEM_FIELD else query_terms
            if not terms:
                continue
            table = idf_stem if field_name == STEM_FIELD else idf
            weight = _FIELD_WEIGHT.get(field_name, 1.0)
            for term in terms:
                tf = toks.count(term)
                if tf == 0:
                    continue
                if field_name not in matched:
                    matched.append(field_name)
                norm_tf = (tf * (_K1 + 1)) / (tf + norm_den)
                score_val += weight * table.get(term, 0.0) * norm_tf

        # Priority boost
        score_val *= _PRIORITY_BOOST.get(m.priority, 1.0)

        # Project affinity boost
        if boost_project:
            affinity = project_affinity(m.project, boost_project)
            if affinity == 2:
                score_val *= _PROJECT_BOOST_EXACT
            elif affinity == 1:
                score_val *= _PROJECT_BOOST_FAMILY

        # Measured-usage boost — ground truth on what actually helps.
        if usage:
            entry = usage.get(m.slug)
            if entry:
                score_val *= usage_multiplier(_usage_score(entry, now))

        if score_val > 0:
            results.append(ScoredMnemonic(m, round(score_val, 4), matched))

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]
