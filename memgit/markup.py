"""Tool-call markup that leaked into a save's field values.

A model sometimes closes a save_memory value with a tag named after the field
(`</rule>`) instead of the tool-call format's own closer. The host parser does
not accept that as the end of the value, so the next parameter's opening tag
and text become part of the value, and every parameter until the next closer
it does accept never arrives as a parameter. Measured 2026-10-07 on one
machine: 748 of 3,025 save_memory calls (24.7%), and 0 of 50,967 calls to
every other tool in the same transcripts.

The damage is silent unless something looks: the save still succeeds, the
missing fields take their defaults, and the damaged text is injected back
into later sessions, where it teaches the next save the same mistake.

This module holds the one definition of "markup" that the save path refuses,
the context renderers strip, and `memgit doctor --repair-markup` splits back
into fields.

What counts, outside backtick code spans (so a memory can quote the markup
deliberately, as the lessons about this defect do):

- a parameter opening tag `<parameter name="...">`, a parameter closing tag,
  an invoke tag, or a function_calls tag, with or without a namespace prefix;
- a closing tag named after a save_memory field (`</rule>`, `</why>`, ...)
  when nothing but whitespace or more markup follows it. A `</body>` in the
  middle of a note about HTML is prose, not damage.
"""
from __future__ import annotations

import dataclasses
import json
import re
from typing import Any

#: Text fields of a memory, in the order save_memory declares them.
TEXT_FIELDS = ('rule', 'why', 'when', 'body')
#: List fields of a memory.
LIST_FIELDS = ('tags', 'related', 'supersedes')
#: Every argument name save_memory accepts.
SAVE_PARAMS = frozenset(
    ('slug', 'project', 'type_code', 'type', 'priority', 'unverified')
    + TEXT_FIELDS + LIST_FIELDS)
#: Names a closing tag can carry and still read as a swallowed field closer.
#: memory_type and desc are not parameters, but models have sent both.
_CLOSER_NAMES = sorted(SAVE_PARAMS | {'memory_type', 'desc'})
_TYPE_CODES = ('fb', 'us', 'pj', 'rf', 'cn', 'lx', 'co', 'tr')

_NS = r'(?:[A-Za-z_][\w.-]*:)?'
# Markup that is never prose: tool-call structure itself.
_STRUCTURAL = re.compile(
    rf'<{_NS}parameter\s+name\s*=\s*"(?P<param>[^"]*)"\s*>'
    rf'|</{_NS}parameter\s*>'
    rf'|<{_NS}invoke\b[^>]*>'
    rf'|</{_NS}invoke\s*>'
    rf'|</?{_NS}function_calls\s*>')
# A closer named after a field. Only damage when it ends the value or more
# markup follows it, which the caller checks.
_FIELD_CLOSER = re.compile(rf'</(?:{"|".join(_CLOSER_NAMES)})\s*>')
# Only a CLOSED fence is a code span: an unclosed one (```mermaid in prose)
# would otherwise hide every token after it.
_CODE = re.compile(r'```.*?```|`[^`\n]*`', re.S)


def _mask_code(text: str) -> str:
    """Blank out backtick code spans, keeping every offset where it was."""
    return _CODE.sub(lambda mo: ' ' * len(mo.group(0)), text)


def _tokens(text: str) -> list[re.Match]:
    """Markup tokens in `text`, in order, ignoring anything inside code spans.

    Matches are taken against the masked copy, so their offsets index the
    original text as well.
    """
    masked = _mask_code(text)
    structural = list(_STRUCTURAL.finditer(masked))
    starts = sorted(mo.start() for mo in structural)
    out = list(structural)
    for mo in _FIELD_CLOSER.finditer(masked):
        rest = masked[mo.end():]
        if not rest.strip():
            out.append(mo)
            continue
        nxt = len(rest) - len(rest.lstrip())
        pos = mo.end() + nxt
        if pos in starts or _FIELD_CLOSER.match(masked, pos):
            out.append(mo)
    out.sort(key=lambda mo: mo.start())
    return out


def first_markup(text: str | None) -> int | None:
    """Offset of the first markup token in `text`, or None when clean."""
    if not text:
        return None
    toks = _tokens(text)
    return toks[0].start() if toks else None


def has_markup(text: str | None) -> bool:
    return first_markup(text) is not None


def clean_for_context(text: str | None) -> str:
    """`text` cut at its first markup token, for injection into context.

    Whatever follows the first token is the next parameter's value, which
    belongs to another field, so cutting there leaves the field's own text.
    Never used to rewrite the store: `memgit doctor --repair-markup` does that.
    """
    if not text:
        return text or ''
    i = first_markup(text)
    return text if i is None else text[:i].rstrip()


def swallowed_params(text: str | None) -> list[str]:
    """Parameter names whose opening tag sits inside `text`, in order."""
    if not text:
        return []
    names = [mo.group('param') for mo in _tokens(text)
             if mo.re is _STRUCTURAL and mo.group('param')]
    return list(dict.fromkeys(names))


