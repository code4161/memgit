class Memgit < Formula
  include Language::Python::Virtualenv

  desc "Git for AI memory — version-controlled context persistence across Claude, GPT, Cursor, Windsurf and more"
  homepage "https://memgit.dev"
  url "https://files.pythonhosted.org/packages/66/51/4f4b32c4e7d9165cf10ab51c7d155a10e02b2a5b16cddfff103c4fc70f21/memgit-0.7.0.tar.gz"
  sha256 "1accb8ec9c880aeaece3c318620dc50ae91ec0f09d84ba590e1d37427113efb6"
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
