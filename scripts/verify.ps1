$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location "$root\services\api"
try {
  python -m pytest -q
  python -m ruff check app tests
} finally {
  Pop-Location
}

Push-Location "$root\apps\tv\Tower"
try {
  node --test *.test.cjs
  node --check app.js
  node --check room-bridge.js
  node --check oc-import-client.js
  node --check demo-server.cjs
} finally {
  Pop-Location
}

Push-Location "$root\apps\room"
try {
  node --test fallback-demo.test.cjs
  & npm.cmd ci
  & npm.cmd test -- --run
  & npm.cmd run typecheck:relay
  & npm.cmd run build:vps
} finally {
  Pop-Location
}

Push-Location "$root\hardware\orange-pi\gateway"
try {
  python -m pytest -q
} finally {
  Pop-Location
}

Write-Host "OOCC verification complete."
