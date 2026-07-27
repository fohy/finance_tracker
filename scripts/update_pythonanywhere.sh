#!/usr/bin/env bash
set -euo pipefail

PROJECT_HOME="${PROJECT_HOME:-$HOME/finance_tracker}"
cd "$PROJECT_HOME"

if [[ -x .venv/bin/python && -f instance/finance.db ]]; then
    .venv/bin/python scripts/backup_db.py
fi

git pull --ff-only origin main
.venv/bin/pip install --disable-pip-version-check -r requirements.txt

TOKEN="${PA_API_TOKEN:-${API_TOKEN:-}}"
USERNAME="${PA_USERNAME:-$USER}"
DOMAIN="${PA_DOMAIN:-$USERNAME.pythonanywhere.com}"
API_BASE="${PA_API_BASE:-https://www.pythonanywhere.com}"

if [[ -n "$TOKEN" ]]; then
    curl --fail --silent --show-error \
        -X POST \
        -H "Authorization: Token $TOKEN" \
        "$API_BASE/api/v0/user/$USERNAME/webapps/$DOMAIN/reload/"
    echo "FinFlow updated and reloaded: https://$DOMAIN"
else
    echo "Code updated. Create an API token or click Reload on the PythonAnywhere Web tab."
fi
