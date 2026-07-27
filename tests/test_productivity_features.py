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


def test_default_categories_and_spending_statistics(client, csrf_headers):
    data = bootstrap(client)
    expense_categories = {item["name"]: item for item in data["categories"] if item["type"] == "expense"}
    assert {"Автомобиль", "Питомцы", "Налоги и комиссии", "Страхование"} <= expense_categories.keys()
    account = next(item for item in data["accounts"] if item["kind"] == "life")
    category = expense_categories["Автомобиль"]

    for amount in (100, 300):
        response = client.post(
            "/api/transactions",
            headers=csrf_headers,
            json={
                "tx_type": "expense",
                "amount": amount,
                "tx_date": date.today().isoformat(),
                "category_id": category["id"],
                "account_id": account["id"],
            },
        )
        assert response.status_code == 201

    summary = client.get(f"/api/summary?period=month&anchor={date.today().isoformat()}").get_json()["data"]
    stats = summary["spending_stats"]
    assert stats["total"] == 400
    assert stats["average_per_day"] == round(400 / date.today().day, 2)
    assert stats["average_transaction"] == 200
    assert stats["transaction_count"] == 2
    assert stats["active_days"] == 1
    assert stats["largest"]["amount"] == 300
    assert stats["largest"]["category_name"] == "Автомобиль"


def test_income_allocation_plan_uses_savings_and_currency_accounts(client, csrf_headers):
    data = bootstrap(client)
    people = data["people"]
    checking = next(account for account in data["accounts"] if account["account_type"] == "checking")
    income_category = next(category for category in data["categories"] if category["type"] == "income")

    settings_response = client.put(
        "/api/settings",
        headers=csrf_headers,
        json={
            "investment_target_percent": 20,
            "currency_target_percent": 10,
            "monthly_life_budget": 90_000,
            "currency": "$",
        },
    )
    assert settings_response.status_code == 200
    assert bootstrap(client)["settings"]["currency"] == "$"

    created_accounts = {}
    for account_type, name, rate in (
        ("savings", "Подушка", 12),
        ("currency", "Валютный резерв", 0),
    ):
        response = client.post(
            "/api/accounts",
            headers=csrf_headers,
            json={"name": name, "account_type": account_type, "annual_rate": rate},
        )
        assert response.status_code == 201
        created_accounts[account_type] = response.get_json()["data"]["id"]

    for amount, person in zip((100_000, 80_000), people, strict=True):
        response = client.post(
            "/api/transactions",
            headers=csrf_headers,
            json={
                "tx_type": "income",
                "amount": amount,
                "tx_date": date.today().isoformat(),
                "category_id": income_category["id"],
                "person_id": person["id"],
                "account_id": checking["id"],
            },
        )
        assert response.status_code == 201

    for amount, target in ((20_000, "savings"), (5_000, "currency")):
        response = client.post(
            "/api/transactions",
            headers=csrf_headers,
            json={
                "tx_type": "transfer",
                "amount": amount,
                "tx_date": date.today().isoformat(),
                "account_id": checking["id"],
                "target_account_id": created_accounts[target],
            },
        )
        assert response.status_code == 201

    summary = client.get(f"/api/summary?period=month&anchor={date.today().isoformat()}").get_json()["data"]
    plan = {bucket["key"]: bucket for bucket in summary["allocation_plan"]["buckets"]}
    assert summary["current"]["income"] == 180_000
    assert summary["current"]["saved"] == 20_000
    assert summary["current"]["currency_reserved"] == 5_000
    assert plan["spending"]["planned"] == 90_000
    assert plan["savings"]["planned"] == 72_000
    assert plan["savings"]["remaining"] == 52_000
    assert plan["currency"]["planned"] == 18_000
    assert plan["currency"]["remaining"] == 13_000
    assert plan["savings"]["destination"] == "Подушка"
    assert plan["currency"]["destination"] == "Валютный резерв"
