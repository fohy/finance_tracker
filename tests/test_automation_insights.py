from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from finance.db import get_db
from finance.import_service import parse_statement


def bootstrap(client):
    response = client.get("/api/bootstrap")
    assert response.status_code == 200
    return response.get_json()["data"]


def test_new_pages_render_for_authenticated_user(client):
    for path in ("/automation", "/insights"):
        response = client.get(path)
        assert response.status_code == 200
        assert 'src="/static/js/app.js?' in response.get_data(as_text=True)


def test_basic_xlsx_first_sheet_parser():
    output = BytesIO()
    worksheet = """<?xml version="1.0" encoding="UTF-8"?>
    <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
      <row r="1"><c r="A1" t="inlineStr"><is><t>Дата</t></is></c><c r="B1" t="inlineStr"><is><t>Сумма</t></is></c><c r="C1" t="inlineStr"><is><t>Описание</t></is></c></row>
      <row r="2"><c r="A2" t="inlineStr"><is><t>2026-07-15</t></is></c><c r="B2"><v>-1250.5</v></c><c r="C2" t="inlineStr"><is><t>Магазин</t></is></c></row>
    </sheetData></worksheet>"""
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
    parsed = parse_statement("statement.xlsx", output.getvalue())
    assert parsed["rows"][0] == {
        "row_number": 2, "tx_date": "2026-07-15", "tx_type": "expense",
        "amount": 1250.5, "note": "Магазин", "category": "",
    }


def test_csv_preview_dedupe_and_category_rule(client, app, csrf_headers):
    data = bootstrap(client)
    account = next(item for item in data["accounts"] if item["account_type"] == "checking")
    person = data["people"][0]
    category = next(item for item in data["categories"] if item["type"] == "expense")
    rule = client.post(
        "/api/category-rules", headers=csrf_headers,
        json={"pattern": "кофейня", "category_id": category["id"], "priority": 10},
    )
    assert rule.status_code == 201
    csv_data = "Дата;Сумма;Описание\n15.07.2026;-450,50;Кофейня у дома\n".encode()

    def upload(path):
        return client.post(
            path, headers=csrf_headers,
            data={
                "account_id": str(account["id"]), "person_id": str(person["id"]),
                "file": (BytesIO(csv_data), "statement.csv"),
            },
            content_type="multipart/form-data",
        )

    preview = upload("/api/imports/preview")
    assert preview.status_code == 200
    assert preview.get_json()["data"]["items"][0]["duplicate"] is False
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0

    first = upload("/api/imports/confirm")
    assert first.status_code == 201
    assert first.get_json()["data"]["imported"] == 1
    second = upload("/api/imports/confirm")
    assert second.status_code == 201
    assert second.get_json()["data"]["imported"] == 0
    assert second.get_json()["data"]["duplicates"] == 1
    with app.app_context():
        row = get_db().execute("SELECT category_id, note FROM transactions").fetchone()
        assert row["category_id"] == category["id"]
        assert row["note"] == "Кофейня у дома"


