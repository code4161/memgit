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


def from_claude_code(memory_dir: Path = None) -> list[Mnemonic]:
    """Import all Claude Code markdown memory files.

    Searches `~/.claude/projects/*/memory/*.md` by default,
    or a specific directory if provided.
    """
    if memory_dir is not None:
        dirs = [memory_dir]
    else:
        base = Path.home() / '.claude' / 'projects'
        if not base.exists():
            return []
        dirs = [d / 'memory' for d in base.iterdir() if (d / 'memory').is_dir()]

    mnemonics = []
    for d in dirs:
        for md_file in sorted(d.glob('*.md')):
            if md_file.name.upper() == 'MEMORY.MD':
                continue  # skip index files
            m = _parse_md(md_file)
            if m:
                mnemonics.append(m)
    return mnemonics


def from_markdown_file(path: Path) -> Optional[Mnemonic]:
    """Import a single Claude Code markdown memory file."""
    return _parse_md(path)


def from_toon_file(path: Path) -> list[Mnemonic]:
    """Import mnemonics from a .toon file."""
    from .toon import parse_toon
    text = path.read_text(encoding='utf-8')
    objs = parse_toon(text)
    return [o for o in objs if isinstance(o, Mnemonic)]


def _parse_md(path: Path) -> Optional[Mnemonic]:
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

    # Extract WHY and WHEN from body (bold labels)
    why_m = re.search(r'\*\*Why:\*\*\s*(.+?)(?=\n\n|\*\*|$)', body, re.DOTALL)
    when_m = re.search(r'\*\*How to apply:\*\*\s*(.+?)(?=\n\n|\*\*|$)', body, re.DOTALL)
    why = why_m.group(1).strip() if why_m else None
    when = when_m.group(1).strip() if when_m else None

    # Rule = first paragraph before any ** sections
    rule_text = re.split(r'\n\*\*|\n\n', body)[0].strip()
    rule = rule_text or desc or slug

    # Try to clean up multi-line rule
    rule = ' '.join(rule.split('\n')).strip()

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
        priority=2,
        tags=[type_code],
    )
