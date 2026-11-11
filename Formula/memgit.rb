class Memgit < Formula
  include Language::Python::Virtualenv

  desc "One memory for Claude Code, Cursor and Codex on every machine, versioned"
  homepage "https://memgit.dev"
  url "https://files.pythonhosted.org/packages/source/m/memgit/memgit-0.15.0.tar.gz"
  sha256 "ea6bc6af0e382f0f9616f21335d3459fd1223a5521f06098a82cee7d8d9a31d9"
  license "MIT"

  depends_on "python@3.12"

  def install
    venv = virtualenv_create(libexec, "python3.12")
    venv.pip_install buildpath
    bin.install_symlink venv.root/"bin/memgit"
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/memgit --version")
    assert_match "Usage:", shell_output("#{bin}/memgit --help")
  end
end
