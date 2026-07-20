import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "local-finance-secret")
    DATABASE = os.getenv("DATABASE_PATH", str(BASE_DIR / "instance" / "finance.db"))
    # Seed data is useful for a demo, but dangerous as the default for a real ledger.
    SEED_DEMO = os.getenv("SEED_DEMO", "0") == "1"
    TESTING = False
    LOGIN_DISABLED = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 14
