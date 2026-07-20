#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install -r requirements.txt

echo
printf 'FinFlow is running at http://127.0.0.1:5000\nPress Ctrl+C to stop.\n\n'
python app.py
