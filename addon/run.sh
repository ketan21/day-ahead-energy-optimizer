#!/usr/bin/env bash
set -euo pipefail

export DAEO_DATA_DIR="${DAEO_DATA_DIR:-/data}"
export DAEO_HOST="${DAEO_HOST:-0.0.0.0}"
export DAEO_PORT="${DAEO_PORT:-8099}"

# The add-on options are stored in /data/options.json by the Supervisor.
if [ -f /data/options.json ]; then
    DEMO_MODE="$(python - <<'PY'
import json
try:
    with open("/data/options.json", encoding="utf-8") as handle:
        print("1" if json.load(handle).get("demo_mode", False) else "0")
except Exception:
    print("0")
PY
)"
    export DAEO_DEMO="${DEMO_MODE}"
else
    export DAEO_DEMO="${DAEO_DEMO:-0}"
fi

# The integration needs a stable token. The add-on log prints it once so the
# pairing flow can copy it even when the web UI is not open.
if [ "${DAEO_DEMO}" = "0" ]; then
    mkdir -p "$DAEO_DATA_DIR"
    TOKEN_FILE="$DAEO_DATA_DIR/api_token"
    if [ ! -s "$TOKEN_FILE" ]; then
        python -c 'import secrets; print(secrets.token_urlsafe(32))' > "$TOKEN_FILE"
        chmod 600 "$TOKEN_FILE"
    fi
    export DAEO_API_TOKEN="$(cat "$TOKEN_FILE")"
    echo "DAO API token: ${DAEO_API_TOKEN}"
fi

exec python -m daeo
