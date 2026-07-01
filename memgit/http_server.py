"""memgit HTTP server — REST API for GPT Custom Actions and Gemini function calling.

Run with: memgit serve --http [--port 7474]

Serves the same 5 tools as the MCP server but over HTTP+JSON so any LLM that
supports OpenAPI-based tool use (GPT Custom Actions, Gemini Extensions, etc.)
can call it without MCP support.

The /openapi.json endpoint serves the spec so GPT Actions can import it directly.
"""

from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

from .models import Mnemonic
from .repo import Repository
from .scorer import score as bm25_score


def _default_store() -> Path:
    return Path.home() / ".claude" / "memgit-store"


def _load_repo(store_path: Path | None) -> Repository | None:
    path = store_path or _default_store()
    memgit_dir = path / ".memgit"
    if not memgit_dir.is_dir():
        return None
    return Repository(memgit_dir)


def _mnem_to_dict(m: Mnemonic, score: float | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {"slug": m.slug, "type": m.type_code, "priority": m.priority, "rule": m.rule}
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


def _load_openapi_spec() -> dict:
    spec_path = Path(__file__).parent.parent / "openapi.json"
    if spec_path.exists():
        return json.loads(spec_path.read_text())
    return {"error": "openapi.json not found"}


class MemgitHandler(BaseHTTPRequestHandler):
    store_path: Path | None = None
    openapi_spec: dict = {}

    def log_message(self, fmt, *args):
        pass  # suppress default Apache-style logs

    def _json_response(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, indent=2, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, msg: str, status: int = 400) -> None:
        self._json_response({"error": msg}, status)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        if path == "/status":
            repo = _load_repo(self.store_path)
            self._json_response({
                "status": "ok",
                "version": "0.1.2",
                "store": str(self.store_path or _default_store()),
                "initialized": repo is not None,
                "memory_count": len(repo.list()) if repo else 0,
            })
            return

        if path in ("/", "/openapi.json"):
            spec = dict(self.openapi_spec)
            spec["servers"] = [{"url": f"http://localhost:{self.server.server_address[1]}"}]
            self._json_response(spec)
            return

        if path == "/memories":
            repo = _load_repo(self.store_path)
            if repo is None:
                self._error("memgit store not found. Run `memgit init` first.", 503)
                return
            type_filter = qs.get("type_filter", [None])[0]
            min_priority = int(qs.get("min_priority", [1])[0])
            mnemonics = repo.list()
            if type_filter:
                mnemonics = [m for m in mnemonics if m.type_code == type_filter]
            if min_priority > 1:
                mnemonics = [m for m in mnemonics if m.priority >= min_priority]
            mnemonics.sort(key=lambda m: (m.type_code, m.slug))
            self._json_response([_mnem_to_dict(m) for m in mnemonics])
            return

        m = re.match(r"^/memories/([a-z0-9_-]+)$", path)
        if m:
            slug = m.group(1)
            repo = _load_repo(self.store_path)
            if repo is None:
                self._error("memgit store not found.", 503)
                return
            mem = repo.get(slug)
            if mem is None:
                self._error(f"Memory not found: {slug}", 404)
                return
            self._json_response(_mnem_to_dict(mem))
            return

        if path == "/checkpoints":
            repo = _load_repo(self.store_path)
            if repo is None:
                self._error("memgit store not found.", 503)
                return
            limit = int(qs.get("limit", [5])[0])
            checkpoints = repo.log(limit=limit)
            results = []
            for ck in checkpoints:
                d = {"sha": ck.sha[:8] if ck.sha else "?", "timestamp": ck.timestamp.isoformat(), "message": ck.message}
                if ck.diff_summary:
                    d["added"] = len(ck.diff_summary.added)
                    d["modified"] = len(ck.diff_summary.modified)
                    d["removed"] = len(ck.diff_summary.removed)
                results.append(d)
            self._json_response(results)
            return

        self._error(f"Not found: {path}", 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/memories/search":
            body = self._read_body()
            query = body.get("query", "")
            if not query:
                self._error("query is required")
                return
            top_k = min(int(body.get("top_k", 8)), 30)
            type_filter = body.get("type_filter")

            repo = _load_repo(self.store_path)
            if repo is None:
                self._error("memgit store not found.", 503)
                return

            mnemonics = repo.list()
            if type_filter:
                mnemonics = [m for m in mnemonics if m.type_code == type_filter]

            results = bm25_score(query, mnemonics, top_k=top_k)
            self._json_response([_mnem_to_dict(r.mnemonic, r.score) for r in results])
            return

        self._error(f"Not found: {path}", 404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        m = re.match(r"^/memories/([a-z0-9_-]+)$", path)
        if m:
            slug = m.group(1)
            body = self._read_body()
            rule = body.get("rule", "").strip()
            if not rule:
                self._error("rule is required")
                return

            repo = _load_repo(self.store_path)
            if repo is None:
                self._error("memgit store not found.", 503)
                return

            existing = repo.get(slug)
            mem = Mnemonic(
                type_code=body.get("type_code", "fb"),
                slug=slug,
                timestamp=datetime.now(timezone.utc),
                rule=rule,
                priority=int(body.get("priority", 2)),
                tags=body.get("tags", []),
                why=body.get("why"),
                when=body.get("when"),
            )
            repo.add(mem)
            action = "updated" if existing else "saved"
            self._json_response({"status": "ok", "action": action, "slug": slug})
            return

        self._error(f"Not found: {path}", 404)


def run_http_server(port: int = 7474, store_path: Path | None = None) -> None:
    """Run the memgit HTTP REST server."""
    MemgitHandler.store_path = store_path
    MemgitHandler.openapi_spec = _load_openapi_spec()

    server = HTTPServer(("127.0.0.1", port), MemgitHandler)
    print(f"memgit HTTP server running at http://127.0.0.1:{port}")
    print(f"  OpenAPI spec: http://127.0.0.1:{port}/openapi.json")
    print(f"  For GPT Custom Actions: import the spec from http://127.0.0.1:{port}/openapi.json")
    print(f"  Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
