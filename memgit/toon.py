"""TOON format parser and serializer.

TOON — Thought Object Observation Notation
Line-oriented, sigil-prefixed format purpose-built for AI memory objects.
Slightly more token-efficient than equivalent markdown (~5-10% with a real
tokenizer); the big context savings in memgit comes from BM25 top-k
retrieval, not the format itself.
"""

from __future__ import annotations
import re
from datetime import datetime, timezone
from typing import Union

from .models import Mnemonic, MindState, MindStateEntry, Checkpoint, DiffSummary

USER_TYPE_CODES = {"fb", "us", "pj", "rf", "cn", "lx"}


def _esc(value: str) -> str:
    """Escape a field value for TOON's one-line-per-field layout.

    CR must be escaped like LF: parse-side normalization treats a raw CR
    as a line break, which would truncate the field mid-value and re-parse
    the tail as new fields — silent corruption plus field injection.
    A leading space/tab gets a protective backslash so it survives the
    lenient `KEY: value` (space-after-colon) parse of hand-written files.
    """
    out = (value.replace('\\', '\\\\')
                .replace('\n', '\\n')
                .replace('\r', '\\r'))
    if out[:1] in (' ', '\t'):
        out = '\\' + out
    return out


def _unesc(value: str) -> str:
    """Reverse _esc. Left-to-right so escaped backslashes round-trip."""
    if '\\' not in value:
        return value
    out: list[str] = []
    i = 0
    while i < len(value):
        c = value[i]
        if c == '\\' and i + 1 < len(value):
            nxt = value[i + 1]
            if nxt == 'n':
                out.append('\n')
                i += 2
                continue
            if nxt == 'r':
                out.append('\r')
                i += 2
                continue
            if nxt in (' ', '\t'):
                out.append(nxt)
                i += 2
                continue
            if nxt == '\\':
                out.append('\\')
                i += 2
                continue
        out.append(c)
        i += 1
    return ''.join(out)


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO 8601 compact UTC timestamp."""
    s = ts_str.rstrip('Z')
    try:
        if 'T' in s:
            # Normalize: 2026-06-14T08:22 → 2026-06-14T08:22:00
            if len(s) == 16:
                s += ':00'
            return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    return datetime.now(timezone.utc)


def format_ts(dt: datetime) -> str:
    """Format datetime to TOON compact UTC: 2026-06-14T08:22Z"""
    return dt.strftime('%Y-%m-%dT%H:%MZ')


def parse_toon(text: str) -> list[Union[Mnemonic, MindState, Checkpoint]]:
    """Parse a TOON file into a list of objects."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    blocks = re.split(r'\n{2,}', text.strip())
    results = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        obj = _parse_block(block)
        if obj is not None:
            results.append(obj)
    return results


def _parse_block(block: str) -> Union[Mnemonic, MindState, Checkpoint, None]:
    lines = block.split('\n')
    if not lines:
        return None

    header = lines[0]
    if not header.startswith('TOON1|'):
        return None

    parts = header.split('|')
    if len(parts) < 4:
        return None

    type_code = parts[1]
    slug = parts[2]
    timestamp = _parse_ts(parts[3])
    flags_str = parts[4] if len(parts) > 4 else ''
    priority = 2
    if flags_str.startswith('!'):
        try:
            priority = int(flags_str[1:])
        except ValueError:
            pass

    field_lines = lines[1:]

    if type_code == 'ms':
        return _parse_ms(field_lines, timestamp, slug)
    elif type_code == 'ck':
        return _parse_ck(field_lines, timestamp, slug)
    elif type_code in USER_TYPE_CODES:
        return _parse_mnemonic(field_lines, type_code, slug, timestamp, priority)
    return None


def _parse_ms(lines: list[str], timestamp: datetime, slug: str) -> MindState:
    entries = []
    for line in lines:
        line = line.strip()
        if line.startswith('ENTRY:'):
            rest = line[6:]
            if ':' in rest:
                idx = rest.index(':')
                s = rest[:idx].strip()
                h = rest[idx+1:].strip()
                entries.append(MindStateEntry(slug=s, mnem_sha=h))
    ms = MindState(timestamp=timestamp, entries=entries)
    ms.sha = slug  # slug field stores sha[:16] for internal objects
    return ms


