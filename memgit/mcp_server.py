"""memgit MCP server — exposes memory search/get/list/save over stdio MCP protocol."""

from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import mcp.server.stdio
from mcp.server import Server
from mcp.types import (
    TextContent,
    Tool,
)

from .models import Mnemonic
from .repo import Repository
from .scorer import score as bm25_score
from .toon import serialize_mnemonic


_SERVER_DESCRIPTION = (
    "memgit is a version-controlled memory store — git for AI memory. "
    "It stores typed, prioritized facts, rules, preferences, and lessons learned, "
    "then serves only the most relevant ones per query via BM25 scoring. "
    "HOW TO USE IT WELL — apply judgment, not keywords: "
    "(1) Before answering, ask yourself: does this request depend on state I don't have in "
    "context? A request that presupposes shared history ('continue', 'the pending tasks', "
    "'that bug from yesterday') cannot be answered from the current conversation or open "
    "files alone — resume_session is the record of what actually happened last; "
    "search_memories answers topic-specific questions about past work and preferences. "
    "When in doubt, checking memory is cheap; guessing wrong is not. "
    "(2) Call save_memory whenever you learn something durable — a rule the user corrected you on, "
    "a preference they stated, a project decision, a lesson from a mistake. "
    "Do NOT wait for the user to ask you to remember — save proactively. "
    "Put the one-line fact in 'rule' and the full details in 'body' — body is where "
    "state, decisions, and context live losslessly. "
    "(3) Memories are project-scoped: searches and recall are FILTERED to the current project's "
    "family plus global memories by default (pass all_projects=true to search the whole store, "
    "or project=<label> to hard-filter one). Saves default to the current project; pass "
    "project=\"\" for a deliberately-global memory — a save whose project can't be detected is "
    "quarantined under '_unknown' until relabeled (`memgit doctor --relabel`). "
    "If the current project has NO memories yet (adopted mid-project), bootstrap it: "
    "extract 10-20 durable facts from README/CLAUDE.md/docs/git history and save_memory "
    "each — `memgit onboard` prints the full brief. "
    "(4) memgit is cross-tool: memories saved here are also available in Cursor, Windsurf, GPT, and Gemini. "
    "(5) CORE OPERATING GUIDE — each project has one (`memgit core`): a per-project navigation aid "
    "(which skills/tools/commands to reach for) that is injected at session start AND written into every "
    "host's own rules file, so any tool knows how to work here even when its CLAUDE.md/skills aren't set up. "
    "If resume shows no core guide for this project, seed it ONCE: `memgit core seed` (drafts it from the "
    "project's existing skills + rules), then `memgit core sync` to deliver it to every AI tool. It grows "
    "automatically from usage; if it ever looks stale, wrong, or bloated, run `memgit core heal`. It is a "
    "fallback aid, always SUBORDINATE to the repo's own CLAUDE.md / AGENTS.md / rules. "
    "(6) memgit is the AUTHORITY for entity STATUS: 'tr' tracker memories are the live state of deploys, "
    "drafts, migrations, campaigns — files and READMEs are downstream and may lag. When you change an "
    "entity's state, update its tracker (save_memory, same '<entity>-status' slug, type tr). When you "
    "correct or replace a memory, pass supersedes=[old-slug] — never prefix rules with 'CORRECTED:' or "
    "leave stale duplicates; superseded memories stop surfacing automatically. "
    "The resume digest and recall blocks ADVERTISE depth ('+N more on <topic>') — those counts are real; "
    "search_memories(<topic>) is guaranteed to return them."
)

_TYPE_DESCRIPTIONS = (
    "fb=feedback (corrections, preferences, how the user likes to work), "
    "us=user (who the user is, their role, expertise, goals), "
    "pj=project (active projects, goals, decisions, deadlines), "
    "rf=reference (pointers to external systems, URLs, tools), "
    "cn=convention (code style, naming, architecture rules), "
    "lx=lesson (lessons learned, post-mortems, 'we got burned by X'), "
    "co=core (the per-project operating guide — which tools/skills/commands to reach for; "
    "always injected at session start, subordinate to the repo's own rules), "
    "tr=tracker (LIVE STATUS of exactly one entity — a deploy, draft, migration, campaign. "
    "One tracker per entity, slug '<entity>-status', tags naming the entity; UPDATE it by "
    "re-saving the same slug whenever the state changes. Trackers render as the status board "
    "at session start; memgit is the authority for this status, files are downstream)"
)

