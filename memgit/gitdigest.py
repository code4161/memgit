"""Deterministic repo digest for onboarding — mine git + the filesystem
so the AI operator starts from extracted facts, not exploration.

Every probe is bounded (commit caps, timeouts, output clips) so this stays
fast and safe on very large repositories, and every probe is read-only.
A probe that fails or times out is simply omitted — never an error.
"""

from __future__ import annotations
import subprocess
from collections import Counter
from pathlib import Path
from typing import Optional

# Bounds — chosen so the digest is near-instant even on monorepos.
_GIT_TIMEOUT = 5          # seconds per git call
_CHURN_COMMITS = 300      # commits sampled for hot-file analysis
_RECENT_SUBJECTS = 15     # recent commit subjects shown
_AUTHOR_SAMPLE = 500      # commits sampled for contributor list

# Well-known files worth reading during onboarding, in reading order.
_DOC_FILES = [
    'CLAUDE.md', 'README.md', 'README.rst', 'CONTRIBUTING.md',
    'ARCHITECTURE.md', 'AGENTS.md', 'CHANGELOG.md',
]
_MANIFEST_FILES = [
    'package.json', 'pyproject.toml', 'setup.py', 'requirements.txt',
    'go.mod', 'Cargo.toml', 'pom.xml', 'build.gradle', 'Gemfile',
    'composer.json', 'mix.exs', 'Makefile', 'docker-compose.yml',
    'Dockerfile',
]

_STACK_HINTS = {
    'package.json': 'Node.js/TypeScript',
    'pyproject.toml': 'Python',
    'setup.py': 'Python',
    'requirements.txt': 'Python',
    'go.mod': 'Go',
    'Cargo.toml': 'Rust',
    'pom.xml': 'Java (Maven)',
    'build.gradle': 'Java/Kotlin (Gradle)',
    'Gemfile': 'Ruby',
    'composer.json': 'PHP',
    'mix.exs': 'Elixir',
}


def _git(args: list[str], cwd: Path) -> Optional[str]:
    """Run one read-only git command; None on any failure or timeout."""
    try:
        out = subprocess.run(
            ['git', '--no-pager'] + args,
            cwd=str(cwd), capture_output=True, text=True, timeout=_GIT_TIMEOUT,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def build_digest(path: Path) -> dict:
    """Extract a bounded, factual digest of the repo at `path`.

    Returns a dict; `has_git` False means only the filesystem probes ran.
    """
    path = path.resolve()
    digest: dict = {'path': str(path), 'has_git': False}

    # Filesystem probes (work with or without git)
    docs = [f for f in _DOC_FILES if (path / f).is_file()]
    manifests = [f for f in _MANIFEST_FILES if (path / f).is_file()]
    stacks = sorted({_STACK_HINTS[m] for m in manifests if m in _STACK_HINTS})
    digest['docs'] = docs
    digest['manifests'] = manifests
    digest['stacks'] = stacks
    digest['has_docs_dir'] = (path / 'docs').is_dir()
    digest['has_ci'] = (path / '.github' / 'workflows').is_dir() or (path / '.gitlab-ci.yml').is_file()

    if _git(['rev-parse', '--is-inside-work-tree'], path) != 'true':
        return digest
    digest['has_git'] = True

    digest['branch'] = _git(['branch', '--show-current'], path) or None
    digest['last_commit_date'] = _git(['log', '-1', '--format=%as'], path)
    count = _git(['rev-list', '--count', 'HEAD'], path)
    digest['commit_count'] = int(count) if count and count.isdigit() else None
    digest['latest_tag'] = _git(['describe', '--tags', '--abbrev=0'], path)

    subjects = _git(['log', f'-{_RECENT_SUBJECTS}', '--no-merges', '--format=%s'], path)
    digest['recent_subjects'] = (
        [s.strip()[:100] for s in subjects.splitlines() if s.strip()] if subjects else []
    )

    authors = _git(['log', f'-{_AUTHOR_SAMPLE}', '--format=%an'], path)
    if authors:
        top = Counter(a.strip() for a in authors.splitlines() if a.strip())
        digest['top_authors'] = [name for name, _ in top.most_common(5)]
    else:
        digest['top_authors'] = []

    # Hot files/dirs: what actually changes is where the project lives.
    churn = _git(
        ['log', f'-{_CHURN_COMMITS}', '--no-merges', '--name-only', '--format='],
        path,
    )
    if churn:
        files = [f.strip() for f in churn.splitlines() if f.strip()]
        file_counts = Counter(files)
        dir_counts: Counter = Counter()
        for f, n in file_counts.items():
            top_level = f.split('/', 1)[0] if '/' in f else '(root)'
            dir_counts[top_level] += n
        digest['hot_files'] = [f for f, _ in file_counts.most_common(10)]
        digest['hot_dirs'] = [d for d, _ in dir_counts.most_common(6)]
    else:
        digest['hot_files'] = []
        digest['hot_dirs'] = []

    return digest


def format_digest(digest: dict) -> str:
    """Render the digest as a markdown section for the onboarding brief."""
    lines: list[str] = []
    if digest.get('has_git'):
        facts = []
        if digest.get('commit_count'):
            facts.append(f"{digest['commit_count']} commits")
        if digest.get('branch'):
            facts.append(f"branch `{digest['branch']}`")
        if digest.get('last_commit_date'):
            facts.append(f"last commit {digest['last_commit_date']}")
        if digest.get('latest_tag'):
            facts.append(f"latest tag {digest['latest_tag']}")
        if facts:
            lines.append(f"- Git: {' · '.join(facts)}")
        if digest.get('top_authors'):
            lines.append(f"- Recent authors: {', '.join(digest['top_authors'])}")
    if digest.get('stacks'):
        lines.append(f"- Stack: {', '.join(digest['stacks'])} "
                     f"(manifests: {', '.join(digest['manifests'])})")
    elif digest.get('manifests'):
        lines.append(f"- Manifests: {', '.join(digest['manifests'])}")
    read_first = list(digest.get('docs', []))
    if digest.get('has_docs_dir'):
        read_first.append('docs/')
    if read_first:
        lines.append(f"- Read these first: {', '.join(read_first)}")
    if digest.get('hot_dirs'):
        lines.append(f"- Hot areas (most-changed recently): {', '.join(digest['hot_dirs'])}")
    if digest.get('hot_files'):
        lines.append(f"- Most-changed files: {', '.join(digest['hot_files'][:6])}")
    if digest.get('recent_subjects'):
        lines.append('- Recent commit subjects (newest first):')
        for s in digest['recent_subjects']:
            lines.append(f'    · {s}')
    if digest.get('has_ci'):
        lines.append('- CI config present (.github/workflows or .gitlab-ci.yml)')
    return '\n'.join(lines)
