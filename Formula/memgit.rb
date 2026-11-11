class Memgit < Formula
  include Language::Python::Virtualenv

  desc "One memory for Claude Code, Cursor and Codex on every machine, versioned"
  homepage "https://memgit.dev"
  url "https://files.pythonhosted.org/packages/source/m/memgit/memgit-0.14.3.tar.gz"
  sha256 "51de8ef1130ef99cd21937396a2056e7654147960b08c31c55df3638c7f457e8"
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
