class Memgit < Formula
  include Language::Python::Virtualenv

  desc "Git for AI memory — version-controlled context persistence across Claude, GPT, Cursor, Windsurf and more"
  homepage "https://memgit.dev"
  url "https://files.pythonhosted.org/packages/a8/53/7f9f99173eececd6ce438844f544ad4760f805149918eae60efa7da20cbc/memgit-0.6.1.tar.gz"
  sha256 "48f81815b5f5bd99eedb942da9c683386758fb29df63971efb589d78a1994b12"
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
