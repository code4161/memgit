"""The environment-variable inventory must match the code, both ways.

`memgit/env.py` documents every variable memgit reads. A document drifts; this
test is the mechanism that keeps it honest — it walks the package's AST and
compares what the code actually reads against what the inventory claims.

It also covers the dynamic case: `repo.py` reads MEMGIT_AUTHOR / MEMGIT_CLIENT
through a loop over a tuple of names, which no `os.environ.get('X')` scan can
see, so any bare `MEMGIT_*` string constant in the package counts as a read.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from memgit.env import KNOWN_ENV_VARS, render_table

PACKAGE = Path(__file__).resolve().parent.parent / 'memgit'
ENVISH = re.compile(r'^[A-Z][A-Z0-9_]*$')


def _names_read_by_the_code() -> set[str]:
    names: set[str] = set()
    for path in sorted(PACKAGE.rglob('*.py')):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            # os.environ.get('X') and os.getenv('X')
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ('get', 'getenv') and node.args:
                    arg = node.args[0]
                    src = ast.unparse(node.func)
                    if ('environ' in src or 'getenv' in src) \
                            and isinstance(arg, ast.Constant) \
                            and isinstance(arg.value, str) and ENVISH.match(arg.value):
                        names.add(arg.value)
            # os.environ['X']
            if isinstance(node, ast.Subscript) and 'environ' in ast.unparse(node.value):
                key = node.slice
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    names.add(key.value)
            # a bare 'MEMGIT_X' constant — catches names read through a variable
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.startswith('MEMGIT_') and ENVISH.match(node.value):
                    names.add(node.value)
    return names


def test_inventory_lists_every_variable_the_code_reads():
    undocumented = _names_read_by_the_code() - set(KNOWN_ENV_VARS)
    assert not undocumented, (
        f'These environment variables are read by memgit but missing from '
        f'memgit/env.py: {sorted(undocumented)}'
    )


def test_inventory_lists_nothing_the_code_stopped_reading():
    stale = set(KNOWN_ENV_VARS) - _names_read_by_the_code()
    assert not stale, (
        f'memgit/env.py documents environment variables nothing reads any '
        f'more: {sorted(stale)}'
    )


def test_every_entry_has_a_description():
    for name, purpose in KNOWN_ENV_VARS.items():
        assert purpose.strip(), f'{name} has no description'


def test_render_table_covers_every_entry():
    table = render_table()
    for name in KNOWN_ENV_VARS:
        assert name in table


def test_the_readme_table_lists_every_variable():
    """The README says its table comes from this inventory. Hold it to that."""
    readme = (Path(__file__).resolve().parent.parent / 'README.md').read_text()
    start = readme.index('## What memgit reads from your environment')
    section = readme[start:readme.index('### How the project label is decided', start)]
    missing = [name for name in KNOWN_ENV_VARS if f'`{name}`' not in section]
    assert not missing, (
        f'README environment table is missing: {sorted(missing)} — regenerate it '
        f'from memgit/env.py'
    )
