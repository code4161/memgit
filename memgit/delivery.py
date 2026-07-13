"""Deliver the per-project core operating guide into each AI host's native
context surface.

Design (constraint: NEVER disturb the host's own defaults):
  * For every host except Codex we write a DEDICATED, memgit-owned file inside
    the host's rules directory (e.g. `.cursor/rules/memgit.mdc`). memgit owns
    the whole file, so writing it is overwrite-in-full — trivially idempotent,
    git-clean, and safe for the user to delete. It never collides with the
    user's own rule files or config.
  * Codex has no rules directory — `AGENTS.md` is its whole surface AND it is a
    file the user co-owns. There we write a marker-delimited block and replace
    ONLY between the markers, leaving the user's content untouched.

Surfaces are the current, verified ones (see plan Phase 0 research):
  Claude Code : .claude/rules/memgit.md
  Cursor      : .cursor/rules/memgit.mdc     (alwaysApply: true)
  Windsurf    : .windsurf/rules/memgit.md    (trigger: always_on)  [12k cap]
  Cline       : .clinerules/memgit.md
  Roo Code    : .roo/rules/memgit.md
  Continue    : .continue/rules/memgit.md    (alwaysApply: true)
  Gemini CLI  : .gemini/memgit.md            (note: add to context.fileName)
  Codex       : AGENTS.md                     marker-block [32k cap, shared]
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

MARKER_START = "<!-- MEMGIT:BEGIN -->"
MARKER_END = "<!-- MEMGIT:END -->"

_DISCLAIMER = (
    "memgit-managed core operating guide — auto-generated navigation aid. "
    "If this conflicts with this repo's own CLAUDE.md / AGENTS.md / rules, "
    "THOSE win — this is not policy. Regenerate with `memgit core sync`; "
    "edit the source with `memgit core edit`. Safe to delete."
)


def _body_block(body: str) -> str:
    return f"<!-- {_DISCLAIMER} -->\n\n{body.rstrip()}\n"


def _render_plain(body: str) -> str:
    return _body_block(body)


def _render_cursor(body: str) -> str:
    return (
        "---\n"
        "description: memgit core operating guide\n"
        "alwaysApply: true\n"
        "---\n\n"
        + _body_block(body)
    )


def _render_windsurf(body: str) -> str:
    return "---\ntrigger: always_on\n---\n\n" + _body_block(body)


def _render_continue(body: str) -> str:
    return "---\nname: memgit core operating guide\nalwaysApply: true\n---\n\n" + _body_block(body)


@dataclass
class Target:
    label: str
    rel_path: str
    render: Callable[[str], str]
    #: home-dir and project-dir signatures that mean "this host is in use"
    detect: list[str] = field(default_factory=list)
    #: dedicated file we fully own (overwrite) vs a shared file (marker-block)
    dedicated: bool = True
    #: soft size ceiling in characters (host-enforced), warn if exceeded
    cap: Optional[int] = None


# Ordered; `detect` entries are checked against BOTH ~/ and the project root.
TARGETS: list[Target] = [
    Target("Claude Code", ".claude/rules/memgit.md", _render_plain, [".claude"]),
    Target("Cursor", ".cursor/rules/memgit.mdc", _render_cursor, [".cursor"]),
    Target("Windsurf", ".windsurf/rules/memgit.md", _render_windsurf,
           [".windsurf", ".codeium/windsurf"], cap=12000),
    Target("Cline", ".clinerules/memgit.md", _render_plain, [".clinerules"]),
    Target("Roo Code", ".roo/rules/memgit.md", _render_plain, [".roo", ".roorules"]),
    Target("Continue.dev", ".continue/rules/memgit.md", _render_continue, [".continue"]),
    Target("Gemini CLI", ".gemini/memgit.md", _render_plain, [".gemini", "GEMINI.md"]),
    Target("Codex", "AGENTS.md", _render_plain, [".codex", "AGENTS.md"],
           dedicated=False, cap=32000),
]

TARGETS_BY_LABEL = {t.label: t for t in TARGETS}


def is_present(target: Target, root: Path, home: Optional[Path] = None) -> bool:
    """A host counts as 'in use' if any detect signature exists in the project
    root or the user's home — so a Cursor user gets a project-local rule file
    even before they've created a project-local `.cursor/`."""
    home = home or Path.home()
    for sig in target.detect:
        if (root / sig).exists() or (home / sig).exists():
            return True
    return False