_TYPE_ENUM = ["fb", "us", "pj", "rf", "cn", "lx", "co", "tr"]


def _default_store() -> Path:
    from .repo import default_store_candidates
    for candidate in default_store_candidates():
        if (candidate / ".memgit").is_dir():
            return candidate
    return Path.home() / ".claude" / "memgit-store"


#: Project label detected once at server startup (MCP hosts launch stdio
#: servers with cwd set to the workspace). Kept as the per-call FALLBACK:
#: envs are re-read on every call so MEMGIT_PROJECT / CLAUDE_PROJECT_DIR
#: changes win, but a host that only communicated the workspace via the
#: launch cwd still resolves correctly for the server's whole life.
_startup_project: str | None = None


def _detect_project() -> str | None:
    """Label for the project this MCP server is serving, re-derived per call.

    Shares the single detection path (`project.detect_project`): explicit
    envs first, then the current cwd; falls back to the label captured at
    server startup.
    """
    from .project import detect_project
    try:
        label = detect_project()
    except Exception:
        label = None
    return label or _startup_project


def _load_repo(store_path: Path | None) -> Repository | None:
    path = store_path or _default_store()
    memgit_dir = path / ".memgit"
    if not memgit_dir.is_dir():
        return None
    return Repository(memgit_dir)


