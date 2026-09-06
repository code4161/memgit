"""What memory costs against what finding the same fact would have cost.

`metrics.py` refuses to print a savings number, and its reasoning was right as
far as it went: you cannot observe a file read that did not happen. But that
argument proves only that the *naive* counterfactual is unmeasurable. A
DEFINED counterfactual is measurable, and this module measures one:

    Without memgit, an agent that needed the fact in a memory would have to
    find it by reading this project's files: grep for the memory's distinctive
    terms, then open the best-matching files and read them.

That path is mechanical, so its cost can be computed rather than guessed. The
comparison is:

    memgit        the tokens actually injected to deliver the fact
    without       the tokens of the files an agent would have had to read to
                  recover the same fact

Three honesty rules are built into the code, not left to the caller:

1. **A memory that no file contains is never converted into tokens.** It goes
   into `unrecoverable` and is reported as a count. Most of this store is
   decisions, corrections and gotchas that were never written down anywhere
   else, and pricing them as "infinite tokens saved" would be the exact
   fabrication `metrics.py` refused to make. The honest statement is that
   without memgit those facts are not found at any price.
2. **Every parameter is explicit and reported** — the match threshold, how many
   files a reader is assumed to open, the size cap. Change them and the number
   changes; that is a property of the counterfactual, not a flaw to hide.
3. **The estimate is deliberately conservative.** It counts only the files, not
   the grep output, not the turns spent deciding what to open, and not the
   second and third attempts when the first read misses. Real cost is higher.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Iterable, Optional

from .tokens import count_tokens

#: A PASSAGE must carry at least this share of a memory's distinctive terms
#: before we accept that reading its file would have taught you the fact.
DEFAULT_MATCH = 0.5
#: Matching is done over passages, not whole files, and this is why: a 40 KB
#: document contains half the vocabulary of almost any memory, so a whole-file
#: term overlap makes the three largest docs in a repo "contain" everything.
#: That biases the counterfactual twice over, because those same files are
#: also the most expensive to read. A fact lives in a passage; requiring the
#: terms to co-occur inside one is the difference between "this file mentions
#: those words somewhere" and "this file states the fact".
WINDOW_CHARS = 1200
WINDOW_STRIDE = 600
#: How many files the counterfactual reader opens. Three is the realistic
#: "grep, then read the top few hits" behaviour; one would understate the cost
#: of finding anything, ten would flatter memgit.
DEFAULT_READS = 3
#: Files larger than this are assumed to be read in part, not whole, and are
#: counted at this cap. Keeps one vendored bundle from dominating a total.
MAX_FILE_TOKENS = 8000
#: Terms shorter than this carry no retrieval signal.
MIN_TERM_LEN = 4

_WORD = re.compile(r"[A-Za-z0-9_]+")

_STOPWORDS = {
    "this", "that", "with", "from", "have", "been", "were", "will", "would",
    "when", "what", "which", "there", "their", "then", "than", "them", "they",
    "into", "only", "also", "before", "after", "because", "every", "never",
    "always", "should", "could", "must", "does", "done", "make", "made",
    "over", "under", "each", "same", "such", "some", "more", "most", "less",
    "about", "against", "between", "during", "while", "where", "here",
    "memgit", "memory", "memories", "note", "notes",
}

#: Extensions that are text a reader would actually open.
_TEXT_SUFFIXES = {
    ".md", ".txt", ".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".bash", ".zsh",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".sql", ".rb", ".go",
    ".rs", ".java", ".c", ".h", ".cpp", ".hpp", ".css", ".html", ".rst",
}


def _terms(text: str) -> set[str]:
    """Distinctive lowercase terms of a piece of text."""
    out = set()
    for w in _WORD.findall(text.lower()):
        if len(w) >= MIN_TERM_LEN and w not in _STOPWORDS and not w.isdigit():
            out.add(w)
    return out


#: Directories a reader would never open, and that would swamp the count.
_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", ".next", ".nuxt", "target", "vendor", ".terraform",
    "site-packages", ".tox", "coverage", ".cache",
    # The memory store itself, which must NEVER count as a file the
    # counterfactual reader could open: the whole question is what it would
    # cost to find the fact WITHOUT memgit, and reading memgit's own objects
    # is not that. Found by a test whose saving failed to scale linearly with
    # recall count, because the usage ledger inside the store was growing the
    # corpus between two measurements of the same store.
    ".memgit", ".memgit-store", "memgit-store",
}


def _tracked_files(root: Path) -> list[Path]:
    """Every file a reader could plausibly open under root.

    This WALKS rather than asking git, and the reason is measured: on this
    workspace `git ls-files` at the root returned 149 files because the
    sub-projects are their own repositories, and a walk returned 1,965. An
    agent searching for a fact does not stop at a repository boundary, so
    stopping there made the counterfactual look cheaper than it is — the share
    of memories found in no file fell from 71.6% to 40.6% once the sub-repos
    were included. Build output and dependency trees are skipped by name
    instead, which is what .gitignore was doing for us.
    """
    out = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        out.append(path)
    return out


def _passages(text: str) -> list[set[str]]:
    """Overlapping windows of the text, each as a term set."""
    if len(text) <= WINDOW_CHARS:
        return [_terms(text)]
    out = []
    for start in range(0, len(text), WINDOW_STRIDE):
        chunk = text[start:start + WINDOW_CHARS]
        if not chunk:
            break
        out.append(_terms(chunk))
        if start + WINDOW_CHARS >= len(text):
            break
    return out


class FileCorpus:
    """The project's readable files, indexed by passage, built once."""

    def __init__(self, root: Path):
        self.root = root
        self.files: list[tuple[Path, list[set[str]], int]] = []
        self.skipped = 0
        for path in _tracked_files(root):
            if path.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            try:
                if path.stat().st_size > 2_000_000:
                    self.skipped += 1
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                self.skipped += 1
                continue
            self.files.append(
                (path, _passages(text), min(count_tokens(text), MAX_FILE_TOKENS)))

    def cost_to_find(self, terms: set[str], match: float,
                     reads: int) -> tuple[Optional[int], list[str]]:
        """Tokens a reader would spend to recover a fact with these terms.

        A file counts only if ONE passage inside it carries enough of the
        memory's terms. Returns (None, []) when no passage anywhere does — the
        fact is not in the files, which is a finding and not a zero.
        """
        if not terms:
            return None, []
        n = len(terms)
        scored = []
        for path, passages, tok in self.files:
            best = 0.0
            for p in passages:
                hit = len(terms & p) / n
                if hit > best:
                    best = hit
                    if best >= 1.0:
                        break
            if best >= match:
                scored.append((best, tok, path))
        if not scored:
            return None, []
        scored.sort(key=lambda r: (-r[0], r[1]))
        top = scored[:reads]
        return (sum(t for _, t, _ in top),
                [str(p.relative_to(self.root)) for _, _, p in top])


