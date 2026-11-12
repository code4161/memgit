"""memgit tips: posts the address to memgit.dev's tips route. No network: a stub server."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from click.testing import CliRunner

from memgit.cli import cli


def _serve(reply, status=200):
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen['body'] = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            seen['ua'] = self.headers.get('User-Agent')
            out = json.dumps(reply).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    return f'http://127.0.0.1:{srv.server_port}/api/tips', seen


def test_tips_posts_email_with_cli_source(monkeypatch):
    url, seen = _serve({'ok': True, 'message': 'Check your inbox for a confirmation link.'})
    monkeypatch.setenv('MEMGIT_TIPS_URL', url)
    r = CliRunner().invoke(cli, ['tips', 'a@example.org'])
    assert r.exit_code == 0, r.output
    assert 'Check your inbox' in r.output
    assert seen['body'] == {'email': 'a@example.org', 'source': 'cli'}
    assert seen['ua'].startswith('memgit-cli/')


def test_tips_reports_a_refusal_and_exits_nonzero(monkeypatch):
    url, _ = _serve({'ok': False, 'message': 'That does not look like an email address.'}, 400)
    monkeypatch.setenv('MEMGIT_TIPS_URL', url)
    r = CliRunner().invoke(cli, ['tips', 'nope'])
    assert r.exit_code == 1
    assert 'does not look like an email' in r.output


def test_tips_unreachable_points_to_the_page(monkeypatch):
    monkeypatch.setenv('MEMGIT_TIPS_URL', 'http://127.0.0.1:9/api/tips')
    r = CliRunner().invoke(cli, ['tips', 'a@example.org'])
    assert r.exit_code == 1
    assert 'memgit.dev/tips' in r.output