def _mnem_to_dict(m: Mnemonic, score: float | None = None,
                  include_body: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {
        "slug": m.slug,
        "type": m.type_code,
        "priority": m.priority,
        "rule": m.rule,
    }
    if m.why:
        d["why"] = m.why
    if m.when:
        d["when"] = m.when
    if m.tags:
        d["tags"] = m.tags
    if m.desc:
        d["desc"] = m.desc
    if m.project:
        d["project"] = m.project
    if include_body and m.body:
        d["body"] = m.body
    elif m.body:
        d["has_body"] = True  # full detail available via get_memory
    if score is not None:
        d["score"] = round(score, 4)
    return d


def run_server(store_path: Path | None = None) -> None:
    """Run the MCP server on stdio."""
    global _startup_project
    _startup_project = _detect_project()

    server = Server(
        "memgit",
        instructions=_SERVER_DESCRIPTION,
    )

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="resume_session",
                description=(
                    "Get a compact 'where we left off' digest: the status board (live entity "
                    "state from tracker memories), the last checkpoints (most recent actions "
                    "taken), staged work in flight, recently updated memories, critical rules "
                    "that always apply, and a memory index of topics with counts. "
                    "This is the authoritative record of what happened in previous sessions. "
                    "Use your judgment about when the current request depends on that record: "
                    "any ask that presupposes shared history — continuing work, referencing "
                    "'pending' or 'recent' things, resuming after a break — can't be answered "
                    "correctly from the conversation or open files alone, however plausible they "
                    "look. An open file shows what the user is looking at; this shows what was "
                    "actually done last. Cheap to call, so prefer checking over assuming; skip it "
                    "only when the request is clearly self-contained."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "checkpoints": {
                            "type": "integer",
                            "description": "How many recent checkpoints to include (default 5)",
                            "default": 5,
                        },
                        "recent": {
                            "type": "integer",
                            "description": "How many recently updated memories to include (default 10)",
                            "default": 10,
                        },
                    },
                },
            ),
            Tool(
                name="search_memories",
                description=(
                    "Search your persistent memory store for facts, rules, and lessons relevant to the current task. "
                    "CALL THIS: at the start of every session, before answering questions about past work, "
                    "before applying preferences the user may have expressed before, or whenever you are unsure "
                    "whether you have prior context on a topic. "
                    "SCOPED BY DEFAULT: results come from the current project's family plus global "
                    "(project-less) memories — other projects' memories never appear unless you widen. "
                    "To widen: pass all_projects=true to search the entire store (each hit then carries "
                    "its 'project' label), or pass project=<label> to hard-filter to one specific project. "
                    "The resume digest and <memgit-recall> blocks show a memory index with counts "
                    "('+N more on <topic>') — those topics are guaranteed to return results here; "
                    "the injected blocks are a teaser of this store, not its full depth. "
                    "Returns memories ranked by relevance — only what matters, not everything. "
                    "Superseded (corrected/replaced) memories are hidden by default. "
                    "This is faster and more relevant than reading individual memory files."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Natural-language description of what you want to recall. "
                                "Examples: 'user preferences for code style', "
                                "'how does the Instagram pipeline work', "
                                "'what trading rules should I follow'"
                            ),
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Max results to return (default 8, max 30). Use 15-20 for broad topic discovery.",
                            "default": 8,
                        },
                        "type_filter": {
                            "type": "string",
                            "enum": _TYPE_ENUM,
                            "description": _TYPE_DESCRIPTIONS,
                        },
                        "project": {
                            "type": "string",
                            "description": (
                                "Hard-filter to exactly one project's memories. Usually "
                                "UNNECESSARY — searches are already scoped to the current "
                                "project's family + global memories. Set only to look at a "
                                "specific other project."
                            ),
                        },
                        "all_projects": {
                            "type": "boolean",
                            "description": (
                                "Search the ENTIRE store instead of the default scope "
                                "(current project family + global). Every hit carries its "
                                "'project' label so cross-project results are attributable."
                            ),
                            "default": False,
                        },
                        "format": {
                            "type": "string",
                            "enum": ["json", "toon"],
                            "description": (
                                "Output format. 'json' (default) is universal and works with all LLMs. "
                                "'toon' is a token-efficient sigil format — use only if you know the TOON spec."
                            ),
                            "default": "json",
                        },
                        "include_superseded": {
                            "type": "boolean",
                            "description": (
                                "Also score memories that a newer memory supersedes. "
                                "Default false — the current head of each correction "
                                "chain is what you want; set true only for history "
                                "archaeology."
                            ),
                            "default": False,
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="get_memory",
                description=(
                    "Fetch a single memory by its exact slug identifier. "
                    "CALL THIS: when search_memories returned a relevant slug and you need "
                    "the full details (why, when to apply, tags). "
                    "Slugs are kebab-case identifiers like 'ig-pipeline-no-fallback' or 'trading-capital-track'."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "slug": {
                            "type": "string",
                            "description": "The kebab-case memory slug (e.g. 'ig-pipeline-no-fallback')",
                        },
                        "format": {
                            "type": "string",
                            "enum": ["json", "toon"],
                            "default": "json",
                        },
                    },
                    "required": ["slug"],
                },
            ),
            Tool(
                name="list_memories",
                description=(
                    "List all memories, returning slug + rule for each. "
                    "CALL THIS: to browse what's stored, discover memory slugs for get_memory, "
                    "or audit the full memory set. For finding relevant memories on a topic, "
                    "use search_memories instead — it is faster and ranked."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "type_filter": {
                            "type": "string",
                            "enum": _TYPE_ENUM,
                            "description": _TYPE_DESCRIPTIONS,
                        },
                        "min_priority": {
                            "type": "integer",
                            "description": (
                                "Only return memories at or above this priority. "
                                "1=low (all memories), 2=medium+, 3=critical only. Default 1."
                            ),
                            "default": 1,
                        },
                    },
                },
            ),
            Tool(
                name="save_memory",
                description=(
                    "Persist a new fact, rule, preference, or lesson to the memory store for future sessions. "
                    "CALL THIS: whenever you learn something the user would want you to remember next time — "
                    "a preference they stated, a rule they corrected you on, a project decision, "
                    "a lesson from a mistake, or a reference to an external system. "
                    "Do NOT save ephemeral or task-specific details; save durable facts only. "
                    "If a memory with the same slug already exists, this updates it — that is exactly "
                    "how 'tr' trackers are meant to be updated when an entity's state changes. "
                    "When this memory CORRECTS or replaces existing ones, pass their slugs in "
                    "'supersedes' instead of writing 'CORRECTED:' prefixes or leaving stale duplicates."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "slug": {
                            "type": "string",
                            "description": (
                                "Short kebab-case identifier, unique per memory. "
                                "Examples: 'user-prefers-terse-responses', 'ig-pipeline-no-fallback', "
                                "'trading-confirm-only-orders'. Use existing slug to update."
                            ),
                        },
                        "rule": {
                            "type": "string",
                            "description": (
                                "The primary fact or rule to remember (max ~200 chars). "
                                "Write as a declarative statement: 'always X', 'never Y', 'Z is located at ...'"
                            ),
                        },
                        "body": {
                            "type": "string",
                            "description": (
                                "Full long-form detail behind the rule — state, decisions, code paths, "
                                "context. Multi-line markdown welcome; this is stored losslessly and "
                                "returned by get_memory. Use it instead of cramming detail into 'rule'."
                            ),
                        },
                        "project": {
                            "type": "string",
                            "description": (
                                "Project this memory belongs to. Defaults to the current workspace — "
                                "set explicitly only for global facts (pass empty string \"\" = applies "
                                "everywhere) or another project. If omitted AND the workspace can't be "
                                "detected, the memory is quarantined under '_unknown' instead of "
                                "becoming global."
                            ),
                        },
                        "type_code": {
                            "type": "string",
                            "enum": _TYPE_ENUM,
                            "description": _TYPE_DESCRIPTIONS,
                            "default": "fb",
                        },
                        "type": {
                            "type": "string",
                            "enum": _TYPE_ENUM,
                            "description": (
                                "Alias for type_code (read tools return this "
                                "field as 'type', so both spellings work here)."
                            ),
                        },
                        "why": {
                            "type": "string",
                            "description": "Why this rule exists — the incident, reason, or motivation. Optional but strongly recommended.",
                        },
                        "when": {
                            "type": "string",
                            "description": "When / where to apply this rule. Optional.",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Topic tags for filtering. Examples: ['instagram', 'trading', 'admin']",
                        },
                        "priority": {
                            "type": "integer",
                            "enum": [1, 2, 3],
                            "description": (
                                "1=low (background context), "
                                "2=medium (default — apply when relevant), "
                                "3=critical (always loaded, applied in every session)"
                            ),
                            "default": 2,
                        },
                        "supersedes": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Slugs of memories this one REPLACES (corrections, updated "
                                "decisions, resolved incidents). Pass this instead of writing "
                                "'CORRECTED:' prefixes or leaving stale duplicates — superseded "
                                "memories stop surfacing in search/recall/resume automatically "
                                "(history is preserved; remove the superseder and they return)."
                            ),
                        },
                        "related": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Slugs of related memories (cross-references, not replacement)."
                            ),
                        },
                    },
                    "required": ["slug", "rule"],
                },
            ),
            Tool(
                name="get_checkpoint_log",
                description=(
                    "Show recent checkpoint history for the memory store — when memories were last synced "
                    "and what changed. CALL THIS: to understand how fresh the memory store is, or to "
                    "debug sync issues."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Max checkpoints to return (default 5)",
                            "default": 5,
                        },
                    },
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        import json

        repo = _load_repo(store_path)
        if repo is None:
            return [TextContent(
                type="text",
                text="Error: memgit store not found. Run `memgit init` in ~/.claude/memgit-store/",
            )]

        if name == "resume_session":
            from .cli import _format_resume_plain
            n_ck = int(arguments.get("checkpoints", 5))
            n_recent = int(arguments.get("recent", 10))
            ctx = repo.resume_context(checkpoints=n_ck, recent=n_recent,
                                      project=_detect_project())
            return [TextContent(type="text", text=_format_resume_plain(ctx))]

        elif name == "search_memories":
            query = arguments.get("query", "")
            top_k = min(int(arguments.get("top_k", 8)), 30)
            type_filter = arguments.get("type_filter")
            project_filter = arguments.get("project")
            all_projects = bool(arguments.get("all_projects", False))
            fmt = arguments.get("format", "json")
            include_superseded = bool(arguments.get("include_superseded", False))
            current_project = _detect_project()

            mnemonics = repo.list()
            if not include_superseded:
                from .links import filter_active
                mnemonics = filter_active(mnemonics)
            if type_filter:
                mnemonics = [m for m in mnemonics if m.type_code == type_filter]
            if project_filter:
                mnemonics = [m for m in mnemonics if m.project == project_filter]

            # Filter-by-default: scope to the current project family + global
            # unless the caller hard-filtered a project or asked for the
            # whole store. Scoping happens inside the scorer so IDF is
            # computed over the scoped corpus.
            scope = None
            if not project_filter and not all_projects:
                scope = current_project
            results = bm25_score(query, mnemonics, top_k=top_k,
                                 boost_project=current_project,
                                 scope_project=scope)

            if not results:
                from .project import same_project_family
                text = "No results found."
                # Fresh-adoption nudge: this project has nothing saved at all
                # (nothing in its project tree — subdirs and parents count).
                if current_project and not any(
                    same_project_family(m.project, current_project)
                    for m in mnemonics
                ):
                    text += (
                        f"\n\nNOTE: project '{current_project}' has NO memories yet — "
                        "memgit was likely adopted mid-project, so there is no initial "
                        "context to search. Bootstrap it now (once): read README/CLAUDE.md/"
                        "docs and `git log --oneline -30`, extract 10-20 durable facts "
                        "(purpose, architecture, conventions, current state, gotchas), and "
                        "save_memory each with a one-line rule + full body. "
                        "Run `memgit onboard` first — it mines the repo's git history and "
                        "manifests into a factual digest plus the complete seeding brief, "
                        "so you read only what matters instead of crawling the tree."
                    )
                return [TextContent(type="text", text=text)]

            if fmt == "toon":
                lines = [f"# search: {query!r}  ({len(results)} results)\n"]
                for r in results:
                    lines.append(f"# score={r.score:.2f}  matched={r.matched_fields}")
                    lines.append(serialize_mnemonic(r.mnemonic))
                    lines.append("")
                text = "\n".join(lines)
            else:
                out = [_mnem_to_dict(r.mnemonic, r.score) for r in results]
                text = json.dumps(out, indent=2)

            try:
                from .usage import record_hits
                record_hits(repo, [r.mnemonic.slug for r in results])
            except Exception:
                pass
            return [TextContent(type="text", text=text)]

        elif name == "get_memory":
            slug = arguments.get("slug", "")
            fmt = arguments.get("format", "json")
            m = repo.get(slug)
            if m is None:
                return [TextContent(type="text", text=f"No memory found: {slug}")]

            if fmt == "toon":
                text = serialize_mnemonic(m)
            else:
                d = _mnem_to_dict(m, include_body=True)
                if m.supersedes:
                    d["supersedes"] = m.supersedes
                if m.related:
                    d["related"] = m.related
                # Reading a retired chain link must be visible as such —
                # otherwise the operator trusts stale state.
                from .links import superseded_by, resolve_head
                all_mems = repo.list()
                heirs = superseded_by(slug, all_mems)
                if heirs:
                    d["superseded_by"] = heirs
                    d["head"] = resolve_head(slug, all_mems)
                    d["note"] = ("This memory has been SUPERSEDED — read 'head' "
                                 "for the current version.")
                text = json.dumps(d, indent=2)

            return [TextContent(type="text", text=text)]

        elif name == "list_memories":
            type_filter = arguments.get("type_filter")
            min_priority = int(arguments.get("min_priority", 1))

            mnemonics = repo.list()
            if type_filter:
                mnemonics = [m for m in mnemonics if m.type_code == type_filter]
            if min_priority > 1:
                mnemonics = [m for m in mnemonics if m.priority >= min_priority]
            mnemonics.sort(key=lambda m: (m.type_code, m.slug))

            if not mnemonics:
                return [TextContent(type="text", text="No memories found.")]

            # list is the audit surface: superseded memories stay visible,
            # but marked, with their chain head named.
            from .links import superseded_slugs, resolve_head
            all_mems = repo.list()
            hidden = superseded_slugs(all_mems)

            lines = [f"# {len(mnemonics)} memories"]
            for m in mnemonics:
                rule_preview = m.rule[:80] + ".." if len(m.rule) > 80 else m.rule
                proj = f" {m.project}" if m.project else ""
                sup = (f" ⊘superseded-by:{resolve_head(m.slug, all_mems)}"
                       if m.slug in hidden else "")
                lines.append(f"{m.slug}\t[{m.type_code}p{m.priority}{proj}]{sup}\t{rule_preview}")

            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "save_memory":
            slug = arguments.get("slug", "").strip()
            rule = arguments.get("rule", "").strip()

            if not slug or not rule:
                return [TextContent(type="text", text="Error: slug and rule are required.")]

            # Accept "type" as an alias: read surfaces return the field as
            # "type", so an operator mirroring get_memory output naturally
            # passes it back under that name.
            type_code = arguments.get("type_code") or arguments.get("type") or "fb"
            why = arguments.get("why")
            when = arguments.get("when")
            body = arguments.get("body")
            tags = arguments.get("tags", [])
            priority = int(arguments.get("priority", 2))
            # project: explicit value wins; empty string = deliberately global
            # (applies everywhere); absent = the workspace this server is
            # running in. Detection failing must NEVER silently produce a
            # global memory — the save is quarantined under `_unknown`
            # instead, and the response says so.
            from .project import UNKNOWN_PROJECT
            quarantined = False
            if "project" in arguments:
                project = (arguments.get("project") or "").strip() or None
            else:
                project = _detect_project()
                if project is None:
                    project = UNKNOWN_PROJECT
                    quarantined = True

            existing = repo.get(slug)
            now = datetime.now(timezone.utc)

            from .links import validate_relations
            sup_list, rel_list, warnings = validate_relations(
                slug, arguments.get("supersedes"), arguments.get("related"),
                repo.list())

            m = Mnemonic(
                type_code=type_code,
                slug=slug,
                timestamp=now,
                rule=rule,
                priority=priority,
                tags=tags if isinstance(tags, list) else [],
                why=why,
                when=when,
                body=body,
                project=project,
                supersedes=sup_list,
                related=rel_list,
            )

            repo.add(m)
            # Checkpoint immediately with real provenance. Relying on a
            # later session-end sync leaves saves staged indefinitely on
            # machines with no markdown memories, and buries them in
            # `sync:` messages when it does run. One save = one checkpoint,
            # rollback-able and attributable in the log.
            ck_sha = repo.commit(
                message=f"save: {slug} [{type_code}]",
                trigger="mcp_save",
            )

            action = "updated" if existing else "saved"
            out: dict[str, Any] = {
                "status": "ok",
                "action": action,
                "slug": slug,
                "type": type_code,
                "priority": priority,
                "project": project,
                "checkpoint": (ck_sha or "")[:8] or None,
            }
            if sup_list:
                out["supersedes"] = sup_list
            if rel_list:
                out["related"] = rel_list
            if quarantined:
                warnings.append(
                    "project could not be determined — memory quarantined "
                    f"under '{UNKNOWN_PROJECT}' (it will not surface in any "
                    "project's recall). Pass project explicitly (a label, or "
                    "\"\" for global), or run from the project directory; "
                    "relabel existing ones with `memgit doctor --relabel`."
                )
            if warnings:
                out["warnings"] = warnings
            return [TextContent(type="text", text=json.dumps(out, indent=2))]

        elif name == "get_checkpoint_log":
            limit = int(arguments.get("limit", 5))
            checkpoints = repo.log(limit=limit)
            if not checkpoints:
                return [TextContent(type="text", text="No checkpoints yet.")]

            lines = []
            for ck in checkpoints:
                sha_s = ck.sha[:8] if ck.sha else "?"
                ts = ck.timestamp.strftime("%Y-%m-%d %H:%M")
                d = ck.diff_summary
                delta = ""
                if d:
                    parts = []
                    if d.added:
                        parts.append(f"+{len(d.added)}")
                    if d.modified:
                        parts.append(f"~{len(d.modified)}")
                    if d.removed:
                        parts.append(f"-{len(d.removed)}")
                    if parts:
                        delta = "  " + " ".join(parts)
                lines.append(f"{sha_s}  {ts}  {ck.message}{delta}")

            return [TextContent(type="text", text="\n".join(lines))]

        else:
            # Raising lets the MCP layer mark the result isError=true —
            # returning text would read as success to a compliant client.
            raise ValueError(f"Unknown tool: {name}")

    # Run
    import asyncio

    async def _main():
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    asyncio.run(_main())