def _upsert_marker_block(existing: str, block_body: str) -> str:
    """Replace only the memgit-marked region of a shared file (e.g. AGENTS.md),
    leaving all user content intact. Append if no markers yet."""
    block = f"{MARKER_START}\n{_body_block(block_body)}{MARKER_END}\n"
    if MARKER_START in existing and MARKER_END in existing:
        pattern = re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END) + r"\n?"
        # function replacement avoids backslash/backref interpretation in body
        return re.sub(pattern, lambda _m: block, existing, count=1, flags=re.S)
    if existing.strip():
        return existing.rstrip() + "\n\n" + block
    return block


# ── seed: ingest existing host skills/rules into a draft core guide ───────────

def _frontmatter_field(text: str, key: str) -> Optional[str]:
    """Pull a top-level `key: value` from a leading `---` YAML frontmatter.

    Handles folded/literal block scalars (`key: >` / `key: |`): the value is
    the first indented line that follows — one line is enough for a routing
    entry, and a real YAML parser is not worth the dependency here.
    """
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    block = text[3:end] if end != -1 else text[3:]
    m = re.search(rf"^{re.escape(key)}:\s*(.*)$", block, flags=re.M)
    if not m:
        return None
    value = m.group(1).strip().strip('"\'')
    if value in (">", "|", ">-", "|-", ""):
        tail = block[m.end():]
        for line in tail.splitlines():
            if line.strip() and line[:1] in (" ", "\t"):
                return line.strip()
            if line.strip():  # next top-level key — no scalar body
                break
        return None
    return value


#: (label, glob) pairs — where each host keeps model-invoked skills.
_SKILL_SOURCES = [
    (".claude/skills", "*/SKILL.md"),
    (".agents/skills", "*/SKILL.md"),
    (".codex/skills", "*/SKILL.md"),
]


def collect_skills(root: Path, home: Optional[Path] = None) -> list[tuple[str, str]]:
    """Discover (name, description) for skills in the project and user home.
    Deduplicated by name; project entries win over home."""
    home = home or Path.home()
    found: dict[str, str] = {}
    for base in (home, root):
        for rel, pattern in _SKILL_SOURCES:
            skills_dir = base / rel
            if not skills_dir.is_dir():
                continue
            for skill_md in sorted(skills_dir.glob(pattern)):
                try:
                    text = skill_md.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                name = _frontmatter_field(text, "name") or skill_md.parent.name
                desc = _frontmatter_field(text, "description") or ""
                found[name] = desc  # later (project) overrides earlier (home)
    return sorted(found.items())


def build_seed(root: Path, home: Optional[Path] = None) -> str:
    """Assemble a compact routing guide from existing host skills + rules files.
    Deterministic — the intelligent refinement comes from the usage loop (3c)."""
    home = home or Path.home()
    lines: list[str] = [
        "# Core operating guide",
        "",
        "How to work in this project. Prefer these over guessing; defer to the "
        "repo's own rules where they differ.",
        "",
        "## memgit",
        "- Before answering anything that depends on past work, call resume/search "
        "(memgit) — the record of prior sessions lives there, not in this file.",
        "- memgit is the authority for entity STATUS ('tr' tracker memories: "
        "deploys, drafts, migrations, campaigns); files and READMEs are "
        "downstream and may lag. Changed an entity's state? Update its "
        "<entity>-status tracker (save, same slug).",
        "- Save durable facts/decisions/lessons as you learn them. A memory "
        "that corrects an old one should supersede it (supersedes=[old-slug]), "
        "not sit beside it.",
    ]

    skills = collect_skills(root, home)
    if skills:
        lines += ["", "## Available skills (invoke by name when the task matches)"]
        for name, desc in skills:
            lines.append(f"- **{name}** — {desc}" if desc else f"- **{name}**")

    rule_files = []
    for rel in (".cursor/rules", ".windsurf/rules", ".roo/rules",
                ".continue/rules", ".clinerules"):
        d = root / rel
        if d.is_dir():
            rule_files += [str((Path(rel) / p.name)) for p in sorted(d.glob("*"))
                           if p.name != "memgit.md" and p.name != "memgit.mdc"]
    for f in ("CLAUDE.md", "AGENTS.md", "GEMINI.md"):
        if (root / f).exists():
            rule_files.append(f)
    if rule_files:
        lines += ["", "## This project also defines (read if relevant)"]
        lines += [f"- {f}" for f in rule_files]

    return "\n".join(lines).rstrip() + "\n"


# ── auto-grow: usage-driven promotions inside the guide body ──────────────────
# The body has two regions. Everything BEFORE the AUTO markers is curated
# (owned by seed/set/edit — the AI or user wrote it). The AUTO block is owned by
# the accumulation loop and rewritten from usage. Splitting them means auto-grow
# can never clobber curated text, and — crucially — the loop only emits POINTERS
# ("[slug] rule"), never restated rules, so it stays a navigation aid subordinate
# to the repo's real rules, not a shadow rulebook that could conflict.

