"""Action gate — rules that fire on what the agent DOES, not what the user says.

Prompt recall matches the user's words. A rule like "never create a feature
branch here" is broken by a tool call (`git worktree add -b ...`) that arrives
after a prompt saying only "please do all", so recall cannot see it coming.
Measured 2026-10-23 on a client store: two priority-3 rules were each broken by
a Bash or Write call, and each surfaced only after the user's correction
repeated the rule's own words.

A memory can therefore carry `triggers`: the tool calls it governs.

    triggers:
      - {"tool": "Bash", "command": "git (checkout|switch) -b |git worktree add",
         "cwd": "api|web"}
      - {"path": "api/scripts/*.sql"}

Fields (all optional, all present fields must match; triggers are OR-ed):

- tool     regex, full match, case-insensitive. Default: Bash when `command`
           is set, else the file-writing tools.
- command  regex searched in a Bash call's command.
- path     glob matched against the file a Write/Edit call touches (matches
           anywhere below a directory: `scripts/*.sql` matches
           `/repo/scripts/x.sql`).
- cwd      regex searched in where the action happens: the session's working
           directory, plus the command text or file path.
- note     free text, shown with the rule.

At least one of command/path is required: a trigger that names only a tool
would fire on every call.

The PreToolUse hook never loads the object store. It reads one small JSON file
(`cache/triggers.json`) rebuilt at commit time, the way tagmap.json is, and is
silent unless something matches. A match on a priority-3 feedback or
convention memory DENIES the call with the rule as the reason; any other match
adds the rule as context. Both are logged per session so the Stop hook can
replay the transcript and catch any governed call that went through anyway.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

_CACHE = 'triggers.json'
_ALLOW = 'gate-allow.json'

#: Types whose priority-3 memories are rules about behaviour, so a match is
#: refused rather than annotated.
DENY_TYPES = ('fb', 'cn')
#: The file-writing tools a `path` trigger watches by default.
FILE_TOOLS = 'Write|Edit|MultiEdit|NotebookEdit'
#: Matcher the hook is registered with on Claude Code.
GATE_MATCHER = 'Bash|' + FILE_TOOLS

TRIGGER_KEYS = ('tool', 'command', 'path', 'cwd', 'note')
MAX_TRIGGERS = 10
MAX_FIELD_CHARS = 300
#: Context (non-deny) matches per session, so the gate cannot become noise on
#: the hottest tools in a session.
MAX_CONTEXT_PER_SESSION = 5
#: An override lasts this long by default, and never longer than the max.
ALLOW_DEFAULT_MIN = 15
ALLOW_MAX_MIN = 120
#: Text every denial carries, so the Stop replay can recognise a refused call
#: in the transcript even if the hook's own log was lost.
DENY_MARK = 'memgit action gate'


# ── validation (save path) ───────────────────────────────────────────────────

def validate_triggers(value) -> tuple[list[dict], list[str]]:
    """Clean a caller-supplied trigger list. Returns (triggers, problems).

    Any problem means the save should be refused: a trigger that does not
    compile, or names no command or path, would either never fire or fire on
    everything, and both fail silently.
    """
    if value is None:
        return [], []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return [], ['triggers must be a list of objects, e.g. '
                        '[{"tool": "Bash", "command": "git worktree add"}]']
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return [], ['triggers must be a list of objects']
    if len(value) > MAX_TRIGGERS:
        return [], [f'at most {MAX_TRIGGERS} triggers per memory']
    out: list[dict] = []
    problems: list[str] = []
    for i, t in enumerate(value):
        where = f'triggers[{i}]'
        if not isinstance(t, dict):
            problems.append(f'{where} is not an object')
            continue
        unknown = sorted(k for k in t if k not in TRIGGER_KEYS)
        if unknown:
            problems.append(f'{where} has unknown key(s) {", ".join(unknown)}; '
                            f'allowed: {", ".join(TRIGGER_KEYS)}')
            continue
        clean = {}
        for k in TRIGGER_KEYS:
            v = t.get(k)
            if v is None or v == '':
                continue
            if not isinstance(v, str):
                problems.append(f'{where}.{k} must be a string')
                break
            if len(v) > MAX_FIELD_CHARS:
                problems.append(f'{where}.{k} is over {MAX_FIELD_CHARS} characters')
                break
            if k in ('tool', 'command', 'cwd'):
                try:
                    re.compile(v)
                except re.error as e:
                    problems.append(f'{where}.{k} is not a valid regex: {e}')
                    break
            clean[k] = v
        else:
            if not (clean.get('command') or clean.get('path')):
                problems.append(f'{where} needs a command or a path; a trigger '
                                'on a tool alone would fire on every call')
                continue
            out.append(clean)
    return out, problems


def needs_trigger(type_code: str, priority: int) -> bool:
    """A critical behaviour rule with no trigger is enforced only by recall."""
    return priority == 3 and type_code in DENY_TYPES


# ── trigger cache (written at commit, read per tool call) ────────────────────

def _cache_path(repo, name: str) -> Path:
    d = repo.path / 'cache'
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def write_trigger_cache(repo) -> None:
    """Rebuild cache/triggers.json from the active, verified memories.

    Best-effort: called from the commit path, so it never raises into a save.
    """
    try:
        from .links import filter_active
        rows = []
        for m in filter_active(repo.list()):
            if not m.triggers or m.unverified:
                continue
            rows.append({
                'slug': m.slug,
                'project': m.project or '',
                'priority': m.priority,
                'type': m.type_code,
                'rule': (m.rule or '')[:400],
                'triggers': m.triggers,
            })
        rows.sort(key=lambda r: r['slug'])
        _cache_path(repo, _CACHE).write_text(json.dumps(rows), encoding='utf-8')
    except Exception:
        pass


def read_trigger_cache(repo) -> list[dict]:
    try:
        data = json.loads(_cache_path(repo, _CACHE).read_text(encoding='utf-8'))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


# ── matching ─────────────────────────────────────────────────────────────────

def _target(tool_name: str, tool_input: dict) -> tuple[str, str]:
    """(command, path) a call acts on; either may be empty."""
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    command = tool_input.get('command') if tool_name == 'Bash' else ''
    path = (tool_input.get('file_path') or tool_input.get('notebook_path')
            or (tool_input.get('path') if tool_name != 'Bash' else '') or '')
    return str(command or ''), str(path or '')


def _glob_match(path: str, pattern: str) -> bool:
    if not path:
        return False
    path = path.replace('\\', '/')
    return (fnmatch.fnmatchcase(path, pattern)
            or fnmatch.fnmatchcase(path, '*/' + pattern.lstrip('/')))


def trigger_matches(trig: dict, tool_name: str, tool_input: dict,
                    cwd: str = '') -> bool:
    command, path = _target(tool_name, tool_input)
    tool_re = trig.get('tool') or ('Bash' if trig.get('command') else FILE_TOOLS)
    try:
        if not re.fullmatch(tool_re, tool_name or '', re.IGNORECASE):
            return False
        if trig.get('command'):
            if not command or not re.search(trig['command'], command):
                return False
        if trig.get('path'):
            if not _glob_match(path, trig['path']):
                return False
        if trig.get('cwd'):
            where = '\n'.join(x for x in (cwd or '', command, path) if x)
            if not re.search(trig['cwd'], where):
                return False
    except re.error:
        return False
    return True


def matching_rules(rows: list[dict], tool_name: str, tool_input: dict,
                   cwd: str = '', project: Optional[str] = None) -> list[dict]:
    """Cached rows whose triggers match this call, scoped like recall:
    this project's tree plus explicitly-global memories."""
    from .project import UNKNOWN_PROJECT, project_affinity
    out = []
    for r in rows:
        proj = r.get('project') or ''
        if proj == UNKNOWN_PROJECT:
            continue
        if proj and not (project and project_affinity(proj, project) >= 1):
            continue
        if any(trigger_matches(t, tool_name, tool_input, cwd)
               for t in r.get('triggers') or [] if isinstance(t, dict)):
            out.append(r)
    # Denials first, then by priority, so the reason leads with the hard rule.
    out.sort(key=lambda r: (not is_deny(r), -int(r.get('priority', 2)), r['slug']))
    return out


