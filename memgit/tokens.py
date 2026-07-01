"""Token counting utilities — approximation only, no external dependencies.

Uses a character-based model calibrated against GPT-4 tokenizer averages:
  - ~4 chars/token for English prose
  - Code/slugs are slightly denser (~3.5 chars/token)
  - Good enough for the 3–5x comparisons we display in `memgit stats`
"""

from __future__ import annotations
import re


def count_tokens(text: str) -> int:
    """Approximate token count for `text` using a char-density model."""
    if not text:
        return 0
    # Strip whitespace normalization
    text = text.strip()
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
_GPT4O_PER_MTK = 5.0   # $5/1M tokens
_CLAUDE_SONNET_PER_MTK = 3.0  # $3/1M tokens


def token_cost_usd(tokens: int, model: str = 'gpt4o') -> float:
    rate = _CLAUDE_SONNET_PER_MTK if model == 'claude' else _GPT4O_PER_MTK
    return tokens * rate / 1_000_000
