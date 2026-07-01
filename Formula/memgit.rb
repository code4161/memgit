class Memgit < Formula
  include Language::Python::Virtualenv

  desc "Git for AI memory — version-controlled context persistence across Claude, GPT, Cursor, Windsurf and more"
  homepage "https://memgit.dev"
  # TODO: After publishing to PyPI, replace URL + sha256 with:
  #   url "https://files.pythonhosted.org/packages/source/m/memgit/memgit-0.1.0.tar.gz"
  #   sha256 "<run: curl -sL <url> | shasum -a 256>"
  url "https://github.com/code4161/memgit/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "REPLACE_WITH_ACTUAL_SHA256_AFTER_TAGGING"
  license "MIT"

  depends_on "python@3.12"

  # Run `brew pypi-formula memgit` after publishing to PyPI to auto-generate
  # these resource stanzas with correct URLs + sha256 hashes.
  resource "click" do
    url "https://files.pythonhosted.org/packages/source/c/click/click-8.1.8.tar.gz"
    sha256 "ed53c9d8821d46d604ac3c43b89d0d2ba426acfba28ef3e749b22b39765b72e5"
  end

  resource "rich" do
    url "https://files.pythonhosted.org/packages/source/r/rich/rich-13.9.4.tar.gz"
    sha256 "439594978a49a09530cff7ebc4b5c7103ef57baf48d5ea3184f21d9a2befa098"
  end

  resource "mcp" do
    url "https://files.pythonhosted.org/packages/source/m/mcp/mcp-1.6.0.tar.gz"
    sha256 "REPLACE_WITH_MCP_SHA256"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "memgit", shell_output("#{bin}/memgit --version")
    assert_match "Usage:", shell_output("#{bin}/memgit --help")
  end
end
