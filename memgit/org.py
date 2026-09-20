"""Deciding which company a project belongs to, from evidence inside the work.

Nobody is asked. A memory tool that stops to ask which company it is looking at
is a tool that gets the answer wrong the one time nobody is watching, so the
company is derived from what the project itself says and the derivation is
recorded with its evidence so it can be checked.

THE RULE THAT MATTERS: a path segment nominates a company, it never decides
one. Measured on a real tree, one folder held six unrelated clients and another
held three unrelated organisations. Taking a folder name as a company fuses
each set into one fictional company and files one client's record inside
another client's scope, which is worse than having no company tier at all.

So a candidate is assigned only when the project ATTESTS it from the inside.
Five evidence classes, and a candidate needs two of them with at least one from
inside:

    declared   an agent or a conversation said so                 inside
    repo       a git remote owner, a manifest domain              inside
    prose      the name in the project's own CLAUDE.md or README  inside
    memory     the name across the project's existing memories    inside
    folder     the parent directory name                          outside

Two companies attested for one project is a CONFLICT and assigns nothing. That
is not a theoretical case: on the store this was built against, one project
name was claimed by a client of one company and by a component of another, and
a resolver that picked either would have put one company's infrastructure into
the other's scope.

A parent folder that none of its children attest is recorded as a CONTAINER and
is never nominated again.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

from .tiers import (attests_identity, company_candidate,
                    read_org, slugify_org)

#: Files read when looking for a company name in a project's own prose. Bounded
#: because this runs on a save path: a resolver that stops to read a repository
#: is a resolver someone turns off.
PROSE_FILES = ('CLAUDE.md', 'AGENTS.md', 'README.md', 'README.rst',
               'PLAN.md', 'PRD.md', 'PROPOSAL.md')
PROSE_BYTES = 40_000

#: Files that carry a machine-readable owner.
REPO_FILES = ('.git/config', 'package.json', 'pyproject.toml', 'LICENSE')
REPO_BYTES = 20_000

#: A candidate shorter than this is not matched against text with its
#: punctuation stripped. Compacting turns AI into ai, which appears inside
#: ordinary words, and a false company assignment is the expensive direction.
MIN_COMPACT_LEN = 5

#: A single-token candidate shorter than this is never attested from prose,
#: memory or foldering. Measured: a folder named AI held three unrelated
#: organisations, and the two letters appear in normal sentences in every one
#: of their documents, so every child attested its own container. A company
#: name has to be distinctive enough to be an identifier. An explicitly
#: declared name bypasses this, because someone said it on purpose.
MIN_NAME_LEN = 4

#: Matches any run of non-space characters containing a path separator. In
#: PROSE a path is an address and not an identity: every one of these projects
#: quotes its own location, so the folder name appears in the folder's own
#: children and each container attested itself. In a git config or a manifest
#: the path IS the identity, so this is never applied there.
_PATHY = re.compile(r'\S*[/\\]\S*')

#: Evidence classes that count as coming from inside the project.
INSIDE = frozenset({'declared', 'repo', 'prose', 'memory'})

_WORD = re.compile(r'[^a-z0-9]+')


def _compact(text: str) -> str:
    return _WORD.sub('', (text or '').lower())


def _read(path: Path, limit: int) -> str:
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            return fh.read(limit)
    except OSError:
        return ''


def name_in_text(name: str, text: str, mask_paths: bool = False) -> bool:
    """True when the name appears in the text as a name rather than as letters.

    The readable form is matched on word boundaries so Masgarti does not match
    inside a longer word. The punctuation-stripped form is matched too, which
    is what lets a domain in a config file attest a two-word company, but only
    for candidates long enough that the compact form is still distinctive.

    mask_paths drops every path-looking token before matching. Without it a
    project whose own documents say where it lives attests the folder it lives
    in, which made two container folders read as companies and would have put
    six clients into one scope.
    """
    if not name or not text:
        return False
    if mask_paths:
        text = _PATHY.sub(' ', text)
    low = text.lower()
    readable = re.escape(name.lower().strip())
    if re.search(r'(?<![a-z0-9])' + readable + r'(?![a-z0-9])', low):
        return True
    # The punctuation-stripped form only applies to a MULTI-WORD name, where
    # it is the thing that links a company to its domain. A single word gains
    # nothing from it, because the readable form already matched on word
    # boundaries, and it loses the boundaries: Masgarti would match inside
    # MasgartiFIT, which is a product of that company, not the company.
    if ' ' not in name.strip():
        return False
    compact = _compact(name)
    if len(compact) >= MIN_COMPACT_LEN and compact in _compact(text):
        return True
    return False


def prose_attests(root: Path, name: str) -> bool:
    """True when the project's own documents name this company."""
    for fname in PROSE_FILES:
        if name_in_text(name, _read(root / fname, PROSE_BYTES), mask_paths=True):
            return True
    return False


def repo_attests(root: Path, name: str) -> bool:
    """True when a git remote, manifest or licence names this company."""
    for fname in REPO_FILES:
        if name_in_text(name, _read(root / fname, REPO_BYTES)):
            return True
    return False


def memory_attests(name: str, memories: Iterable) -> bool:
    """True when the project's own memories already carry this company.

    An org tag written earlier is the strongest of the four, because it is a
    decision this resolver or an agent already recorded. A bare mention in a
    rule line counts too, which is how a project that predates the tier gets
    its company back without anyone retyping it.
    """
    slug = slugify_org(name)
    hits = 0
    for m in memories:
        if read_org(m) == slug:
            return True
        if name_in_text(name, getattr(m, 'rule', '') or '', mask_paths=True):
            hits += 1
            if hits >= 2:
                return True
        for tag in getattr(m, 'tags', None) or []:
            if slugify_org(tag) == slug:
                return True
    return False