def recall_line_tokens(m) -> int:
    """What one recall of this memory actually injects.

    The recall block renders `- [slug] rule`, which is the form the model is
    charged for. Not the whole memory: the body is only paid for when the model
    follows up with get_memory, and that follow-up is counted where it happens.
    """
    return count_tokens(f"- [{m.slug}] {m.rule or ''}")


def measure(repo, root: Path, project: Optional[str] = None,
            match: float = DEFAULT_MATCH, reads: int = DEFAULT_READS,
            include_unused: bool = False) -> dict:
    """Compare what memgit charged against what reading would have cost.

    Only memories with recorded recalls count by default: a memory nobody has
    surfaced has neither cost nor saved anything, and including it would
    inflate both sides with traffic that never happened.
    """
    from .usage import read_usage

    usage = read_usage(repo)
    corpus = FileCorpus(root)

    rows = []
    for m in repo.list():
        if project is not None and m.project != project:
            continue
        hits = int((usage.get(m.slug) or {}).get("hits", 0))
        if hits <= 0 and not include_unused:
            continue
        cost, where = corpus.cost_to_find(
            _terms(f"{m.slug} {m.rule or ''}"), match, reads)
        rows.append({
            "slug": m.slug,
            "hits": hits,
            "memgit_tokens_per_recall": recall_line_tokens(m),
            "without_tokens_per_recall": cost,
            "found_in": where,
        })

    recoverable = [r for r in rows if r["without_tokens_per_recall"] is not None]
    unrecoverable = [r for r in rows if r["without_tokens_per_recall"] is None]

    memgit_total = sum(r["memgit_tokens_per_recall"] * max(r["hits"], 1)
                       for r in recoverable)
    without_total = sum(r["without_tokens_per_recall"] * max(r["hits"], 1)
                        for r in recoverable)

    top = sorted(recoverable,
                 key=lambda r: (r["without_tokens_per_recall"]
                                - r["memgit_tokens_per_recall"]) * max(r["hits"], 1),
                 reverse=True)[:10]

    return {
        "project": project,
        "root": str(root),
        "files_indexed": len(corpus.files),
        "parameters": {"match": match, "reads": reads,
                       "max_file_tokens": MAX_FILE_TOKENS},
        "memories_considered": len(rows),
        "recalls_counted": sum(max(r["hits"], 1) for r in recoverable),
        "recoverable_from_files": len(recoverable),
        "unrecoverable_from_files": len(unrecoverable),
        "memgit_tokens": memgit_total,
        "without_memgit_tokens": without_total,
        "saved_tokens": without_total - memgit_total,
        "ratio": (without_total / memgit_total) if memgit_total else None,
        "top_savers": top,
        "unrecoverable_slugs": [r["slug"] for r in unrecoverable][:20],
    }
