class Memgit < Formula
  include Language::Python::Virtualenv

  desc "Git for AI memory — version-controlled context persistence across Claude, GPT, Cursor, Windsurf and more"
  homepage "https://memgit.dev"
  url "https://files.pythonhosted.org/packages/58/9d/ba0c45067f7d3360f1fdc0806db9c8bcd425a87579d34567bc04d94a4dbc/memgit-0.2.0.tar.gz"
  sha256 "35a889caa8bfe0f73b4dc90a4a2c74b8d2f3fe39d571c10771b9ae6ab26019cc"
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
