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
    "(3) memgit is cross-tool: memories saved here are also available in Cursor, Windsurf, GPT, and Gemini."
)

_TYPE_DESCRIPTIONS = (
    "fb=feedback (corrections, preferences, how the user likes to work), "
    "us=user (who the user is, their role, expertise, goals), "
    "pj=project (active projects, goals, decisions, deadlines), "
    "rf=reference (pointers to external systems, URLs, tools), "
    "cn=convention (code style, naming, architecture rules), "
    "lx=lesson (lessons learned, post-mortems, 'we got burned by X')"
)


def _default_store() -> Path:
    from .repo import default_store_candidates
    for candidate in default_store_candidates():
        if (candidate / ".memgit").is_dir():
            return candidate
    return Path.home() / ".claude" / "memgit-store"


def _load_repo(store_path: Path | None) -> Repository | None:
    path = store_path or _default_store()
    memgit_dir = path / ".memgit"
    if not memgit_dir.is_dir():
        return None
    return Repository(memgit_dir)


def _mnem_to_dict(m: Mnemonic, score: float | None = None) -> dict[str, Any]:
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
    if score is not None:
        d["score"] = round(score, 4)
    return d


def run_server(store_path: Path | None = None) -> None:
    """Run the MCP server on stdio."""
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
                    "Get a compact 'where we left off' digest: the last checkpoints (most recent "
                    "actions taken), staged work in flight, recently updated memories, and critical "
                    "rules that always apply. "
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
                    "Returns memories ranked by relevance — only what matters, not everything. "
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
                            "enum": ["fb", "us", "pj", "rf", "cn", "lx"],
                            "description": _TYPE_DESCRIPTIONS,
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
                            "enum": ["fb", "us", "pj", "rf", "cn", "lx"],
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
                    "If a memory with the same slug already exists, this updates it."
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
                        "type_code": {
                            "type": "string",
                            "enum": ["fb", "us", "pj", "rf", "cn", "lx"],
                            "description": _TYPE_DESCRIPTIONS,
                            "default": "fb",
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
            ctx = repo.resume_context(checkpoints=n_ck, recent=n_recent)
            return [TextContent(type="text", text=_format_resume_plain(ctx))]

        elif name == "search_memories":
            query = arguments.get("query", "")
            top_k = min(int(arguments.get("top_k", 8)), 30)
            type_filter = arguments.get("type_filter")
            fmt = arguments.get("format", "json")

            mnemonics = repo.list()
            if type_filter:
                mnemonics = [m for m in mnemonics if m.type_code == type_filter]

            results = bm25_score(query, mnemonics, top_k=top_k)

            if not results:
                return [TextContent(type="text", text="No results found.")]

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
                text = json.dumps(_mnem_to_dict(m), indent=2)

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

            lines = [f"# {len(mnemonics)} memories"]
            for m in mnemonics:
                rule_preview = m.rule[:80] + ".." if len(m.rule) > 80 else m.rule
                lines.append(f"{m.slug}\t[{m.type_code}p{m.priority}]\t{rule_preview}")

            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "save_memory":
            slug = arguments.get("slug", "").strip()
            rule = arguments.get("rule", "").strip()

            if not slug or not rule:
                return [TextContent(type="text", text="Error: slug and rule are required.")]

            type_code = arguments.get("type_code", "fb")
            why = arguments.get("why")
            when = arguments.get("when")
            tags = arguments.get("tags", [])
            priority = int(arguments.get("priority", 2))

            existing = repo.get(slug)
            now = datetime.now(timezone.utc)

            m = Mnemonic(
                type_code=type_code,
                slug=slug,
                timestamp=now,
                rule=rule,
                priority=priority,
                tags=tags if isinstance(tags, list) else [],
                why=why,
                when=when,
            )

            repo.add(m)

            action = "updated" if existing else "saved"
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "ok",
                    "action": action,
                    "slug": slug,
                    "type": type_code,
                    "priority": priority,
                }, indent=2),
            )]

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
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

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