def test_salary_plan_apply_is_idempotent(client, csrf_headers):
    data = bootstrap(client)
    checking = next(item for item in data["accounts"] if item["account_type"] == "checking")
    income_category = next(item for item in data["categories"] if item["type"] == "income")
    assert client.put(
        "/api/settings", headers=csrf_headers,
        json={"investment_target_percent": 20, "currency_target_percent": 10, "monthly_life_budget": 60_000},
    ).status_code == 200
    for body in (
        {"name": "Резерв", "account_type": "savings", "annual_rate": 5},
        {"name": "Доллары", "account_type": "currency", "currency_code": "USD", "exchange_rate": 100},
    ):
        assert client.post("/api/accounts", headers=csrf_headers, json=body).status_code == 201
    assert client.post(
        "/api/transactions", headers=csrf_headers,
        json={
            "tx_type": "income", "amount": 100_000, "account_id": checking["id"],
            "category_id": income_category["id"], "note": "Зарплата",
        },
    ).status_code == 201
    first = client.post("/api/salary-plan/apply", headers=csrf_headers, json={"confirm": True})
    assert first.status_code == 200
    assert {item["bucket"] for item in first.get_json()["data"]["created"]} == {"savings", "currency"}
    second = client.post("/api/salary-plan/apply", headers=csrf_headers, json={"confirm": True})
    assert second.status_code == 200
    assert second.get_json()["data"]["created"] == []
    assert client.post(
        "/api/transactions", headers=csrf_headers,
        json={
            "tx_type": "income", "amount": 50_000, "account_id": checking["id"],
            "category_id": income_category["id"], "note": "Вторая зарплата",
        },
    ).status_code == 201
    third = client.post("/api/salary-plan/apply", headers=csrf_headers, json={"confirm": True})
    assert third.status_code == 200
    assert {item["bucket"] for item in third.get_json()["data"]["created"]} == {"savings", "currency"}


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
    assert summary["total_capital"] == 0
    goal = client.post(
        "/api/goals", headers=csrf_headers,
        json={"title": "Резерв в евро", "target_amount": 5_000, "account_id": currency_id},
    )
    assert goal.status_code == 201
    linked = next(item for item in client.get("/api/goals").get_json()["data"] if item["id"] == goal.get_json()["data"]["id"])
    assert linked["current_amount"] == 1_000
    assert linked["account_name"] == "Евро"
    mismatch = client.post(
        "/api/transactions", headers=csrf_headers,
        json={
            "tx_type": "transfer", "amount": 1_000, "target_amount": 10,
            "account_id": checking["id"],
            "target_account_id": next(
                item["id"] for item in data["accounts"] if item["account_type"] == "investment"
            ),
        },
    )
    assert mismatch.status_code == 400
    outgoing_currency = client.post(
        "/api/transactions", headers=csrf_headers,
        json={
            "tx_type": "transfer", "amount": 100,
            "account_id": currency_id, "target_account_id": checking["id"],
        },
    )
    assert outgoing_currency.status_code == 400
    assert client.delete(f"/api/transactions/{transaction_id}", headers=csrf_headers).status_code == 200
    account = next(item for item in client.get("/api/accounts").get_json()["data"] if item["id"] == currency_id)
    assert account["balance"] == 0


def test_insights_scenario_and_weekly_report_endpoints(client, csrf_headers):
    insights = client.get("/api/insights")
    assert insights.status_code == 200
    assert {"amount", "monthly_burn", "runway_months", "gap_3", "gap_6"} <= insights.get_json()["data"]["cushion"].keys()
    scenario = client.post(
        "/api/insights/what-if", headers=csrf_headers,
        json={
            "income": 120_000, "expense": 70_000, "savings_percent": 20,
            "currency_percent": 10, "savings_rate": 6, "currency_rate": 2,
            "horizon_months": 24,
        },
    )
    assert scenario.status_code == 200
    scenario_data = scenario.get_json()["data"]
    assert scenario_data["allocation"]["savings"] == 24_000
    assert scenario_data["projected_capital"] > scenario_data["current_capital"]
    report = client.get("/api/weekly-report")
    assert report.status_code == 200
    report_data = report.get_json()["data"]
    assert len(report_data["actions"]) == 3
    assert {"income", "expense", "saved", "currency_reserved"} <= report_data["current_week"].keys()


def test_category_learning_uses_consistent_corrected_history(client, app, csrf_headers):
    data = bootstrap(client)
    account = next(item for item in data["accounts"] if item["account_type"] == "checking")
    category = next(item for item in data["categories"] if item["name"] == "Продукты")
    for order in (101, 202, 303):
        response = client.post(
            "/api/transactions",
            headers=csrf_headers,
            json={
                "tx_type": "expense", "amount": 500, "account_id": account["id"],
                "category_id": category["id"], "note": f"Яндекс Лавка заказ {order}",
            },
        )
        assert response.status_code == 201
    learned = client.post(
        "/api/transactions",
        headers=csrf_headers,
        json={
            "tx_type": "expense", "amount": 700, "account_id": account["id"],
            "note": "Яндекс Лавка заказ 404",
        },
    )
    assert learned.status_code == 201
    with app.app_context():
        row = get_db().execute(
            "SELECT category_id FROM transactions WHERE id = ?", (learned.get_json()["data"]["id"],)
        ).fetchone()
        assert row["category_id"] == category["id"]
