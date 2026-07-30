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
    assert client.delete(f"/api/recurring-transactions/{rule_id}", headers=csrf_headers).status_code == 200
    assert client.get("/api/recurring-transactions").get_json()["data"] == []


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


def test_income_paid_directly_to_investment_is_counted_as_invested(client, csrf_headers):
    data = bootstrap(client)
    investment = next(account for account in data["accounts"] if account["account_type"] == "investment")
    income_category = next(category for category in data["categories"] if category["type"] == "income")
    response = client.post(
        "/api/transactions",
        headers=csrf_headers,
        json={
            "tx_type": "income",
            "amount": 14_500.75,
            "tx_date": date.today().isoformat(),
            "category_id": income_category["id"],
            "account_id": investment["id"],
        },
    )
    assert response.status_code == 201

    summary = client.get(f"/api/summary?period=month&anchor={date.today().isoformat()}").get_json()["data"]
    assert summary["current"]["income"] == 14_500.75
    assert summary["current"]["invested"] == 14_500.75
    assert summary["current"]["saved"] == 14_500.75


def test_invested_metric_and_history_use_net_investment_and_currency_flows(client, csrf_headers):
    data = bootstrap(client)
    checking = next(account for account in data["accounts"] if account["account_type"] == "checking")
    investment = next(account for account in data["accounts"] if account["account_type"] == "investment")
    currency_response = client.post(
        "/api/accounts",
        headers=csrf_headers,
        json={"name": "Евро", "account_type": "currency", "currency_code": "EUR", "exchange_rate": 100},
    )
    currency_id = currency_response.get_json()["data"]["id"]

    transfers = [
        {"amount": 1_000, "account_id": checking["id"], "target_account_id": investment["id"]},
        {"amount": 250, "account_id": investment["id"], "target_account_id": checking["id"]},
        {"amount": 1_000, "target_amount": 10, "account_id": checking["id"], "target_account_id": currency_id},
        {"amount": 4, "target_amount": 400, "account_id": currency_id, "target_account_id": checking["id"]},
    ]
    for transfer in transfers:
        response = client.post(
            "/api/transactions", headers=csrf_headers, json={"tx_type": "transfer", **transfer}
        )
        assert response.status_code == 201

    summary = client.get(f"/api/summary?period=month&anchor={date.today().isoformat()}").get_json()["data"]
    assert summary["current"]["invested"] == 1_350
    history = client.get("/api/investment-balance-history").get_json()["data"]
    assert history[-1]["invested"] == 1_350
