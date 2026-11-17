#!/bin/bash
# LOCAL TESTING ONLY. Starts the static site on :8080 and the API on :8000
# against a local PostgreSQL database named imx_local.
set -e
cd "$(dirname "$0")/.."
export DATABASE_URL="${DATABASE_URL:-postgresql://localhost/imx_local}"
export FRONTEND_URL="http://localhost:8080"
export ALLOW_LOCAL_IMPORTS=1          # lets the importer read the fixtures from http://127.0.0.1:8080
export STAFF_BOOTSTRAP_USERNAME="${STAFF_BOOTSTRAP_USERNAME:-staff.local}"
export STAFF_BOOTSTRAP_PASSWORD="${STAFF_BOOTSTRAP_PASSWORD:-Local-Only-Pass-2026}"
export STAFF_BOOTSTRAP_NAME="Local Staff"
export GITHUB_CLIENT_ID="${GITHUB_CLIENT_ID:-local}" GITHUB_CLIENT_SECRET="${GITHUB_CLIENT_SECRET:-local}"
python3 -m http.server 8080 --bind 127.0.0.1 >/tmp/imx-web.log 2>&1 &
WEB=$!; trap 'kill $WEB' EXIT
echo "Site:  http://localhost:8080/index.html   Staff: http://localhost:8080/admin.html"
echo "Staff sign-in (local only): $STAFF_BOOTSTRAP_USERNAME / $STAFF_BOOTSTRAP_PASSWORD"
python3 -m uvicorn main:app --port 8000
