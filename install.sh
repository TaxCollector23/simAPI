#!/bin/sh
# SimAPI CLI installer (macOS / Linux)
#   curl -fsSL https://simapilander.vercel.app/install.sh | sh
set -e

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  printf 'Node.js 18+ (with npm) is required. Install it from https://nodejs.org, then re-run this installer.\n' >&2
  exit 1
fi
NODE_MAJOR=$(node -p 'Number(process.versions.node.split(".")[0])' 2>/dev/null || echo 0)
if [ "$NODE_MAJOR" -lt 18 ]; then
  printf 'Node.js 18+ is required; found %s. Upgrade Node.js, then re-run this installer.\n' "$(node -v)" >&2
  exit 1
fi

printf 'Installing SimAPI CLI from npm…\n'
npm install --global simapi-cli@latest
printf '\nInstalled. Start with: simapi\nSee all commands with: simapi --help\n'
