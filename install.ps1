# codedict installer for Windows. Run in PowerShell:
#   irm https://raw.githubusercontent.com/Marqueos/codedict/main/install.ps1 | iex
# Installs into its own folder (no admin, no PATH changes) and turns codedict on in Claude Code.
# Run it again to update. Uninstall: & "$HOME\.codedict\venv\Scripts\python.exe" -m codedict setup --remove
# Optional env vars: CODEDICT_REPO (pip source), CODEDICT_HOME (install folder), CODEDICT_SETTINGS (settings.json).
$ErrorActionPreference = "Stop"
$repo = if ($env:CODEDICT_REPO) { $env:CODEDICT_REPO } else { "git+https://github.com/Marqueos/codedict" }
$home_ = if ($env:CODEDICT_HOME) { $env:CODEDICT_HOME } else { Join-Path $HOME ".codedict" }
$venv = Join-Path $home_ "venv"
$py = Join-Path $venv "Scripts\python.exe"

$exe = $null
foreach ($c in "py -3", "python", "python3") {
    $parts = $c -split " "
    if (-not (Get-Command $parts[0] -ErrorAction SilentlyContinue)) { continue }
    $pre = @($parts | Select-Object -Skip 1)  # array, so "-3" is passed as one argument
    & $parts[0] @pre -c "import sys; sys.exit(sys.version_info < (3, 11))" 2>$null
    if ($LASTEXITCODE -eq 0) { $exe = $parts[0]; break }
}
if (-not $exe) { throw "Python 3.11+ not found. Install it from https://www.python.org/downloads/ and run this again." }

if (-not (Test-Path $py)) { & $exe @pre -m venv $venv; if ($LASTEXITCODE) { throw "could not create $venv" } }
& $py -m pip install --upgrade --quiet --disable-pip-version-check $repo
if ($LASTEXITCODE) { throw "pip install failed (see the error above)" }

$setup = @("-m", "codedict", "setup")
if ($env:CODEDICT_SETTINGS) { $setup += @("--settings", $env:CODEDICT_SETTINGS) }
& $py @setup
if ($LASTEXITCODE) { throw "codedict setup failed (see the error above)" }

Write-Host ""
Write-Host "Done. Open Claude Code in any git project: it indexes itself and answers code questions from the index."
Write-Host "Command line: $(Join-Path $venv 'Scripts\codedict.exe')"
