from __future__ import annotations

import pytest

from finance import create_app


def test_private_routes_and_api_require_login(app):
    client = app.test_client()
    assert client.get("/").status_code == 302
    response = client.get("/api/bootstrap")
    assert response.status_code == 401
    assert response.get_json()["error"] == "Требуется вход"


def test_login_rotates_session_and_csrf_protects_writes(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session["csrf_token"] = "login-token"
    response = client.post(
        "/login",
        data={"login": "sasha", "password": "correct-password", "csrf_token": "login-token"},
    )
    assert response.status_code == 302
    assert client.post("/api/categories", json={"name": "Тест", "type": "expense"}).status_code == 400
    with client.session_transaction() as session:
        csrf_token = session["csrf_token"]
    response = client.post(
        "/api/categories",
        headers={"X-CSRF-Token": csrf_token},
        json={"name": "Тест", "type": "expense"},
    )
    assert response.status_code == 201


def test_production_requires_secret_and_enables_secure_cookie(tmp_path):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app({
            "APP_ENV": "production",
            "SECRET_KEY": "local-finance-secret",
            "DATABASE": str(tmp_path / "invalid.db"),
            "TESTING": True,
        })

    app = create_app({
        "APP_ENV": "production",
        "SECRET_KEY": "x" * 64,
        "DATABASE": str(tmp_path / "production.db"),
        "SESSION_COOKIE_SECURE": True,
        "SEED_DEMO": False,
        "TESTING": True,
    })
    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_removed_automation_and_purchase_surfaces_are_unavailable(client):
    for path in (
        "/automation", "/purchases", "/api/category-rules", "/api/salary-plan",
        "/api/upcoming-payments", "/api/purchases",
    ):
        assert client.get(path).status_code == 404
    assert "allocation_plan" not in client.get("/api/summary?period=month").get_json()["data"]