AUTO_START = "<!-- memgit:auto -->"
AUTO_END = "<!-- /memgit:auto -->"

#: hard budget for the always-on auto block (guardrail: bounded token cost)
_AUTO_MAX_CHARS = 900
_AUTO_MAX_ITEMS = 6


def split_curated(body: str) -> str:
    """The curated portion of the body — everything before the auto block."""
    body = body or ""
    if AUTO_START in body:
        return body[: body.index(AUTO_START)].rstrip()
    return body.rstrip()


def compute_auto_section(repo, project, now, curated: str = "") -> str:
    """Rank this project's memories by decayed usage and emit the top few as
    pointers. Guardrails applied here: project-scoped; never promote critical
    (p3) rules or conventions (cn) — those are policy, not navigation; skip
    anything already covered by the curated text (dedup); hard size/item cap."""
    from .usage import read_usage, usage_score
    from .project import project_affinity

    usage = read_usage(repo)
    if not usage:
        return ""
    candidates = []
    from .links import superseded_slugs
    all_mems = repo.list()
    hidden = superseded_slugs(all_mems)
    for m in all_mems:
        if m.type_code in ("co", "cn"):        # skip core + conventions (rules)
            continue
        if m.type_code == "tr":                # skip trackers — live state must
            continue                           # never fossilize in static files
        if m.priority == 3:                    # skip always-on criticals (rules)
            continue
        if m.slug in hidden:                   # skip superseded (stale by definition)
            continue
        if project and project_affinity(m.project, project) < 1:
            continue
        if not project and m.project:
            continue
        entry = usage.get(m.slug)
        if not entry:
            continue
        score = usage_score(entry, now)
        if score <= 0:
            continue
        if m.rule and m.rule[:40] in curated:  # dedup against curated text
            continue
        candidates.append((score, m))
    if not candidates:
        return ""
    candidates.sort(key=lambda sm: (-sm[0], sm[1].slug))

    lines = [
        "## Frequently relevant in this project",
        "(auto-maintained pointers — call memgit get/search for full detail)",
    ]
    total = 0
    for _score, m in candidates:
        rule = (m.rule or "").strip()
        line = f"- [{m.slug}] {rule[:120]}"
        if len(lines) - 2 >= _AUTO_MAX_ITEMS or total + len(line) > _AUTO_MAX_CHARS:
            break
        lines.append(line)
        total += len(line)
    if len(lines) <= 2:
        return ""
    return "\n".join(lines).rstrip() + "\n"


def refresh_core_body(existing_body, repo, project, now) -> Optional[str]:
    """Splice a freshly computed auto block into the curated body. Returns the
    new body, or None if nothing changed. The curated region is preserved
    byte-for-byte — only the auto block moves."""
    curated = split_curated(existing_body)
    auto = compute_auto_section(repo, project, now, curated)
    if auto:
        block = f"{AUTO_START}\n{auto}{AUTO_END}\n"
        new_body = (curated + "\n\n" + block) if curated else block
    else:
        new_body = (curated + "\n") if curated else ""
    new_body = new_body.rstrip() + "\n" if new_body.strip() else ""
    if new_body == ((existing_body or "").rstrip() + "\n" if (existing_body or "").strip() else ""):
        return None
    return new_body


@dataclass
class DeliveryResult:
    label: str
    path: Path
    action: str          # created | updated | unchanged | over-cap
    bytes: int


def deliver(root: Path, body: str, hosts: Optional[list[str]] = None,
            all_hosts: bool = False, dry_run: bool = False,
            home: Optional[Path] = None,
            only_existing: bool = False) -> list[DeliveryResult]:
    """Write the core guide into each selected host's memgit-owned surface.

    hosts=None + all_hosts=False → auto-detect hosts in use (default).
    hosts=[...] → exactly those labels. all_hosts=True → every target.
    only_existing=True → update just the host files that already exist (used by
    the auto-refresh path, so a background sync never creates new host files).
    """
    results: list[DeliveryResult] = []
    for t in TARGETS:
        if hosts is not None:
            if t.label not in hosts:
                continue
        elif not all_hosts and not is_present(t, root, home):
            continue

        path = root / t.rel_path
        if only_existing and not path.exists():
            continue
        if t.dedicated:
            content = t.render(body)
        else:
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            content = _upsert_marker_block(existing, body)

        action = "created" if not path.exists() else "updated"
        if path.exists() and path.read_text(encoding="utf-8") == content:
            action = "unchanged"
        if t.cap and len(content) > t.cap:
            action = "over-cap"

        if not dry_run and action not in ("unchanged", "over-cap"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        results.append(DeliveryResult(t.label, path, action, len(content)))
    return results
