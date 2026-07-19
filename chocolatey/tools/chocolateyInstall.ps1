$ErrorActionPreference = 'Stop'

# Install memgit via pip
$pipArgs = @('install', 'memgit==0.7.0', '--upgrade')

# Try pip3 first, then pip
$pip = Get-Command pip3 -ErrorAction SilentlyContinue
if (-not $pip) {
    $pip = Get-Command pip -ErrorAction SilentlyContinue
}
if (-not $pip) {
    throw "Python pip not found. Install Python first: https://www.python.org/downloads/"
}

Write-Host "Installing memgit via pip..."
& $pip.Source $pipArgs

# Verify install
$memgit = Get-Command memgit -ErrorAction SilentlyContinue
if ($memgit) {
    Write-Host "memgit installed successfully at: $($memgit.Source)"
    Write-Host ""
    Write-Host "Quick start:"
    Write-Host "  memgit init"
    Write-Host "  memgit setup all"
} else {
    # pip installs to Scripts\ which may not be in PATH yet
    Write-Warning "memgit was installed but may not be in PATH yet."
    Write-Warning "Restart your terminal or add Python Scripts to PATH."
}
