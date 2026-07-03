"""Import memories from external sources into memgit."""

from __future__ import annotations
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import Mnemonic

TYPE_MAP = {
    'feedback': 'fb',
    'user': 'us',
    'project': 'pj',
    'reference': 'rf',
    'convention': 'cn',
    'lesson': 'lx',
}

PRIORITY_MAP = {
    'low': 1, 'medium': 2, 'high': 3, 'critical': 3,
    '1': 1, '2': 2, '3': 3,
}

# Longest body we keep. Generous — the point is losslessness — but bounded
# so a pathological file can't bloat the store.
BODY_MAX_CHARS = 32_000


def project_label_from_path(path: Path) -> Optional[str]:
    """Derive a project label from a filesystem path, matching Claude Code's
    project-directory munging (path separators/dots/spaces → '-').

    /Users/hari/Freelance/BITS → 'Freelance-BITS' (home prefix stripped).
    """
    try:
        resolved = path.expanduser().resolve()
        home = Path.home().resolve()
        if resolved == home:
            return None
        rel = resolved.relative_to(home)
        parts = [re.sub(r'[/._ ]+', '-', p).strip('-') for p in rel.parts]
        label = '-'.join(p for p in parts if p)
        return label or None
    except (ValueError, OSError):
        return None


def _project_label_from_munged(munged: str) -> Optional[str]:
    """Derive a project label from a Claude Code projects/ dir name.

    '-Users-hari-Freelance-BITS' → 'Freelance-BITS' (munged home stripped).
    """
    home_munged = re.sub(r'[/._ ]+', '-', str(Path.home()))
    if munged.startswith(home_munged + '-'):
        label = munged[len(home_munged) + 1:]
    else:
        label = munged.lstrip('-')
    return label or None


def from_claude_code(memory_dir: Path = None) -> list[Mnemonic]:
    """Import all Claude Code markdown memory files.

    Searches `~/.claude/projects/*/memory/*.md` by default,
    or a specific directory if provided. Each memory is tagged with the
    project it came from (derived from the projects/ dir name).
    """
    if memory_dir is not None:
        dirs = [memory_dir]
    else:
        base = Path.home() / '.claude' / 'projects'
        if not base.exists():
            return []
        dirs = [d / 'memory' for d in sorted(base.iterdir()) if (d / 'memory').is_dir()]

    mnemonics = []
    for d in dirs:
        project = _project_label_from_munged(d.parent.name)
        for md_file in sorted(d.glob('*.md')):
            if md_file.name.upper() == 'MEMORY.MD':
                continue  # skip index files
            m = _parse_md(md_file, project=project)
            if m:
                mnemonics.append(m)
    return mnemonics


def from_markdown_file(path: Path, project: Optional[str] = None) -> Optional[Mnemonic]:
    """Import a single Claude Code markdown memory file."""
    return _parse_md(path, project=project)


def from_toon_file(path: Path) -> list[Mnemonic]:
    """Import mnemonics from a .toon file."""
    from .toon import parse_toon
    text = path.read_text(encoding='utf-8')
    objs = parse_toon(text)
    return [o for o in objs if isinstance(o, Mnemonic)]


def _parse_md(path: Path, project: Optional[str] = None) -> Optional[Mnemonic]:
    try:
        text = path.read_text(encoding='utf-8')
    except Exception:
        return None

    if not text.startswith('---'):
        return None
    end = text.find('---', 3)
    if end == -1:
        return None

    frontmatter = text[3:end].strip()
    body = text[end + 3:].strip()

    # Parse frontmatter (simple line-by-line, handles nested metadata block)
    fm: dict[str, str] = {}
    for line in frontmatter.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if ':' in stripped:
            k, v = stripped.split(':', 1)
            fm[k.strip()] = v.strip()

    slug = fm.get('name', path.stem)
    desc = fm.get('description', '')
    type_str = fm.get('type', 'feedback')
    type_code = TYPE_MAP.get(type_str, 'fb')
    priority = PRIORITY_MAP.get(fm.get('priority', '').lower(), 2)

    # Tags: explicit frontmatter tags, else derived from the project label
    tags_raw = fm.get('tags', '')
    tags = [t.strip().lower() for t in re.split(r'[,\s]+', tags_raw) if t.strip()]
    if not tags and project:
        tags = [w.lower() for w in project.split('-') if len(w) > 2][:4]

    # Extract WHY and WHEN from body (bold labels)
    why_m = re.search(r'\*\*Why:\*\*\s*(.+?)(?=\n\n|\*\*|$)', body, re.DOTALL)
    when_m = re.search(r'\*\*How to apply:\*\*\s*(.+?)(?=\n\n|\*\*|$)', body, re.DOTALL)
    why = why_m.group(1).strip() if why_m else None
    when = when_m.group(1).strip() if when_m else None

    # Rule = compact one-liner: first paragraph before any ** sections
    rule_text = re.split(r'\n\*\*|\n\n', body)[0].strip()
    rule = rule_text or desc or slug
    rule = ' '.join(rule.split('\n')).strip()

    # Body = the FULL original content, kept lossless. Only stored when it
    # carries more than the rule line already does.
    full_body = body.strip()
    if len(full_body) > BODY_MAX_CHARS:
        full_body = full_body[:BODY_MAX_CHARS] + '\n…[truncated at 32k chars]'
    if len(full_body) <= len(rule) + 20:
        full_body = None

    # Timestamp from file mtime
    try:
        mtime = path.stat().st_mtime
        timestamp = datetime.fromtimestamp(mtime, tz=timezone.utc)
    except Exception:
        timestamp = datetime.now(timezone.utc)

    if not slug:
        return None

    return Mnemonic(
        type_code=type_code,
        slug=slug,
        timestamp=timestamp,
        rule=rule[:400] if rule else desc,
        why=why[:300] if why else None,
        when=when[:300] if when else None,
        desc=desc[:200] if desc else None,
        body=full_body,
        project=project,
        priority=priority,
        tags=tags,
        source=str(path),
    )
