class Memgit < Formula
  include Language::Python::Virtualenv

  desc "Git for AI memory — version-controlled context persistence across Claude, GPT, Cursor, Windsurf and more"
  homepage "https://memgit.dev"
  url "https://files.pythonhosted.org/packages/f5/19/d4d66d9dbefad7d9f711371f0b46e51489263122f8670e00814fef7a024c/memgit-0.1.4.tar.gz"
  sha256 "a3e553075de6cec1e58ef47e49c37a942eafcdc2c1fbf4135901ebc00a068f0e"
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
