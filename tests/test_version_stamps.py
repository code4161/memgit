"""Every committed version stamp must agree with `memgit.__version__`.

Version skew across channels is this project's recurring release bug, and it has
bitten twice in a way a person could not see: Chocolatey packed 0.9.0 under a
0.10.0 tag for months because `memgit.nuspec` carried a hardcoded version, and
the VS Code Marketplace drifted two versions behind. Both were found by querying
a channel after the fact. This test moves the check before the tag.

Chocolatey is checked too. `choco-publish.yml` stamps the nuspec and the
install script FROM THE TAG and fails if the packed artifact is not the version
it meant to build, so CI cannot ship the wrong number. But with that as the only
guard, the committed files sat at 0.10.0 through three releases, and anyone
packing locally or reading the repo saw the wrong version. Both guards agree on
the same number, so neither fights the other.

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


def test_chocolatey_stamps_match():
    """The nuspec <version> and the pinned pip install in the install script."""
    nuspec = ROOT / 'chocolatey/memgit.nuspec'
    script = ROOT / 'chocolatey/tools/chocolateyInstall.ps1'
    if not nuspec.exists():
        pytest.skip('no chocolatey package in this checkout')
    assert re.findall(r'<version>([^<]+)</version>', nuspec.read_text()) == [__version__]
    assert re.findall(r'memgit==([0-9.]+)', script.read_text()) == [__version__]