def check_save_arguments(arguments: dict[str, Any]) -> list[str]:
    """Problems that make a save_memory call unsafe to store, one per field.

    Empty means the values are clean. Checks every string argument and every
    string inside a list argument, since a damaged call can push markup into
    any of them.
    """
    problems: list[str] = []
    for key, value in arguments.items():
        values = value if isinstance(value, list) else [value]
        for v in values:
            if not isinstance(v, str):
                continue
            toks = _tokens(v)
            if not toks:
                continue
            shown = ', '.join(dict.fromkeys(t.group(0) for t in toks[:3]))
            msg = f"'{key}' contains tool-call markup ({shown})"
            lost = [p for p in swallowed_params(v) if p != key]
            if lost:
                msg += ('; these parameters landed inside it instead of '
                        'arriving: ' + ', '.join(lost))
            problems.append(msg)
            break
    return problems


def refusal_message(problems: list[str]) -> str:
    """The error a damaged save gets back, written for the model to act on."""
    return (
        'save_memory refused: the arguments carry tool-call markup, so some '
        'parameters were swallowed into another field and would have been '
        'stored wrong. ' + ' | '.join(problems) + '. Nothing was saved. '
        'Call save_memory again with each value passed as its own parameter, '
        'closing every value with the parameter closing tag, never with a tag '
        'named after the field such as </rule>. Keep rule to one sentence and '
        'put detail in body. To quote markup on purpose, wrap it in backticks.'
    )


# ── repair ────────────────────────────────────────────────────────────────


def _split(field: str, value: str) -> dict[str, str]:
    """Split one damaged value into {parameter name: text}.

    Text before the first token belongs to `field`. A parameter opening tag
    starts a new segment under its name; an invoke or function_calls opener
    starts the next tool call, whose text is dropped.
    """
    segs: dict[str, list[str]] = {}
    cur: str | None = field
    pos = 0
    for mo in _tokens(value):
        if cur:
            segs.setdefault(cur, []).append(value[pos:mo.start()])
        pos = mo.end()
        tok = mo.group(0)
        if mo.re is _STRUCTURAL and mo.group('param'):
            cur = mo.group('param')
        elif re.match(rf'<{_NS}(?:invoke\b|function_calls)', tok):
            cur = None
    if cur:
        segs.setdefault(cur, []).append(value[pos:])
    return {k: ''.join(v).strip() for k, v in segs.items()}


def _as_list(text: str) -> list[str] | None:
    try:
        v = json.loads(text)
    except (ValueError, TypeError):
        return None
    return [str(x) for x in v] if isinstance(v, list) else None


@dataclasses.dataclass
class Repair:
    slug: str
    fixed: Any = None                    # the repaired Mnemonic, or None
    type_changed: tuple | None = None    # (old, new)
    priority_changed: tuple | None = None
    conflicts: list = dataclasses.field(default_factory=list)
    unparsed: list = dataclasses.field(default_factory=list)


def repair(m) -> Repair | None:
    """Split a damaged memory's fields back apart. None when `m` is clean.

    Swallowed text fields fill the real field when it is empty, and are
    appended to it when both hold different text (reported as a conflict).
    Swallowed tags, related and supersedes merge into the real lists. A
    swallowed type_code or priority is restored. The timestamp is kept, so
    the repair does not read as a fresh save. `fixed` is None when something
    could not be parsed, and the reason is in `unparsed`.
    """
    from .sanitize import detect_injection

    if not any(has_markup(getattr(m, f)) for f in TEXT_FIELDS):
        return None
    rep = Repair(slug=m.slug)
    new = {f: (getattr(m, f) or '') for f in TEXT_FIELDS}
    lists = {f: list(getattr(m, f) or []) for f in LIST_FIELDS}
    extra: dict[str, str] = {}
    parts = {f: _split(f, new[f]) for f in TEXT_FIELDS}
    for f in TEXT_FIELDS:
        new[f] = parts[f].get(f, '')
    for f in TEXT_FIELDS:
        for k, v in parts[f].items():
            if k == f or not v:
                continue
            k = {'type': 'type_code', 'memory_type': 'type_code'}.get(k, k)
            if k in TEXT_FIELDS:
                if not new[k].strip():
                    new[k] = v
                elif v.strip() != new[k].strip():
                    rep.conflicts.append((f, k))
                    new[k] = (new[k].rstrip() + '\n\n' + v).strip()
            elif k in LIST_FIELDS:
                lv = _as_list(v)
                if lv is None:
                    rep.unparsed.append(f'{k} is not a JSON list: {v[:60]!r}')
                else:
                    lists[k] = list(dict.fromkeys(lists[k] + lv))
            else:
                extra[k] = v
    tc, pr = m.type_code, m.priority
    if extra.get('type_code') in _TYPE_CODES and extra['type_code'] != tc:
        rep.type_changed = (tc, extra['type_code'])
        tc = extra['type_code']
    if extra.get('priority', '').strip() in ('1', '2', '3'):
        p = int(extra['priority'])
        if p != pr:
            rep.priority_changed = (pr, p)
            pr = p
    still = [f for f in TEXT_FIELDS if has_markup(new[f])]
    if still:
        rep.unparsed.append('markup remains in ' + ', '.join(still))
    if not new['rule'].strip():
        rep.unparsed.append('rule would be empty')
    if rep.unparsed:
        return rep
    unv = m.unverified
    # The detector may have flagged the merged blob; judge the clean text.
    if unv and not detect_injection(new['rule'], new['body']):
        unv = False
    rep.fixed = dataclasses.replace(
        m, type_code=tc, priority=pr, unverified=unv, sha=None,
        rule=new['rule'],
        why=new['why'] or None, when=new['when'] or None,
        body=new['body'] or None,
        tags=lists['tags'], related=lists['related'],
        supersedes=lists['supersedes'])
    return rep
