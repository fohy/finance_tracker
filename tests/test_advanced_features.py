from __future__ import annotations

from io import BytesIO


def _expense_payload(client, amount: float = 500) -> dict:
    data = client.get("/api/bootstrap").get_json()["data"]
    account = next(item for item in data["accounts"] if item["account_type"] == "checking")
    category = next(item for item in data["categories"] if item["type"] == "expense")
    return {
        "tx_type": "expense",
        "amount": amount,
        "tx_date": data["today"],
        "account_id": account["id"],
        "category_id": category["id"],
        "note": "Тестовый расход",
    }


def test_projects_and_transaction_history(client, csrf_headers):
    response = client.post(
        "/api/projects", headers=csrf_headers,
        json={"name": "Ремонт", "color": "#86aa9a", "icon": "repair"},
    )
    assert response.status_code == 201
    project_id = response.get_json()["data"]["id"]

    payload = _expense_payload(client)
    payload["project_id"] = project_id
    response = client.post("/api/transactions", headers=csrf_headers, json=payload)
    assert response.status_code == 201
    tx_id = response.get_json()["data"]["id"]

    projects = client.get("/api/projects").get_json()["data"]
    project = next(item for item in projects if item["id"] == project_id)
    assert project["spent"] == 500
    assert project["transaction_count"] == 1

    response = client.patch(
        f"/api/transactions/{tx_id}", headers=csrf_headers, json={"amount": 650}
    )
    assert response.status_code == 200
    history = client.get(f"/api/transactions/{tx_id}/history").get_json()["data"]
    assert [item["action"] for item in history[:2]] == ["updated", "created"]
    assert history[0]["details"]["before"]["amount"] == 500
    assert history[0]["details"]["after"]["amount"] == 650


def test_encrypted_backup_restore_and_wrong_password(client, csrf_headers):
    first = _expense_payload(client, 100)
    assert client.post("/api/transactions", headers=csrf_headers, json=first).status_code == 201
    password = "correct horse battery staple"
    response = client.post(
        "/api/backups/export", headers=csrf_headers, json={"password": password}
    )
    assert response.status_code == 200
    encrypted = response.data
    assert encrypted.startswith(b"FINFLOW-BACKUP\x01")

    second = _expense_payload(client, 200)
    assert client.post("/api/transactions", headers=csrf_headers, json=second).status_code == 201

    wrong = client.post(
        "/api/backups/restore", headers=csrf_headers,
        data={"password": "wrong password value", "backup": (BytesIO(encrypted), "backup.ffbackup")},
        content_type="multipart/form-data",
    )
    assert wrong.status_code == 400

    restored = client.post(
        "/api/backups/restore", headers=csrf_headers,
        data={"password": password, "backup": (BytesIO(encrypted), "backup.ffbackup")},
        content_type="multipart/form-data",
    )
    assert restored.status_code == 200
    transactions = client.get("/api/transactions?period=month&per_page=100").get_json()["data"]
    amounts = [item["amount"] for item in transactions["items"]]
    assert 100 in amounts
    assert 200 not in amounts


def test_push_config_reports_missing_server_keys(client):
    response = client.get("/api/push/config")
    assert response.status_code == 200
    assert response.get_json()["data"] == {
        "configured": False, "public_key": "", "subscribed": False,
    }


def test_transaction_push_contains_person_and_purpose(app, client, csrf_headers, monkeypatch):
    payload = _expense_payload(client, 2390)
    response = client.post("/api/transactions", headers=csrf_headers, json=payload)
    transaction_id = response.get_json()["data"]["id"]
    captured = []

    with app.app_context():
        app.config.update(VAPID_PUBLIC_KEY="public", VAPID_PRIVATE_KEY="private")
        monkeypatch.setattr("finance.push_service._send_events", lambda events: captured.extend(events) or {
            "sent": 1, "skipped": 0, "removed": 0, "errors": 0,
        })
        from finance.push_service import notify_transaction_created

        notify_transaction_created(transaction_id, 1)

    assert "Расход 2 390,00" in captured[0]["title"]
    assert "Тестовый расход" in captured[0]["body"]
    assert captured[0]["url"] == "/transactions"
