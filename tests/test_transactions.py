from __future__ import annotations


def bootstrap(client):
    response = client.get("/api/bootstrap")
    assert response.status_code == 200
    return response.get_json()["data"]


def test_transfer_updates_both_balances_and_can_be_reversed(client):
    data = bootstrap(client)
    life = next(account for account in data["accounts"] if account["kind"] == "life")
    investment = next(account for account in data["accounts"] if account["kind"] == "investment")
    initial_life, initial_investment = life["balance"], investment["balance"]

    response = client.post("/api/transactions", json={
        "tx_type": "transfer", "amount": 1234.56, "account_id": life["id"],
        "target_account_id": investment["id"], "note": "Тест перевода",
    })
    assert response.status_code == 201
    transaction_id = response.get_json()["data"]["id"]

    accounts = client.get("/api/accounts").get_json()["data"]
    assert next(item for item in accounts if item["id"] == life["id"])["balance"] == initial_life - 1234.56
    assert next(item for item in accounts if item["id"] == investment["id"])["balance"] == initial_investment + 1234.56

    assert client.delete(f"/api/transactions/{transaction_id}").status_code == 200
    accounts = client.get("/api/accounts").get_json()["data"]
    assert next(item for item in accounts if item["id"] == life["id"])["balance"] == initial_life
    assert next(item for item in accounts if item["id"] == investment["id"])["balance"] == initial_investment


def test_transaction_rejects_invalid_references_and_preserves_balances(client):
    data = bootstrap(client)
    life = next(account for account in data["accounts"] if account["kind"] == "life")
    category = next(item for item in data["categories"] if item["type"] == "expense")

    response = client.post("/api/transactions", json={
        "tx_type": "transfer", "amount": 100, "account_id": life["id"],
        "target_account_id": life["id"],
    })
    assert response.status_code == 400

    response = client.post("/api/transactions", json={
        "tx_type": "income", "amount": 100, "account_id": life["id"],
        "category_id": category["id"],
    })
    assert response.status_code == 400
    accounts = client.get("/api/accounts").get_json()["data"]
    assert next(item for item in accounts if item["id"] == life["id"])["balance"] == life["balance"]