def folder_is_container(folder: Path) -> bool:
    """True when this folder groups unrelated work instead of being a company.

    It reads the children, because the folder itself says nothing: a folder
    holding six clients and a folder holding one company's four projects are
    both an ordinary directory with an ordinary name.

    A MAJORITY of the attesting children must attest the folder name. One child
    is not enough, and that is the whole difference between the two cases
    measured on a real tree:

        Freelance   1 of 6 children attest   six unrelated clients
        Masgarti    4 of 4 children attest   one company
        OFO         1 of 1 children attest   one company

    Any single child is a weak signal because a company name is an ordinary
    English word often enough to appear once by accident. Freelance appears in
    exactly one of its six children, in a sentence about freelance work.
    """
    try:
        children = [d for d in folder.iterdir()
                    if d.is_dir() and not d.name.startswith('.')
                    and attests_identity(d)]
    except OSError:
        return True
    if not children:
        return True
    name = folder.name
    attesting = sum(1 for c in children
                    if prose_attests(c, name) or repo_attests(c, name))
    return attesting * 2 <= len(children)


def collect_evidence(root: Path, memories: Iterable,
                     declared: Optional[str] = None,
                     home: Optional[Path] = None) -> dict:
    """{candidate name: [evidence class, ...]} for one project root.

    Candidates come from structured sources only. Prose never proposes a name,
    it only confirms one, because scanning a document for anything that looks
    like a company is how a dependency or a customer ends up owning the
    project.
    """
    memories = list(memories)
    # Keyed by SLUG, not by the name as written. An org tag stores the slug and
    # a declared name stores what someone typed, so IBM and ibm arrive as two
    # strings for one company. Keying by name made every project that already
    # carried a tag report a conflict with itself.
    by_slug: dict = {}

    def note(name, kind):
        name = (name or '').strip()
        if not name:
            return
        # A short single word is not an identifier. Someone declaring it takes
        # responsibility for it; a folder name does not get that benefit.
        if kind != 'declared' and len(name) < MIN_NAME_LEN and ' ' not in name:
            return
        slug = slugify_org(name)
        if not slug:
            return
        entry = by_slug.setdefault(slug, {'names': [], 'kinds': set()})
        entry['kinds'].add(kind)
        entry['names'].append((kind, name))

    def display(entry) -> str:
        """The most human form of a company that arrived under several spellings.

        A declared name is what someone actually wrote, so it wins. Otherwise
        prefer a form carrying capitals over a slug, because the slug is a
        storage detail and this string is what a person reads.
        """
        names = entry['names']
        for kind, name in names:
            if kind == 'declared' and any(c.isupper() for c in name):
                return name
        for _kind, name in names:
            if any(c.isupper() for c in name):
                return name
        return names[0][1]

    if declared:
        note(declared, 'declared')
    # A container's name is not a company, so it is dropped as a CANDIDATE
    # rather than merely losing its folder evidence. Freelance is attested in
    # one client's prose and in two memory rule lines, which is two inside
    # classes and would qualify it on the general rule. The container verdict
    # has to veto the name itself or six clients land in one scope.
    folder = company_candidate(root, home)
    if folder and not folder_is_container(root.parent):
        note(folder, 'folder')
    for m in memories:
        existing = read_org(m)
        if existing:
            note(existing, 'declared')

    out: dict = {}
    for entry in by_slug.values():
        name = display(entry)
        kinds = set(entry['kinds'])
        if prose_attests(root, name):
            kinds.add('prose')
        if repo_attests(root, name):
            kinds.add('repo')
        if memory_attests(name, memories):
            kinds.add('memory')
        out[name] = sorted(kinds)
    return out


def resolve(root: Path, memories: Iterable, declared: Optional[str] = None,
            home: Optional[Path] = None) -> dict:
    """The verdict for one project root, with the evidence that produced it.

    state is one of:
        assigned     org names the company, evidence says why
        conflicted   two companies attested; nothing is assigned
        container    the only candidate is a folder that groups unrelated work
        standalone   a candidate exists and the project does not attest it
        unresolved   no candidate at all

    Only the assigned state changes any scoping. Every other state leaves memgit on the
    behaviour it has today, which is what makes this safe to turn on before
    every project has been looked at.
    """
    evidence = collect_evidence(root, memories, declared, home)

    qualified = {
        name: kinds for name, kinds in evidence.items()
        if len(kinds) >= 2 and any(k in INSIDE for k in kinds)
    }

    if len(qualified) > 1:
        return {'state': 'conflicted', 'org': None, 'evidence': evidence,
                'candidates': sorted(qualified)}

    if qualified:
        name = next(iter(qualified))
        return {'state': 'assigned', 'org': name,
                'slug': slugify_org(name),
                'evidence': evidence, 'why': qualified[name]}

    # Nothing qualified. Say WHY, because a folder that groups clients and a
    # project that simply belongs to no company are different answers and get
    # different repairs.
    # collect_evidence drops a container's name before it can gather evidence,
    # so a folder candidate that exists on disk but is absent from the evidence
    # map was vetoed as a container. Reading it back costs nothing and avoids
    # walking every sibling a second time.
    folder = company_candidate(root, home)
    if folder and folder not in evidence:
        return {'state': 'container', 'org': None, 'evidence': evidence,
                'container': folder}
    if not evidence:
        return {'state': 'unresolved', 'org': None, 'evidence': {}}
    return {'state': 'standalone', 'org': None, 'evidence': evidence}
