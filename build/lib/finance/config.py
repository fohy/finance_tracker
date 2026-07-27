import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
_APP_ENV = os.getenv("APP_ENV", "development").lower()


class Config:
    APP_ENV = _APP_ENV
    SECRET_KEY = os.getenv("SECRET_KEY", "local-finance-secret")
    DATABASE = os.getenv("DATABASE_PATH", str(BASE_DIR / "instance" / "finance.db"))
    # Seed data is useful for a demo, but dangerous as the default for a real ledger.
    SEED_DEMO = os.getenv("SEED_DEMO", "0") == "1"
    TESTING = False
    LOGIN_DISABLED = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = (
        os.getenv("SESSION_COOKIE_SECURE", "1" if _APP_ENV == "production" else "0") == "1"
    )
    PREFERRED_URL_SCHEME = "https" if _APP_ENV == "production" else "http"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 14
