from __future__ import annotations

from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

from finance import create_app
from finance.db import get_db


@pytest.fixture
def app(tmp_path: Path):
    application = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "test-finflow.db"),
        "SEED_DEMO": False,
    })
    with application.app_context():
        db = get_db()
        person_id = db.execute("SELECT id FROM people WHERE name = 'Саша'").fetchone()["id"]
        db.execute(
            "INSERT INTO users(login, password_hash, person_id, is_admin) VALUES (?, ?, ?, 1)",
            ("sasha", generate_password_hash("correct-password"), person_id),
        )
        db.commit()
    return application


@pytest.fixture
def client(app):
    test_client = app.test_client()
    with test_client.session_transaction() as session:
        session["user_id"] = 1
        session["csrf_token"] = "test-csrf-token"
    return test_client


@pytest.fixture
def csrf_headers():
    return {"X-CSRF-Token": "test-csrf-token"}
