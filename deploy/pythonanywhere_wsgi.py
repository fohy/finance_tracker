"""WSGI entrypoint for PythonAnywhere.

Copy this file's contents into the WSGI configuration shown on the Web tab.
The secret is read from a private file outside the Git repository.
"""

import os
import sys
from pathlib import Path

HOME = Path.home()
PROJECT_HOME = HOME / "finance_tracker"
SECRET_FILE = HOME / ".config" / "finflow" / "secret_key"

if not SECRET_FILE.is_file():
    raise RuntimeError(f"Create the private secret file first: {SECRET_FILE}")

secret_key = SECRET_FILE.read_text(encoding="utf-8").strip()
if len(secret_key) < 32:
    raise RuntimeError("The private SECRET_KEY must contain at least 32 characters")

sys.path.insert(0, str(PROJECT_HOME))
os.environ["APP_ENV"] = "production"
os.environ["SECRET_KEY"] = secret_key
os.environ["DATABASE_PATH"] = str(PROJECT_HOME / "instance" / "finance.db")
os.environ["SEED_DEMO"] = "0"
os.environ["SESSION_COOKIE_SECURE"] = "1"

from app import app as application  # noqa: E402,F401
