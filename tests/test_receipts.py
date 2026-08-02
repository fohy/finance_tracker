from __future__ import annotations

import pytest

import finance.receipt_service as receipt_service
from finance.db import get_db
from finance.receipt_service import classify_item, fetch_receipt


def test_parse_receipt_qr_prefills_expense(client, csrf_headers):
    response = client.post("/api/receipts/parse", headers=csrf_headers, json={
        "qr": "t=20260730T1435&s=1234.56&fn=9282440300123456&i=4567&fp=123456789&n=1"
    })
    assert response.status_code == 200
    receipt = response.get_json()["data"]
    assert receipt["amount"] == 1234.56
    assert receipt["date"] == "2026-07-30"
    assert receipt["time"] == "14:35"
    assert receipt["is_expense"] is True


def test_parse_receipt_qr_rejects_non_receipt(client, csrf_headers):
    response = client.post(
        "/api/receipts/parse", headers=csrf_headers, json={"qr": "https://example.com"}
    )
    assert response.status_code == 400
    assert "не QR-код кассового чека" in response.get_json()["error"]


def test_receipt_item_classification_is_conservative():
    assert classify_item("Пиво светлое 0,5 л") == ("Алкоголь", "high")
    assert classify_item("Арбуз весовой") == ("Продукты", "high")
    assert classify_item("Туалетная бумага 4 рулона") == ("Дом и быт", "high")
    assert classify_item("Шоколадка молочная") == ("Приколюхи", "high")
    assert classify_item("Неизвестный артикул 123") == (None, "uncertain")


def test_fetch_receipt_converts_network_error_to_value_error(monkeypatch):
    def blocked_request(*args, **kwargs):
        raise receipt_service.CurlRequestException("CONNECT tunnel failed, response 403")

    monkeypatch.setattr("finance.receipt_service.requests.post", blocked_request)

    qr = "t=20260730T1435&s=660.00&fn=9282440300123456&i=9876&fp=123456789&n=1"
    with pytest.raises(ValueError, match="Не удалось получить состав чека"):
        fetch_receipt(qr, "configured-token")


def test_import_receipt_creates_grouped_common_expenses(app, client, csrf_headers):
    bootstrap = client.get("/api/bootstrap").get_json()["data"]
    categories = {item["name"]: item["id"] for item in bootstrap["categories"]}
    life = next(item for item in bootstrap["accounts"] if item["kind"] == "life")
    qr = "t=20260730T1435&s=660.00&fn=9282440300123456&i=9876&fp=123456789&n=1"
    groups = [
        {"category_id": categories["Алкоголь"], "amount": 100, "items": ["Пиво"]},
        {"category_id": categories["Продукты"], "amount": 200, "items": ["Арбуз"]},
        {"category_id": categories["Дом и быт"], "amount": 300, "items": ["Туалетная бумага"]},
        {"category_id": categories["Приколюхи"], "amount": 60, "items": ["Шоколад", "Жвачка"]},
    ]
    response = client.post(
        "/api/receipts/import", headers=csrf_headers, json={
            "qr": qr,
            "groups": groups,
            "mappings": [{"name": "Неизвестный товар XYZ", "category_id": categories["Приколюхи"]}],
        }
    )
    assert response.status_code == 201
    assert response.get_json()["data"]["count"] == 4

    transactions = client.get(
        "/api/transactions?period=day&anchor=2026-07-30&per_page=10"
    ).get_json()["data"]["items"]
    assert sorted(item["amount"] for item in transactions) == [60, 100, 200, 300]
    assert all(item["person_id"] is None for item in transactions)
    assert {item["category_name"] for item in transactions} == {
        "Алкоголь", "Продукты", "Дом и быт", "Приколюхи",
    }
    accounts = client.get("/api/accounts").get_json()["data"]
    updated_life = next(item for item in accounts if item["id"] == life["id"])
    assert updated_life["balance"] == life["balance"] - 660

    with app.app_context():
        learned = get_db().execute(
            """SELECT r.normalized_name, c.name category_name
               FROM receipt_product_categories r JOIN categories c ON c.id = r.category_id"""
        ).fetchone()
        assert learned["normalized_name"] == "неизвестный товар xyz"
        assert learned["category_name"] == "Приколюхи"

    duplicate = client.post(
        "/api/receipts/import", headers=csrf_headers, json={"qr": qr, "groups": groups}
    )
    assert duplicate.status_code == 400
    assert "уже был добавлен" in duplicate.get_json()["error"]
