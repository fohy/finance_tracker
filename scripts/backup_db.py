"""Create a consistent SQLite backup without stopping the web application."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = Path(os.getenv("DATABASE_PATH", ROOT / "instance" / "finance.db"))
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", ROOT / "backups"))
KEEP_BACKUPS = 14


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"Database does not exist: {SOURCE}")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    destination = BACKUP_DIR / f"finance-{datetime.now():%Y%m%d-%H%M%S}.db"
    with sqlite3.connect(SOURCE) as source, sqlite3.connect(destination) as backup:
        source.backup(backup)
    backups = sorted(BACKUP_DIR.glob("finance-*.db"), reverse=True)
    for obsolete in backups[KEEP_BACKUPS:]:
        obsolete.unlink()
    print(destination)


if __name__ == "__main__":
    main()
