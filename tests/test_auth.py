from __future__ import annotations


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
