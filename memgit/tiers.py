"""Company and component: the two tiers around the project label.

A project label is a munged path, so it answers only one question, and answers
it badly when a workspace is opened at any depth other than the one the last
save used. Two tiers close that:

    company     scope boundary above project, inherits DOWNWARD only
    project     the existing scope boundary
    component   a repo or area inside a project, for ranking and labelling

A client folder is not one project. Measured 2026-09-20: one client folder held
six separate git repos, another workspace held thirteen sub-projects, and eight
of the twenty-two workspaces ever opened on that machine were components inside
a parent project. Every one of those saves landed on whatever depth the session
started from, so 234 memories sat on the parent label and none recorded which
of its six repos they were about.

COMPONENT IS NOT A SCOPE BOUNDARY, and that is deliberate. Making it one would
split those 234 memories into six stores that cannot see each other, which is
the failure this module exists to prevent. A session in one repo sees the whole
project and ranks its own repo first.

WHERE THE TIERS ARE STORED: reserved tags, not new TOON fields. The parser
carries unknown fields now, but every already-released memgit strips them, and
a machine running two versions against one store is the normal case rather than
the exception. A tag survives every shipped version, the cloud merge path, the
VS Code extension and both published tool schemas, none of which need to change.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

from .project import munge

#: Reserved tag prefixes. A tag carrying one of these is structure, not a
#: subject, so it is hidden from tag rendering and kept out of the BM25 corpus
#: and the tag index. Neither prefix can collide with a real tag: a subject tag
#: holding a colon has never been written by any surface.
ORG_TAG = 'org:'
PART_TAG = 'part:'
RESERVED_PREFIXES = (ORG_TAG, PART_TAG)

#: A directory attests an identity when it carries one of these. Measured
#: against a real tree: every project root and every component had at least
#: one, and all four client container folders had none. That is the whole
#: discriminator between a folder that groups work and a folder that IS work.
IDENTITY_MARKERS = (
    'CLAUDE.md', 'AGENTS.md', 'README.md', 'README.rst', '.git',
    'package.json', 'pyproject.toml', 'pubspec.yaml', 'go.mod', 'Cargo.toml',
)

_SLUG_RE = re.compile(r'[^a-z0-9]+')


def slugify_org(name: str) -> str:
    """Canonical form of a company name, for the reserved tag.

    OFO Collective and ofo-collective are the same company written twice, and
    a tag that distinguishes them would split the company the way a path
    difference splits a project.
    """
    return _SLUG_RE.sub('-', (name or '').strip().lower()).strip('-')


def is_reserved(tag: str) -> bool:
    """True for a structural tag that must not reach a user or the scorer."""
    return bool(tag) and tag.startswith(RESERVED_PREFIXES)


def visible_tags(tags: Optional[Iterable[str]]) -> list:
    """The subject tags, with structure removed."""
    return [t for t in (tags or []) if not is_reserved(t)]


def _read_tag(tags: Optional[Iterable[str]], prefix: str) -> Optional[str]:
    for t in tags or []:
        if t.startswith(prefix):
            value = t[len(prefix):].strip()
            if value:
                return value
    return None


def read_org(m) -> Optional[str]:
    """The company slug carried by a memory, or None."""
    return _read_tag(getattr(m, 'tags', None), ORG_TAG)


def read_part(m) -> Optional[str]:
    """The component this memory is about, or None for the project as a whole."""
    return _read_tag(getattr(m, 'tags', None), PART_TAG)


def with_tier_tags(tags: Optional[Iterable[str]],
                   org: Optional[str] = None,
                   part: Optional[str] = None) -> list:
    """Tags with the tier tags replaced, never appended twice.

    Writing a second org tag beside an existing one would leave a memory
    claiming two companies, which is the shape this whole module exists to
    keep out of the store.
    """
    out = [t for t in (tags or []) if not is_reserved(t)]
    if org:
        out.append(ORG_TAG + slugify_org(org))
    if part:
        out.append(PART_TAG + part)
    # Anything reserved that is neither org nor part is kept, so a tag written
    # by a newer memgit is not dropped by an older one through this path.
    for t in (tags or []):
        if is_reserved(t) and not t.startswith((ORG_TAG, PART_TAG)):
            out.append(t)
    return out


def attests_identity(path: Path) -> bool:
    """True when this directory is work rather than a folder that groups work."""
    try:
        return any((path / marker).exists() for marker in IDENTITY_MARKERS)
    except OSError:
        return False


def project_root(path: Path, home: Optional[Path] = None):
    """Resolve a working directory to (project root, component path).

    Walks up to home and returns the HIGHEST ancestor that attests an identity
    whose own parent does not. Everything below that root is the component.

    That rule is what makes a directly opened sub-repo resolve to its project
    instead of becoming a project of its own:

        ~/Freelance/FittyMe/fittyme_app
            fittyme_app  own git repo and manifest, but its parent attests
            FittyMe      CLAUDE.md naming the client and its repos
            Freelance    attests nothing, so it groups clients
            -> root FittyMe, component fittyme_app

    It also anchors identity to the attesting directory rather than to the path
    the session happened to start from, which is the failure that stranded
    1,819 memories on a directory that had moved.

    Returns (None, None) when nothing below home attests, which is the honest
    answer for a scratch directory and leaves the caller on today's behaviour.
    """
    home = (home or Path.home())
    try:
        path = path.expanduser().resolve()
        home = home.expanduser().resolve()
    except OSError:
        return None, None
    try:
        rel = path.relative_to(home)
    except ValueError:
        return None, None

    # Ancestors from just below home down to the path itself.
    chain = [home / Path(*rel.parts[:i]) for i in range(1, len(rel.parts) + 1)]
    attesting = [d for d in chain if attests_identity(d)]
    if not attesting:
        return None, None

    # The highest attesting directory whose parent does not attest. Walking
    # from the top means a container folder that somehow attests (a stray
    # README over a set of clients) cannot swallow the projects beneath it,
    # because the first attesting directory is still the shallowest one.
    root = attesting[0]
    for d in attesting:
        if not attests_identity(d.parent) or d.parent == home:
            root = d
            break

    component = path.relative_to(root).as_posix() if path != root else None
    return root, component


def company_candidate(root: Path, home: Optional[Path] = None) -> Optional[str]:
    """The folder name that COULD be this project's company. A candidate only.

    A parent directory that groups work is where a company name usually sits,
    but the name is never taken on that evidence alone. Measured on a real
    tree, one such folder held six unrelated clients and another held three
    unrelated organisations; taking the folder name would have filed one
    client's record inside another's. Attestation from inside the project
    decides, and this only nominates.
    """
    home = (home or Path.home())
    try:
        root = root.expanduser().resolve()
        home = home.expanduser().resolve()
        parent = root.parent
    except OSError:
        return None
    if parent == home or parent == root:
        return None
    try:
        parent.relative_to(home)
    except ValueError:
        return None
    return parent.name or None


def component_label(root: Path, component: Optional[str]) -> Optional[str]:
    """The component in the same munged form the project label uses."""
    if not component:
        return None
    return munge(component).strip('-') or None
