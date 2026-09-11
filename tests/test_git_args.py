"""`remote` and `branch` are validated before they become git argv.

No shell is involved anywhere in memgit's git calls, so there is nothing to
quote — but argv is not inert. git reads a leading '-' as an option, which turns
a remote name into `--upload-pack=<cmd>`; and an `ext::` URL is by definition a
command git runs. These values reach memgit from a CLI argument, a teammate's
checked-in config, or an MCP caller.
"""

from __future__ import annotations

from memgit.repo import Repository, validate_git_branch, validate_git_remote


class TestRemote:
    def test_accepts_a_name_and_a_url(self):
        assert validate_git_remote('origin') is None
        assert validate_git_remote('git@github.com:team/ai-memory.git') is None
        assert validate_git_remote('https://github.com/team/ai-memory.git') is None

    def test_rejects_option_shaped_values(self):
        assert validate_git_remote('--upload-pack=touch /tmp/pwned')
        assert validate_git_remote('-c')

    def test_rejects_transports_that_execute_their_url(self):
        assert validate_git_remote('ext::sh -c whoami')
        assert validate_git_remote('EXT::sh -c whoami')
        assert validate_git_remote('fd::7')

    def test_rejects_empty_and_control_characters(self):
        assert validate_git_remote('')
        assert validate_git_remote('   ')
        assert validate_git_remote('origin\nurl.x.insteadOf=y')


class TestBranch:
    def test_accepts_ordinary_branch_names(self):
        for name in ('main', 'master', 'feature/sync-fix', 'release-1.2'):
            assert validate_git_branch(name) is None, name

    def test_rejects_option_shaped_values(self):
        assert validate_git_branch('--output=/tmp/pwned')

    def test_rejects_what_git_check_ref_format_rejects(self):
        for name in ('a b', 'a~1', 'a^', 'a:b', 'a?', 'a*', 'a[b', 'a\\b',
                     'a..b', 'a@{0}', '@', 'x.lock', 'a/', '/a', '.a', 'a.',
                     'a//b', ''):
            assert validate_git_branch(name), f'{name!r} should be refused'


class TestRepositoryRefuses:
    def test_push_refuses_before_writing_anything(self, tmp_path):
        repo = Repository.init(tmp_path / 'store')
        (repo.path.parent / '.git').mkdir()

        def _must_not_run(*a, **kw):
            raise AssertionError('git_push exported flat files before refusing '
                                 'the remote')

        repo.write_flat = _must_not_run
        ok, msg = repo.git_push(remote='ext::sh -c whoami', branch='main')
        assert ok is False
        assert 'ext::' in msg

    def test_pull_refuses_an_option_shaped_branch(self, tmp_path):
        repo = Repository.init(tmp_path / 'store')
        (repo.path.parent / '.git').mkdir()
        ok, msg, count = repo.git_pull(remote='origin', branch='--upload-pack=id')
        assert ok is False
        assert count == 0
        assert 'branch' in msg
