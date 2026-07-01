"""Token counting utilities.

Uses tiktoken (GPT-4o encoding) when installed — `pip install memgit[tokens]` —
otherwise falls back to a word-based approximation:
  - Each whitespace-separated word averages ~1.3 tokens
  - Good enough for the order-of-magnitude comparisons in `memgit stats`
"""

from __future__ import annotations
import re

try:
    import tiktoken
    _ENCODER = tiktoken.get_encoding('o200k_base')
except Exception:
    _ENCODER = None


def count_tokens(text: str) -> int:
    """Token count for `text` — exact via tiktoken if available, else approximate."""
    if not text:
        return 0
    text = text.strip()
    if _ENCODER is not None:
        return max(1, len(_ENCODER.encode(text)))
    # Count whitespace-separated tokens (rough word count)
    words = len(re.findall(r'\S+', text))
    # Each word averages ~1.3 tokens (handles punctuation, subwords, numbers)
    return max(1, round(words * 1.3))


def memory_tokens(m) -> int:
    """Token cost of a single Mnemonic as context."""
    from .toon import serialize_mnemonic
    return count_tokens(serialize_mnemonic(m))


def all_memories_tokens(mnemonics: list) -> int:
    """Token cost of loading ALL memories (the claude.md / dump approach)."""
    return sum(memory_tokens(m) for m in mnemonics)


def search_tokens(scored: list, query: str) -> int:
    """Token cost of a search result set (top-k relevance approach)."""
    return sum(memory_tokens(r.mnemonic) for r in scored)


# GPT-4o pricing (input, per million tokens) as of 2026
_GPT4O_PER_MTK = 2.5   # $2.50/1M tokens
_CLAUDE_SONNET_PER_MTK = 3.0  # $3/1M tokens


def token_cost_usd(tokens: int, model: str = 'gpt4o') -> float:
    rate = _CLAUDE_SONNET_PER_MTK if model == 'claude' else _GPT4O_PER_MTK
    return tokens * rate / 1_000_000
