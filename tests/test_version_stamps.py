"""Every committed version stamp must agree with `memgit.__version__`.

Version skew across channels is this project's recurring release bug, and it has
bitten twice in a way a person could not see: Chocolatey packed 0.9.0 under a
0.10.0 tag for months because `memgit.nuspec` carried a hardcoded version, and
the VS Code Marketplace drifted two versions behind. Both were found by querying
a channel after the fact. This test moves the check before the tag.

Chocolatey is deliberately absent: `choco-publish.yml` now stamps the nuspec and
the install script FROM THE TAG and fails if the packed artifact is not the
version it meant to build, so the file in the repo is not a source of truth and
asserting on it would fight the mechanism that fixed it.

The Homebrew formula is absent for the opposite reason: it pins the sha256 of
the PyPI sdist, so it can only be bumped AFTER PyPI publishes, and it lives in
another repo.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

from memgit import __version__

ROOT = Path(__file__).resolve().parent.parent


def test_version_is_a_release_number():
    assert re.fullmatch(r'\d+\.\d+\.\d+', __version__), __version__


def test_pyproject_matches():
    data = tomllib.loads((ROOT / 'pyproject.toml').read_text())
    assert data['project']['version'] == __version__


@pytest.mark.parametrize('rel', [
    'npm-wrapper/package.json',
    'vscode-extension/package.json',
])
def test_package_manifest_matches(rel):
    path = ROOT / rel
    if not path.exists():
        pytest.skip(f'{rel} not in this checkout')
    assert json.loads(path.read_text())['version'] == __version__


def test_vscode_lockfile_matches():
    """The lockfile carries the package version twice, and a `node` engine
    constraint that merely looks like a version. Only the first two are ours."""
    path = ROOT / 'vscode-extension/package-lock.json'
    if not path.exists():
        pytest.skip('no vscode-extension in this checkout')
    data = json.loads(path.read_text())
    assert data['version'] == __version__
    assert data['packages']['']['version'] == __version__


def test_every_server_json_stamp_matches():
    """server.json states the version three times: the server, and once per
    package entry. The MCP registry rejects a publish where they disagree."""
    path = ROOT / 'server.json'
    if not path.exists():
        pytest.skip('no server.json in this checkout')
    raw = path.read_text()
    stamps = re.findall(r'"version"\s*:\s*"([^"]+)"', raw)
    assert stamps, 'server.json declares no version at all'
    assert set(stamps) == {__version__}, f'server.json stamps: {stamps}'


def test_changelog_has_an_entry_for_this_version():
    """A release with no changelog entry is a release nobody can read."""
    changelog = (ROOT / 'CHANGELOG.md').read_text()
    assert f'## [{__version__}]' in changelog, (
        f'CHANGELOG.md has no `## [{__version__}]` heading — either the version '
        f'was bumped without writing the entry, or the entry is still under '
        f'[Unreleased]'
    )
