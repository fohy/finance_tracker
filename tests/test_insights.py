from __future__ import annotations

from finance.db import get_db


def bootstrap(client):
    response = client.get("/api/bootstrap")
    assert response.status_code == 200
    return response.get_json()["data"]


def test_insights_page_renders_for_authenticated_user(client):
    response = client.get("/insights")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Аналитика" in html
    assert 'id="trendChart"' in html
    assert 'id="periodComparison"' in html
    assert 'id="capitalHistory"' in html
    assert 'id="categoryDonut"' in html
    assert 'src="/static/js/app.js?' in html


def test_pwa_assets_and_service_worker_headers(client):
    manifest = client.get("/static/manifest.webmanifest")
    assert manifest.status_code == 200
    payload = manifest.get_json()
    assert payload["display"] == "standalone"
    assert payload["start_url"] == "/"
    assert {icon["sizes"] for icon in payload["icons"]} >= {"192x192", "512x512"}
    worker = client.get("/service-worker.js")
    assert worker.status_code == 200
    assert worker.mimetype == "application/javascript"
    assert worker.headers["Service-Worker-Allowed"] == "/"
    assert worker.headers["Cache-Control"] == "no-cache, no-store, must-revalidate"


def test_currency_transfer_reversal_valuation_and_linked_goal(client, csrf_headers):
    data = bootstrap(client)
    checking = next(item for item in data["accounts"] if item["account_type"] == "checking")
    created = client.post(
        "/api/accounts", headers=csrf_headers,
        json={"name": "Евро", "account_type": "currency", "currency_code": "EUR", "exchange_rate": 100},
    )
    currency_id = created.get_json()["data"]["id"]
    transfer = client.post(
        "/api/transactions", headers=csrf_headers,
        json={
            "tx_type": "transfer", "amount": 1_000, "target_amount": 10,
            "account_id": checking["id"], "target_account_id": currency_id,
        },
    )
    assert transfer.status_code == 201
    transaction_id = transfer.get_json()["data"]["id"]
    account = next(item for item in client.get("/api/accounts").get_json()["data"] if item["id"] == currency_id)
    assert account["balance"] == 10
    assert account["base_equivalent"] == 1_000
    summary = client.get("/api/summary?period=month").get_json()["data"]
    assert summary["currency_balance"] == 1_000
    assert summary["invested_balance"] == 1_000
    assert summary["total_capital"] == 0
    goal = client.post(
        "/api/goals", headers=csrf_headers,
        json={"title": "Резерв в евро", "target_amount": 5_000, "account_id": currency_id},
    )
    linked = next(
        item for item in client.get("/api/goals").get_json()["data"]
        if item["id"] == goal.get_json()["data"]["id"]
    )
    assert linked["current_amount"] == 1_000
    assert linked["account_name"] == "Евро"
    assert client.delete(f"/api/transactions/{transaction_id}", headers=csrf_headers).status_code == 200


def test_insights_scenario_and_weekly_report_endpoints(client, csrf_headers):
    insights = client.get("/api/insights")
    assert insights.status_code == 200
    assert {"amount", "monthly_burn", "runway_months", "gap_3", "gap_6"} <= (
        insights.get_json()["data"]["cushion"].keys()
    )
    scenario = client.post(
        "/api/insights/what-if", headers=csrf_headers,
        json={
            "income": 120_000, "expense": 70_000, "savings_percent": 20,
            "currency_percent": 10, "savings_rate": 6, "currency_rate": 2,
            "horizon_months": 24,
        },
    )
    assert scenario.status_code == 200
    assert scenario.get_json()["data"]["allocation"]["savings"] == 24_000
    report = client.get("/api/weekly-report")
    assert report.status_code == 200
    assert len(report.get_json()["data"]["actions"]) == 3


def test_capital_history_keeps_plain_transfer_neutral(client, csrf_headers):
    data = bootstrap(client)
    checking = next(item for item in data["accounts"] if item["account_type"] == "checking")
    savings = client.post(
        "/api/accounts", headers=csrf_headers,
        json={"name": "Резерв", "account_type": "savings"},
    ).get_json()["data"]["id"]
    assert client.post(
        "/api/transactions", headers=csrf_headers,
        json={
            "tx_type": "income", "amount": 2_000, "tx_date": "2026-01-10", "account_id": checking["id"],
            "category_id": next(item["id"] for item in data["categories"] if item["type"] == "income"),
        },
    ).status_code == 201
    assert client.post(
        "/api/transactions", headers=csrf_headers,
        json={
            "tx_type": "transfer", "amount": 750, "tx_date": "2026-01-11",
            "account_id": checking["id"], "target_account_id": savings,
        },
    ).status_code == 201
    history = client.get("/api/capital-history").get_json()["data"]
    by_date = {item["label"]: item["capital"] for item in history}
    assert by_date["2026-01-10"] == 2_000
    assert by_date["2026-01-11"] == 2_000


def test_capital_history_values_currency_transfer_in_base_currency(client, csrf_headers):
    data = bootstrap(client)
    checking = next(item for item in data["accounts"] if item["account_type"] == "checking")
    currency = client.post(
        "/api/accounts", headers=csrf_headers,
        json={"name": "Евро-резерв", "account_type": "currency", "currency_code": "EUR", "exchange_rate": 100},
    ).get_json()["data"]["id"]
    assert client.post(
        "/api/transactions", headers=csrf_headers,
        json={
            "tx_type": "income", "amount": 1_000, "tx_date": "2026-02-10", "account_id": checking["id"],
            "category_id": next(item["id"] for item in data["categories"] if item["type"] == "income"),
        },
    ).status_code == 201
    assert client.post(
        "/api/transactions", headers=csrf_headers,
        json={
            "tx_type": "transfer", "amount": 1_000, "target_amount": 9, "tx_date": "2026-02-11",
            "account_id": checking["id"], "target_account_id": currency,
        },
    ).status_code == 201
    history = client.get("/api/capital-history").get_json()["data"]
    by_date = {item["label"]: item["capital"] for item in history}
    assert by_date["2026-02-10"] == 1_000
    assert by_date["2026-02-11"] == 900


def test_category_learning_uses_consistent_corrected_history(client, app, csrf_headers):
    data = bootstrap(client)
    account = next(item for item in data["accounts"] if item["account_type"] == "checking")
    category = next(item for item in data["categories"] if item["name"] == "Продукты")
    for order in (101, 202, 303):
        response = client.post(
            "/api/transactions", headers=csrf_headers,
            json={
                "tx_type": "expense", "amount": 500, "account_id": account["id"],
                "category_id": category["id"], "note": f"Яндекс Лавка заказ {order}",
            },
        )
        assert response.status_code == 201
    learned = client.post(
        "/api/transactions", headers=csrf_headers,
        json={
            "tx_type": "expense", "amount": 700, "account_id": account["id"],
            "note": "Яндекс Лавка заказ 404",
        },
    )
    with app.app_context():
        row = get_db().execute(
            "SELECT category_id FROM transactions WHERE id = ?", (learned.get_json()["data"]["id"],)
        ).fetchone()
        assert row["category_id"] == category["id"]
