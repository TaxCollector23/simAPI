# SimAPI CLI installer (Windows PowerShell)
#   irm https://simapilander.vercel.app/install.ps1 | iex
$ErrorActionPreference = "Stop"

Write-Host "Installing SimAPI CLI from npm..."

if (-not (Get-Command node -ErrorAction SilentlyContinue) -or -not (Get-Command npm -ErrorAction SilentlyContinue)) {
  Write-Error "Node.js 18+ (with npm) is required. Install it from https://nodejs.org, then re-run this installer."
  exit 1
}

try {
  $nodeVersion = [Version](node -p "process.versions.node")
} catch {
  Write-Error "Could not read the installed Node.js version. Install Node.js 18+ and try again."
  exit 1
}
if ($nodeVersion.Major -lt 18) {
  Write-Error "Node.js 18+ is required; found $nodeVersion. Upgrade Node.js, then re-run this installer."
  exit 1
}

npm install --global simapi-cli@latest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`nInstalled. Start with: simapi"
Write-Host "See all commands with: simapi --help`n"
