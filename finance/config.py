import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
_APP_ENV = os.getenv("APP_ENV", "development").lower()
_PRIVATE_CONFIG_DIR = Path.home() / ".config" / "finflow"


def _private_value(filename: str) -> str:
    path = _PRIVATE_CONFIG_DIR / filename
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


class Config:
    APP_ENV = _APP_ENV
    SECRET_KEY = os.getenv("SECRET_KEY", "local-finance-secret")
    DATABASE = os.getenv("DATABASE_PATH", str(BASE_DIR / "instance" / "finance.db"))
    # Seed data is useful for a demo, but dangerous as the default for a real ledger.
    SEED_DEMO = os.getenv("SEED_DEMO", "0") == "1"
    TESTING = False
    LOGIN_DISABLED = False
    PROVERKACHEKA_TOKEN = os.getenv("PROVERKACHEKA_TOKEN", "").strip()
    VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "").strip() or _private_value("vapid_public_key")
    _VAPID_PRIVATE_FILE = _PRIVATE_CONFIG_DIR / "vapid_private.pem"
    VAPID_PRIVATE_KEY = (
        os.getenv("VAPID_PRIVATE_KEY", "").replace("\\n", "\n").strip()
        or (str(_VAPID_PRIVATE_FILE) if _VAPID_PRIVATE_FILE.is_file() else "")
    )
    VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "").strip() or _private_value("vapid_subject") or "mailto:admin@localhost"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = (
        os.getenv("SESSION_COOKIE_SECURE", "1" if _APP_ENV == "production" else "0") == "1"
    )
    PREFERRED_URL_SCHEME = "https" if _APP_ENV == "production" else "http"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 14
