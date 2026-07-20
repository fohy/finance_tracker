from __future__ import annotations

from datetime import date


def bootstrap(client):
    return client.get("/api/bootstrap").get_json()["data"]


def test_category_budget_and_csv_export(client, csrf_headers):
    data = bootstrap(client)
    category = next(item for item in data["categories"] if item["type"] == "expense")
    response = client.put(
        f"/api/budgets/{category['id']}", headers=csrf_headers, json={"monthly_limit": 5000}
    )
    assert response.status_code == 200
    budgets = client.get("/api/budgets").get_json()["data"]
    assert budgets[0]["category_id"] == category["id"]
    exported = client.get("/api/transactions/export.csv")
    assert exported.status_code == 200
    assert exported.mimetype == "text/csv"
    assert "Дата" in exported.get_data(as_text=True)


def test_recurring_rule_applies_once_and_moves_next_date(client, csrf_headers):
    data = bootstrap(client)
    account = next(item for item in data["accounts"] if item["kind"] == "life")
    category = next(item for item in data["categories"] if item["type"] == "expense")
    response = client.post(
        "/api/recurring-transactions",
        headers=csrf_headers,
        json={
            "title": "Тестовая подписка", "tx_type": "expense", "amount": 100,
            "frequency": "monthly", "next_date": date.today().isoformat(),
            "category_id": category["id"], "account_id": account["id"],
        },
    )
    rule_id = response.get_json()["data"]["id"]
    assert client.post(f"/api/recurring-transactions/{rule_id}/apply", headers=csrf_headers).status_code == 200
    rule = client.get("/api/recurring-transactions").get_json()["data"][0]
    assert rule["next_date"] > date.today().isoformat()
