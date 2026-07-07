class Memgit < Formula
  include Language::Python::Virtualenv

  desc "Git for AI memory — version-controlled context persistence across Claude, GPT, Cursor, Windsurf and more"
  homepage "https://memgit.dev"
  url "https://files.pythonhosted.org/packages/60/1f/ebfe022dea24c9ec05a6ba0e3a36abf4b8d2bd377a99f26e2690e7067a71/memgit-0.4.0.tar.gz"
  sha256 "b523b13eeeaa141010f775f08433fb5d9a5e80c756b189d436a70a0928f2d5d6"
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
