import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "local-finance-secret")
    DATABASE = os.getenv("DATABASE_PATH", str(BASE_DIR / "instance" / "finance.db"))
    # Seed data is useful for a demo, but dangerous as the default for a real ledger.
    SEED_DEMO = os.getenv("SEED_DEMO", "0") == "1"
    TESTING = False