def is_deny(row: dict) -> bool:
    return int(row.get('priority', 2)) == 3 and row.get('type') in DENY_TYPES


def call_signature(tool_name: str, tool_input) -> str:
    raw = json.dumps([tool_name, tool_input], sort_keys=True, default=str)
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]


# ── overrides ────────────────────────────────────────────────────────────────

def allow(repo, slug: str, minutes: int = ALLOW_DEFAULT_MIN,
          now: Optional[datetime] = None) -> datetime:
    """Let calls governed by `slug` through for a short window. Returns expiry."""
    now = now or datetime.now(timezone.utc)
    minutes = max(1, min(int(minutes), ALLOW_MAX_MIN))
    until = now + timedelta(minutes=minutes)
    data = _read_allow(repo)
    data = {s: t for s, t in data.items() if _parse_ts(t) and _parse_ts(t) > now}
    data[slug] = until.isoformat()
    _cache_path(repo, _ALLOW).write_text(json.dumps(data), encoding='utf-8')
    return until


def _read_allow(repo) -> dict:
    try:
        data = json.loads(_cache_path(repo, _ALLOW).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _parse_ts(value) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def allowed(repo, slug: str, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    ts = _parse_ts(_read_allow(repo).get(slug))
    return bool(ts and ts > now)


# ── per-session log (read back by the Stop replay) ───────────────────────────

def _log_path(repo, session_id: str) -> Path:
    from .hooks import _session_cache_dir
    return _session_cache_dir(repo, 'action-gate') / str(session_id)


def log_decision(repo, session_id: Optional[str], sig: str, slugs: list[str],
                 decision: str) -> None:
    if not session_id:
        return
    try:
        with _log_path(repo, session_id).open('a', encoding='utf-8') as f:
            f.write(json.dumps({'sig': sig, 'slugs': slugs,
                                'decision': decision}) + '\n')
    except OSError:
        pass


def read_log(repo, session_id: Optional[str]) -> list[dict]:
    if not session_id:
        return []
    try:
        lines = _log_path(repo, session_id).read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# ── rendering ────────────────────────────────────────────────────────────────

def _rule_line(row: dict) -> str:
    from .markup import clean_for_context
    rule = clean_for_context(row.get('rule') or '').strip().replace('\n', ' ')
    if len(rule) > 300:
        rule = rule[:299] + '…'
    return f'[{row["slug"]}] {rule}'


def deny_reason(rows: list[dict]) -> str:
    deny = [r for r in rows if is_deny(r)]
    lines = [f'{DENY_MARK}: this call is governed by a critical saved rule, '
             'so it was not run.']
    lines += ['- ' + _rule_line(r) for r in deny]
    lines.append(
        'Do what the rule says instead (get_memory("<slug>") has the full '
        'detail). Only if the user has explicitly asked for this exact action '
        'in this session, record that with `memgit allow <slug>` (opens a '
        f'{ALLOW_DEFAULT_MIN}-minute window) and run the call again.')
    return '\n'.join(lines)


def context_text(rows: list[dict]) -> str:
    lines = ['memgit: saved rule(s) govern this action —']
    lines += ['- ' + _rule_line(r) for r in rows]
    return '\n'.join(lines)


# ── transcript replay (Stop backstop) ────────────────────────────────────────

def transcript_calls(text: str) -> list[dict]:
    """Tool calls in a Claude Code JSONL transcript, with each call's result.

    Returns [{id, name, input, cwd, refused}] in order. `refused` is True when
    the call's result carries the gate's denial mark, so a call the gate
    stopped is never counted as a violation even if the hook log is missing.
    """
    calls: list[dict] = []
    by_id: dict[str, dict] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or '"tool_' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        msg = entry.get('message')
        content = msg.get('content') if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get('type') == 'tool_use':
                call = {'id': item.get('id'), 'name': item.get('name') or '',
                        'input': item.get('input') or {},
                        'cwd': entry.get('cwd') or '', 'refused': False}
                calls.append(call)
                if call['id']:
                    by_id[call['id']] = call
            elif item.get('type') == 'tool_result':
                call = by_id.get(item.get('tool_use_id'))
                if call is not None and DENY_MARK in json.dumps(item.get('content'),
                                                                default=str):
                    call['refused'] = True
    return calls


def find_violations(repo, transcript_text: str, session_id: Optional[str],
                    project: Optional[str] = None) -> list[tuple[dict, dict]]:
    """[(call, row)] for governed calls that ran without a recorded decision.

    A call is excused when the gate refused it, or when the gate logged it as
    allowed by an explicit override. Anything else that matches a deny rule
    went through: the trigger was added after the call, the hook was not
    installed, or it failed.
    """
    rows = [r for r in read_trigger_cache(repo) if is_deny(r)]
    if not rows:
        return []
    logged = {e.get('sig') for e in read_log(repo, session_id)
              if e.get('decision') in ('deny', 'override')}
    out = []
    for call in transcript_calls(transcript_text):
        if call['refused']:
            continue
        name = call['name']
        if name != 'Bash' and not re.fullmatch(FILE_TOOLS, name):
            continue
        if call_signature(name, call['input']) in logged:
            continue
        hits = matching_rules(rows, name, call['input'], call['cwd'], project)
        if hits:
            out.append((call, hits[0]))
    return out


def describe_call(call: dict) -> str:
    command, path = _target(call['name'], call['input'])
    what = command or path or ''
    what = what.replace('\n', ' ')
    if len(what) > 160:
        what = what[:159] + '…'
    return f'{call["name"]}: {what}'