def _parse_ck(lines: list[str], timestamp: datetime, slug: str) -> Checkpoint:
    kv: dict[str, str] = {}
    added, updated, removed = [], [], []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith('+'):
            rest = line[1:]
            if ':' in rest:
                k, v = rest.split(':', 1)
                k = k.strip().upper()
                v = v.strip()
                if k == 'ADD':
                    added.append(v)
                elif k == 'UPD':
                    updated.append(v)
                elif k == 'REM':
                    removed.append(v)
        elif ':' in line:
            k, v = line.split(':', 1)
            kv[k.strip().upper()] = v.strip()

    ck = Checkpoint(
        mindstate_sha=kv.get('MSTATE', ''),
        timestamp=timestamp,
        trigger=kv.get('TRIGGER', 'explicit'),
        message=kv.get('MSG', ''),
        author=kv.get('AUTHOR', ''),
        session_id=kv.get('SESSION', ''),
        parent_sha=kv.get('PARENT') or None,
        diff_summary=DiffSummary(added=added, modified=updated, removed=removed),
    )
    ck.sha = slug
    return ck


def _parse_mnemonic(
    lines: list[str],
    type_code: str,
    slug: str,
    timestamp: datetime,
    priority: int,
) -> Mnemonic:
    tags: list[str] = []
    rule = None
    why = who = when = desc = where = dl = inc = cost = source = None
    body = project = None
    supersedes: list[str] = []
    related: list[str] = []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        if line.startswith('#'):
            for tag in line.split():
                t = tag.lstrip('#').strip()
                if t:
                    tags.append(t)
        elif line.startswith('~'):
            rest = line[1:]
            if ':' in rest:
                k, v = rest.split(':', 1)
                k = k.strip().upper()
                v = v.strip()
                if k == 'SUP':
                    supersedes = [s.strip() for s in v.split(',') if s.strip()]
                elif k == 'REL':
                    related = [s.strip() for s in v.split(',') if s.strip()]
                elif k == 'SRC':
                    source = v
        elif ':' in line:
            # Split the RAW line: the serializer writes `KEY:value` with the
            # value's bytes intact, so stripping here would eat leading
            # indentation / trailing spaces that ARE the data. One leading
            # space is dropped for lenient hand-written `KEY: value` files
            # (_esc backslash-protects a data-bearing leading space).
            k, v = raw.split(':', 1)
            k = k.strip().upper()
            if v.startswith(' '):
                v = v[1:]
            v = _unesc(v)
            if k == 'RULE':
                rule = v
            elif k == 'WHY':
                why = v
            elif k == 'WHEN':
                when = v
            elif k == 'DESC':
                desc = v
            elif k == 'BODY':
                body = v
            elif k == 'PROJ':
                project = v
            elif k == 'WHO':
                who = v
            elif k == 'WHERE':
                where = v
            elif k == 'DL':
                dl = v
            elif k == 'INC':
                inc = v
            elif k == 'COST':
                cost = v

    return Mnemonic(
        type_code=type_code,
        slug=slug,
        timestamp=timestamp,
        rule=rule or desc or '',
        priority=priority,
        tags=tags,
        why=why,
        when=when,
        desc=desc,
        body=body,
        project=project,
        who=who,
        where=where,
        dl=dl,
        inc=inc,
        cost=cost,
        supersedes=supersedes,
        related=related,
        source=source,
    )


