from __future__ import annotations

from datetime import date

from finance.db import get_db
from finance.services import accrue_interest, calculate_monthly_interest


def _interest_account(db, *, enabled: bool = True, rate: float = 36.5) -> int:
    cursor = db.execute(
        """INSERT INTO accounts(
               name, kind, account_type, balance, annual_rate, last_accrual_date,
               interest_enabled, interest_last_posted_month
           ) VALUES ('Тестовый накопительный', 'life', 'savings', 0, ?, '2022-12-31', ?, '2022-12')""",
        (rate, int(enabled)),
    )
    return int(cursor.lastrowid)


def test_interest_uses_daily_closing_balance_and_posts_once(app):
    with app.app_context():
        db = get_db()
        account_id = _interest_account(db)
        db.execute(
            "INSERT INTO account_rate_history(account_id, effective_date, annual_rate) VALUES (?, '2023-01-01', 36.5)",
            (account_id,),
        )
        db.execute(
            """INSERT INTO transactions(tx_type, amount, tx_date, account_id, note)
               VALUES ('income', 10000, '2023-01-01', ?, 'Пополнение'),
                      ('expense', 5000, '2023-01-16', ?, 'Снятие')""",
            (account_id, account_id),
        )
        db.execute("UPDATE accounts SET balance = 5000 WHERE id = ?", (account_id,))
        db.commit()

        accrue_interest(date(2023, 2, 1))
        account = db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        assert account["balance"] == 5230
        assert account["interest_last_posted_month"] == "2023-01"
        rows = db.execute(
            "SELECT amount, tx_date, note FROM transactions WHERE tx_type = 'interest' AND account_id = ?",
            (account_id,),
        ).fetchall()
        assert [dict(row) for row in rows] == [{
            "amount": 230, "tx_date": "2023-01-31", "note": "Проценты за 01.2023",
        }]

        accrue_interest(date(2023, 2, 15))
        assert db.execute(
            "SELECT COUNT(*) FROM transactions WHERE tx_type = 'interest' AND account_id = ?",
            (account_id,),
        ).fetchone()[0] == 1


def test_rate_history_changes_daily_calculation_and_disabled_account_does_not_post(app):
    with app.app_context():
        db = get_db()
        account_id = _interest_account(db, enabled=False, rate=73)
        db.executemany(
            "INSERT INTO account_rate_history(account_id, effective_date, annual_rate) VALUES (?, ?, ?)",
            [(account_id, "2023-01-01", 36.5), (account_id, "2023-01-16", 73)],
        )
        db.execute(
            "INSERT INTO transactions(tx_type, amount, tx_date, account_id) VALUES ('income', 10000, '2023-01-01', ?)",
            (account_id,),
        )
        db.execute("UPDATE accounts SET balance = 10000 WHERE id = ?", (account_id,))
        db.commit()

        assert calculate_monthly_interest(account_id, date(2023, 1, 1), 73) == 470
        accrue_interest(date(2023, 2, 1))
        assert db.execute(
            "SELECT COUNT(*) FROM transactions WHERE tx_type = 'interest' AND account_id = ?",
            (account_id,),
        ).fetchone()[0] == 0


def test_interest_rate_and_automation_can_be_changed(client, csrf_headers):
    account = next(
        item for item in client.get("/api/accounts").get_json()["data"]
        if item["account_type"] == "investment"
    )
    response = client.patch(
        f"/api/accounts/{account['id']}",
        headers=csrf_headers,
        json={"annual_rate": 7.25, "interest_enabled": True},
    )
    assert response.status_code == 200
    updated = next(
        item for item in client.get("/api/accounts").get_json()["data"]
        if item["id"] == account["id"]
    )
    assert updated["annual_rate"] == 7.25
    assert updated["interest_enabled"] == 1

    assert client.patch(
        f"/api/accounts/{account['id']}",
        headers=csrf_headers,
        json={"interest_enabled": False},
    ).status_code == 200
    disabled = next(
        item for item in client.get("/api/accounts").get_json()["data"]
        if item["id"] == account["id"]
    )
    assert disabled["interest_enabled"] == 0
