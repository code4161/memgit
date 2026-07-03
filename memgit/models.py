"""Core data models for memgit."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Mnemonic:
    """A single atomic memory unit — one fact, rule, lesson, or reference."""
    type_code: str       # fb|us|pj|rf|cn|lx
    slug: str            # kebab-case unique identifier
    timestamp: datetime
    rule: str            # primary rule/fact (required) — compact one-liner
    priority: int = 2   # 1=low, 2=medium, 3=critical
    tags: list[str] = field(default_factory=list)
    why: Optional[str] = None
    when: Optional[str] = None
    desc: Optional[str] = None
    body: Optional[str] = None     # full long-form detail (multi-line ok)
    project: Optional[str] = None  # which project/workspace this belongs to
    who: Optional[str] = None
    where: Optional[str] = None
    dl: Optional[str] = None
    inc: Optional[str] = None
    cost: Optional[str] = None
    supersedes: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    source: Optional[str] = None
    sha: Optional[str] = None  # computed by store


@dataclass
class MindStateEntry:
    """One entry in a MindState — maps slug to mnemonic SHA."""
    slug: str
    mnem_sha: str


@dataclass
class MindState:
    """Snapshot of all active memories at a point in time (git tree equivalent)."""
    timestamp: datetime
    entries: list[MindStateEntry] = field(default_factory=list)
    sha: Optional[str] = None  # computed by store

    @property
    def count(self) -> int:
        return len(self.entries)


@dataclass
class DiffSummary:
    """Summary of what changed between two MindStates."""
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)


@dataclass
class Checkpoint:
    """Immutable snapshot of a MindState (git commit equivalent)."""
    mindstate_sha: str
    timestamp: datetime
    trigger: str           # session_end|session_start|explicit|auto|merge|import
    message: str
    author: str
    session_id: str
    parent_sha: Optional[str] = None
    diff_summary: Optional[DiffSummary] = None
    sha: Optional[str] = None  # computed by store


@dataclass
class Thread:
    """Named pointer to a Checkpoint — an independent line of memory (git branch equivalent)."""
    name: str
    head_sha: str
    created_at: datetime
    description: str = ""
