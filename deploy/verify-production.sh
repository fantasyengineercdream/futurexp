#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${OOCC_BASE_URL:-https://oc-voice.open.smn.icu}"
EXPECTED_BUILD="BUILD 2026.07.25.13"

curl -fsS "$BASE_URL/" >/dev/null
curl -fsS "$BASE_URL/room/" >/dev/null
curl -fsS "$BASE_URL/fallback-demo/" >/dev/null
curl -fsS "$BASE_URL/api/health" | grep -F '"status":"ok"' >/dev/null

room_html="$(curl -fsS "$BASE_URL/room/")"
room_asset="$(printf '%s' "$room_html" | sed -n 's/.*src="\([^\"]*\.js\)".*/\1/p' | head -n 1)"
if [[ -z "$room_asset" ]]; then
  echo "Room entry did not expose a JavaScript asset" >&2
  exit 1
fi

case "$room_asset" in
  http://*|https://*) asset_url="$room_asset" ;;
  /*) asset_url="$BASE_URL$room_asset" ;;
  *) asset_url="$BASE_URL/room/$room_asset" ;;
esac

if ! curl -fsS "$asset_url" | grep -F "$EXPECTED_BUILD" >/dev/null; then
  echo "Room build mismatch: expected $EXPECTED_BUILD at $asset_url" >&2
  exit 1
fi
echo "OOCC production verified: $EXPECTED_BUILD"
