$ErrorActionPreference = 'Stop'

$pip = Get-Command pip3 -ErrorAction SilentlyContinue
if (-not $pip) { $pip = Get-Command pip -ErrorAction SilentlyContinue }
if ($pip) {
    & $pip.Source uninstall memgit -y
}
