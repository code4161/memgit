"""BM25-style relevance scoring for memory search."""

from __future__ import annotations
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

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


def _field_tokens(m: "Mnemonic") -> dict[str, list[str]]:
    """Return tokenized fields with their weights."""
    return {
        "slug": _tokenize(m.slug),
        "rule": _tokenize(m.rule or ""),
        "why": _tokenize(m.why or ""),
        "when": _tokenize(m.when or ""),
        "tags": _tokenize(" ".join(m.tags)),
        "desc": _tokenize(m.desc or ""),
        "body": _tokenize(m.body or ""),
    }


# Field importance multipliers
_FIELD_WEIGHT = {
    "slug": 2.0,
    "rule": 1.5,
    "tags": 1.8,
    "why": 1.0,
    "when": 0.8,
    "desc": 0.6,
    "body": 0.4,
}

# Score multipliers for memories belonging to the project being worked on.
# An affinity nudge, not a filter — global rules still surface everywhere.
# Exact workspace match nudges hardest; same project tree (a session in
# BITS/bits_back drawing on BITS memories, or vice versa) still nudges.
_PROJECT_BOOST_EXACT = 1.25
_PROJECT_BOOST_FAMILY = 1.15

# BM25 parameters
_K1 = 1.5
_B = 0.75


def _avg_doc_len(mnemonics: list["Mnemonic"]) -> float:
    if not mnemonics:
        return 1.0
    total = sum(
        sum(len(toks) for toks in _field_tokens(m).values())
        for m in mnemonics
    )
    return total / len(mnemonics)


def score(
    query: str,
    mnemonics: list["Mnemonic"],
    top_k: int = 10,
    boost_project: str = None,
) -> list[ScoredMnemonic]:
    """Score mnemonics against query and return top-k by relevance.

    boost_project: memories whose .project matches get a relevance nudge,
    so the current workspace's memories outrank same-text matches from
    other projects without hiding global rules.
    """
    if not query.strip() or not mnemonics:
        return []

    query_terms = set(_tokenize(query))
    if not query_terms:
        return []

    N = len(mnemonics)
    avg_len = _avg_doc_len(mnemonics)

    # Compute IDF per term across the corpus
    df: dict[str, int] = {}
    for m in mnemonics:
        seen = set()
        for toks in _field_tokens(m).values():
            for tok in toks:
                if tok in query_terms and tok not in seen:
                    df[tok] = df.get(tok, 0) + 1
                    seen.add(tok)

    idf: dict[str, float] = {}
    for term in query_terms:
        n_t = df.get(term, 0)
        idf[term] = math.log((N - n_t + 0.5) / (n_t + 0.5) + 1)

    results: list[ScoredMnemonic] = []

    for m in mnemonics:
        fields = _field_tokens(m)
        doc_len = sum(len(toks) for toks in fields.values())
        score_val = 0.0
        matched: list[str] = []

        for term in query_terms:
            for field_name, toks in fields.items():
                tf = toks.count(term)
                if tf == 0:
                    continue
                if field_name not in matched:
                    matched.append(field_name)
                weight = _FIELD_WEIGHT.get(field_name, 1.0)
                norm_tf = (tf * (_K1 + 1)) / (
                    tf + _K1 * (1 - _B + _B * doc_len / avg_len)
                )
                score_val += weight * idf.get(term, 0.0) * norm_tf

        # Priority boost
        score_val *= _PRIORITY_BOOST.get(m.priority, 1.0)

        # Project affinity boost
        if boost_project:
            affinity = project_affinity(m.project, boost_project)
            if affinity == 2:
                score_val *= _PROJECT_BOOST_EXACT
            elif affinity == 1:
                score_val *= _PROJECT_BOOST_FAMILY

        if score_val > 0:
            results.append(ScoredMnemonic(m, round(score_val, 4), matched))

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]