def serialize_mnemonic(m: Mnemonic, canonical: bool = False) -> str:
    """Serialize Mnemonic to TOON.

    canonical=True: sorted fields (used for SHA computation).
    canonical=False: human-friendly output order.
    """
    flags = f'|!{m.priority}' if m.priority != 2 else ''
    header = f'TOON1|{m.type_code}|{m.slug}|{format_ts(m.timestamp)}{flags}'
    lines = [header]

    if canonical:
        # Deterministic field order for SHA: alphabetical by sigil
        fields: list[tuple[str, str]] = []
        if m.body:
            fields.append(('BODY', m.body))
        if m.cost:
            fields.append(('COST', m.cost))
        if m.desc:
            fields.append(('DESC', m.desc))
        if m.dl:
            fields.append(('DL', m.dl))
        if m.inc:
            fields.append(('INC', m.inc))
        if m.project:
            fields.append(('PROJ', m.project))
        fields.append(('RULE', m.rule))
        if m.tags:
            fields.append(('TAGS', ' '.join(sorted(m.tags))))
        if m.when:
            fields.append(('WHEN', m.when))
        if m.where:
            fields.append(('WHERE', m.where))
        if m.who:
            fields.append(('WHO', m.who))
        if m.why:
            fields.append(('WHY', m.why))
        if m.related:
            fields.append(('~REL', ','.join(sorted(m.related))))
        if m.source:
            fields.append(('~SRC', m.source))
        if m.supersedes:
            fields.append(('~SUP', ','.join(sorted(m.supersedes))))

        for k, v in fields:
            if k == 'TAGS':
                lines.append(f'#{v}')
            elif k.startswith('~'):
                lines.append(f'{k}:{_esc(v)}')
            else:
                lines.append(f'{k}:{_esc(v)}')
    else:
        if m.tags:
            lines.append('#' + ' #'.join(m.tags))
        if m.project:
            lines.append(f'PROJ:{_esc(m.project)}')
        lines.append(f'RULE:{_esc(m.rule)}')
        if m.why:
            lines.append(f'WHY:{_esc(m.why)}')
        if m.when:
            lines.append(f'WHEN:{_esc(m.when)}')
        if m.desc:
            lines.append(f'DESC:{_esc(m.desc)}')
        if m.body:
            lines.append(f'BODY:{_esc(m.body)}')
        if m.who:
            lines.append(f'WHO:{_esc(m.who)}')
        if m.where:
            lines.append(f'WHERE:{_esc(m.where)}')
        if m.dl:
            lines.append(f'DL:{_esc(m.dl)}')
        if m.inc:
            lines.append(f'INC:{_esc(m.inc)}')
        if m.cost:
            lines.append(f'COST:{_esc(m.cost)}')
        if m.supersedes:
            lines.append(f'~SUP:{",".join(m.supersedes)}')
        if m.related:
            lines.append(f'~REL:{",".join(m.related)}')
        if m.source:
            lines.append(f'~SRC:{_esc(m.source)}')

    return '\n'.join(lines)


def serialize_mindstate(ms: MindState) -> str:
    """Serialize MindState to TOON."""
    slug_field = ms.sha[:16] if ms.sha else '0' * 16
    lines = [
        f'TOON1|ms|{slug_field}|{format_ts(ms.timestamp)}',
        f'COUNT:{ms.count}',
    ]
    for e in sorted(ms.entries, key=lambda e: e.slug):
        lines.append(f'ENTRY:{e.slug}:{e.mnem_sha}')
    return '\n'.join(lines)


def serialize_checkpoint(ck: Checkpoint) -> str:
    """Serialize Checkpoint to TOON."""
    slug_field = ck.sha[:16] if ck.sha else '0' * 16
    lines = [f'TOON1|ck|{slug_field}|{format_ts(ck.timestamp)}']
    if ck.parent_sha:
        lines.append(f'PARENT:{ck.parent_sha}')
    lines.append(f'MSTATE:{ck.mindstate_sha}')
    lines.append(f'TRIGGER:{ck.trigger}')
    lines.append(f'MSG:{ck.message}')
    if ck.author:
        lines.append(f'AUTHOR:{ck.author}')
    if ck.session_id:
        lines.append(f'SESSION:{ck.session_id}')
    if ck.diff_summary:
        d = ck.diff_summary
        for s in d.added:
            lines.append(f'+ADD:{s}')
        for s in d.modified:
            lines.append(f'+UPD:{s}')
        for s in d.removed:
            lines.append(f'+REM:{s}')
    return '\n'.join(lines)


def mnemonic_to_markdown(m: Mnemonic) -> str:
    """Convert a Mnemonic back to Claude Code markdown format."""
    type_map = {
        'fb': 'feedback', 'us': 'user', 'pj': 'project',
        'rf': 'reference', 'cn': 'convention', 'lx': 'lesson',
    }
    type_str = type_map.get(m.type_code, 'feedback')
    desc = m.desc or m.rule[:120]

    lines = [
        '---',
        f'name: {m.slug}',
        f'description: {desc}',
        'metadata:',
        f'  type: {type_str}',
        '---',
        '',
        m.body if m.body else m.rule,
        '',
    ]
    if not m.body:
        if m.why:
            lines += [f'**Why:** {m.why}', '']
        if m.when:
            lines += [f'**How to apply:** {m.when}', '']
    return '\n'.join(lines)
