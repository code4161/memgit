"""The declared `mcp` range must exclude every version with a known advisory.

memgit speaks stdio and imports only `mcp.server.Server` and `mcp.types`, so
none of the six published MCP-SDK advisories was ever reachable here: five are
in the SDK's HTTP, SSE and WebSocket server transports, and the sixth needs
`server.experimental.enable_tasks()`, which memgit never calls. That is an
argument about today's code, and it is not what a resolver or a supply-chain
scanner reads: they read the range. So the range states the floor, and this
test is what stops the floor being lowered again by a well-meaning edit.

The upper bound has its own reason, recorded in pyproject.toml: the SDK's 2.0
removed `Server.list_tools` / `Server.call_tool`, and an unbounded range shipped
a server that crashed on startup for every fresh install between 2026-07-28 and
2026-09-06.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parent.parent / 'pyproject.toml'

#: advisory -> the highest version it affects. Sources: GitHub Advisory
#: Database, read 2026-09-11.
VULNERABLE_MCP_VERSIONS = {
    'CVE-2025-53366 (FastMCP validation-error DoS)': '1.9.3',
    'CVE-2025-53365 (Streamable HTTP unhandled exception)': '1.9.4',
    'CVE-2025-66416 (DNS rebinding protection off by default)': '1.22.0',
    'CVE-2026-52869 (HTTP transports skip principal check)': '1.27.1',
    'CVE-2026-52870 (experimental task handlers leak across sessions)': '1.27.1',
    'CVE-2026-59950 (WebSocket transport skips Host/Origin check)': '1.28.0',
}


def _mcp_specifier() -> str:
    data = tomllib.loads(PYPROJECT.read_text())
    for dep in data['project']['dependencies']:
        if dep.replace(' ', '').startswith('mcp'):
            return dep
    pytest.fail('pyproject.toml declares no dependency on mcp')


def test_declared_range_excludes_every_known_vulnerable_mcp():
    specifiers = pytest.importorskip('packaging.specifiers')
    spec = specifiers.SpecifierSet(_mcp_specifier().replace('mcp', '', 1))
    for advisory, version in VULNERABLE_MCP_VERSIONS.items():
        assert version not in spec, (
            f'mcp {version} satisfies the declared range but is affected by '
            f'{advisory}'
        )


def test_declared_range_still_excludes_the_2x_api_break():
    specifiers = pytest.importorskip('packaging.specifiers')
    spec = specifiers.SpecifierSet(_mcp_specifier().replace('mcp', '', 1))
    for version in ('2.0.0', '2.1.1', '2.2.0'):
        assert version not in spec, (
            f'mcp {version} satisfies the declared range, but 2.x removed '
            f'Server.list_tools / Server.call_tool and memgit serve cannot run '
            f'on it'
        )


def test_a_currently_supported_version_is_still_installable():
    specifiers = pytest.importorskip('packaging.specifiers')
    spec = specifiers.SpecifierSet(_mcp_specifier().replace('mcp', '', 1))
    assert '1.30.0' in spec, 'the range excludes the newest 1.x release'


def test_the_startup_guard_quotes_the_same_range():
    guard = (Path(__file__).resolve().parent.parent / 'memgit' / 'mcp_server.py').read_text()
    assert _mcp_specifier() in guard, (
        'memgit/mcp_server.py tells the user to install a different range from '
        'the one pyproject.toml declares'
    )
