"""Prompt-injection detection for memory content.

memgit injects memory `rule`/`body` text into an agent's context verbatim and
at high authority. For a single-operator store that is the owner's own words —
safe. But content that arrives from OUTSIDE the operator (a body seeded from a
repo README by `onboard`, or a memory pulled from another writer via team sync)
can carry instruction-shaped text — "ignore previous instructions", "you are
now…", a fake "system:" line — that would ride into context as trusted.

This module only DETECTS. The policy lives at the save/import boundary: content
that trips the detector is marked `unverified` (see Mnemonic.unverified), which
keeps it out of high-authority injection until the operator confirms it. We do
not silently rewrite the user's words — detection + quarantine, not censorship.
"""
from __future__ import annotations

import re

# Patterns that, in memory content, signal an attempt to steer the agent rather
# than record a fact. Kept conservative: each is an imperative aimed at the
# model, not vocabulary that shows up in ordinary notes.
_PATTERNS = [
    (re.compile(r'\bignore\s+(?:all\s+)?(?:previous|prior|above|earlier)\s+'
                r'(?:instructions?|prompts?|context|messages?)\b', re.I),
     'ignore-previous-instructions'),
    (re.compile(r'\bdisregard\s+(?:all\s+)?(?:previous|prior|above|earlier|your)\b', re.I),
     'disregard-previous'),
    (re.compile(r'\byou\s+are\s+now\s+(?:a|an|the)\b', re.I), 'role-reassignment'),
    (re.compile(r'\b(?:new|updated)\s+(?:system\s+)?(?:instructions?|rules?|directives?)\s*[:=]', re.I),
     'new-instructions'),
    (re.compile(r'(?m)^\s*(?:system|assistant|developer)\s*:', re.I), 'fake-role-line'),
    (re.compile(r'<\s*/?\s*(?:system|instructions?|prompt)\s*>', re.I), 'fake-role-tag'),
    (re.compile(r'\boverride\s+(?:the\s+)?(?:previous|prior|system|safety)\b', re.I),
     'override-directive'),
    (re.compile(r'\b(?:always|from\s+now\s+on)\s+(?:respond|reply|answer|do|say)\b', re.I),
     'behavioral-override'),
    (re.compile(r'\bdo\s+not\s+(?:tell|inform|mention\s+to)\s+the\s+user\b', re.I),
     'conceal-from-user'),
]


def detect_injection(*texts: str) -> list[str]:
    """Return the names of injection patterns found across the given texts.

    Deduped, order-stable. Empty list = nothing suspicious. Meant for `rule`
    and `body` on a save/import; a non-empty result should quarantine the
    memory as `unverified`, not block it.
    """
    found: list[str] = []
    blob = '\n'.join(t for t in texts if t)
    if not blob.strip():
        return found
    for rx, name in _PATTERNS:
        if name not in found and rx.search(blob):
            found.append(name)
    return found


def looks_injected(*texts: str) -> bool:
    return bool(detect_injection(*texts))
