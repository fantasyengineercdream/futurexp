# KaleidoRoom demo API

This service is a local-only hackathon demo for the “无限公寓” runtime.

## Install

From the repository root, install the API and its test dependencies:

```powershell
python -m pip install -e ".\services\api[test]"
Set-Location .\services\api
```

Python 3.11 or newer is required.

## Run locally

Use a separate SQLite file for each demo run:

```powershell
$demoDb = Join-Path $env:TEMP (
  "kaleidoroom-runtime-" + [guid]::NewGuid().ToString("N") + ".sqlite3"
)
$env:KALEIDOROOM_DB_PATH = $demoDb
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Keep the service on `127.0.0.1`. The owner and proof endpoints intentionally
have no production authentication and are suitable only for a trusted local
demo environment. **不得暴露公网**。

If `KALEIDOROOM_DB_PATH` is not set, the API uses
`$env:TEMP\kaleidoroom-runtime.sqlite3`. That default file persists across
process restarts, so an explicit per-run path is recommended for a clean demo.

## Stop and clean up

Press `Ctrl+C` in the API terminal and wait for uvicorn to finish. Then remove
the per-run database and clear the environment variable:

```powershell
Remove-Item -LiteralPath $demoDb -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath "$demoDb-wal" -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath "$demoDb-shm" -Force -ErrorAction SilentlyContinue
Remove-Item Env:KALEIDOROOM_DB_PATH -ErrorAction SilentlyContinue
```

## Verify

From `services/api`:

```powershell
python -m pytest -q
python -m ruff check app tests
python -m compileall -q app
```
