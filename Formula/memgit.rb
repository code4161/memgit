class Memgit < Formula
  include Language::Python::Virtualenv

  desc "Git for AI memory — version-controlled context persistence across Claude, GPT, Cursor, Windsurf and more"
  homepage "https://memgit.dev"
  url "https://files.pythonhosted.org/packages/53/65/ce04d6c08de961d777230e4d7bba1d66eb111aa22e6cc19de7102d4be3d2/memgit-0.6.2.tar.gz"
  sha256 "426bc295fa5055b5f7ae65cc5b4630ec84d2b5b77ba688177d99519d4c5a665f"
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
