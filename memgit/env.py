"""Every environment variable memgit reads, in one place.

A memory tool runs inside someone else's agent, so "what does this process read
from my environment?" deserves an answer that is checkable rather than a claim
in a README. This module is that answer, and `tests/test_env_inventory.py`
walks the package's AST on every test run and fails if the code reads a name
that is not listed here, or if a name listed here is read nowhere — so the
inventory cannot drift away from the code the way documentation does.

memgit reads these and nothing else. It writes none of them, and it never reads
an environment variable to decide whether to send data anywhere: the cloud
endpoints below are overrides for a sync the user has already opted into by
running `memgit cloud login`.
"""

from __future__ import annotations

#: name -> what memgit does with it. Keep the description to one line.
KNOWN_ENV_VARS: dict[str, str] = {
    # ── where the store and memgit's own state live ──────────────────────────
    'MEMGIT_STORE': (
        'Absolute path to the memory store. When set it is the ONLY candidate '
        '— an explicit store never silently falls back to another one.'
    ),
    'MEMGIT_HOME': (
        "Base directory for memgit's per-person state, currently the licence "
        'file (default ~/.memgit, mode 0600).'
    ),
    'MEMGIT_PROJECT': (
        'Forces the project label instead of detecting it from the working '
        'directory.'
    ),

    # ── attribution ──────────────────────────────────────────────────────────
    'MEMGIT_AUTHOR': (
        'Explicit author stamped on checkpoints, for multi-agent jobs where '
        'several writers share one machine account. Wins over MEMGIT_CLIENT.'
    ),
    'MEMGIT_CLIENT': (
        'The host that launched this process (claude-code, cursor, ...), '
        'stamped into checkpoints so a memory says where it came from.'
    ),
    'USER': 'Fallback author name when neither MEMGIT_AUTHOR nor MEMGIT_CLIENT is set.',
    'USERNAME': 'Windows fallback for USER.',

    # ── licensing (memgit Pro) ───────────────────────────────────────────────
    'MEMGIT_LICENSE_KEY': (
        'memgit Pro licence key. Never printed in full — `memgit pro status` '
        'shows the last four characters.'
    ),
    'MEMGIT_POLAR_API': 'Overrides the licence-validation API base URL (testing).',
    'MEMGIT_POLAR_ORG_ID': 'Overrides the Polar organisation the licence is checked against.',

    # ── cloud sync (only used after `memgit cloud login`) ────────────────────
    'MEMGIT_CLOUD_API': 'Overrides the memgit cloud API base URL.',
    'MEMGIT_CLOUD_APP': 'Overrides the memgit cloud web app base URL used in printed links.',
    'MEMGIT_CLOUD_NO_CACHE': (
        'Set to 1/true/yes to keep decrypted keys out of credentials.json; the '
        'passphrase is then re-prompted per command.'
    ),

    # ── tuning ───────────────────────────────────────────────────────────────
    'MEMGIT_LOCK_TIMEOUT': 'Seconds a writer waits for the store lock before giving up (default 10).',
    'MEMGIT_IDLE_EVICT_SECONDS': (
        'Idle seconds before the MCP server drops its in-memory caches while '
        'staying connected (default 900).'
    ),
    'MEMGIT_HOUSEKEEPING_INTERVAL': 'Seconds between the MCP server\'s housekeeping passes.',

    # ── set by other software, read but never written by memgit ─────────────
    'CLAUDE_PROJECT_DIR': (
        'Set by Claude Code for hook processes; used as one input to project '
        'detection when the working directory is not the project root.'
    ),
    'PYTEST_CURRENT_TEST': (
        'Set by pytest. Its presence suppresses automatic backups, so a test '
        'run never writes into a real backup location.'
    ),
}


def render_table() -> str:
    """The inventory as plain aligned text, for `--help` output or a README."""
    width = max(len(name) for name in KNOWN_ENV_VARS)
    return '\n'.join(
        f'{name.ljust(width)}  {purpose}'
        for name, purpose in sorted(KNOWN_ENV_VARS.items())
    )
