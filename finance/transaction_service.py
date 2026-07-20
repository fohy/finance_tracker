"""Write-side business rules for transactions.

Keeping balance changes here is intentional: a transaction and every affected
account are committed or rolled back together.  HTTP routes should only parse
requests and translate domain errors to responses.
"""
from __future__ import annotations

from .db import get_db
from .errors import DomainError, NotFoundError
from .services import parse_date

USER_TRANSACTION_TYPES = frozenset({"income", "expense", "transfer"})


def _entity_exists(table: str, entity_id: int | None) -> bool:
    if entity_id is None:
        return True
    return get_db().execute(f"SELECT 1 FROM {table} WHERE id = ?", (entity_id,)).fetchone() is not None


def _require_entity(table: str, entity_id: int | None, label: str) -> None:
    if entity_id is None or not _entity_exists(table, entity_id):
        raise NotFoundError(f"{label} не найден")


def _validate_date(value: str) -> str:
    try:
        return parse_date(value).isoformat()
    except ValueError as exc:
        raise DomainError("Дата должна быть в формате ГГГГ-ММ-ДД") from exc


def create_transaction(
    *,
    tx_type: str,
    amount: float,
    tx_date: str,
    account_id: int,
    target_account_id: int | None,
    category_id: int | None,
    person_id: int | None,
    note: str,
) -> int:
    if tx_type not in USER_TRANSACTION_TYPES:
        raise DomainError("Неверный тип операции")
    if amount <= 0:
        raise DomainError("Сумма должна быть больше нуля")
    _require_entity("accounts", account_id, "Счёт")
    if person_id is not None:
        _require_entity("people", person_id, "Участник")
    if tx_type == "transfer":
        _require_entity("accounts", target_account_id, "Счёт назначения")
        if account_id == target_account_id:
            raise DomainError("Нельзя перевести деньги на тот же счёт")
        if category_id is not None:
            raise DomainError("У перевода не может быть категории")
    else:
        _require_entity("categories", category_id, "Категория")
        category = get_db().execute("SELECT type FROM categories WHERE id = ?", (category_id,)).fetchone()
        if category["type"] != tx_type:
            raise DomainError("Тип категории не соответствует типу операции")

    db = get_db()
    try:
        cursor = db.execute(
            """INSERT INTO transactions(tx_type, amount, tx_date, category_id, person_id, account_id, target_account_id, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (tx_type, round(amount, 2), _validate_date(tx_date), category_id, person_id, account_id, target_account_id, note),
        )
        signed_amount = amount if tx_type == "income" else -amount
        db.execute("UPDATE accounts SET balance = ROUND(balance + ?, 2) WHERE id = ?", (signed_amount, account_id))
        if tx_type == "transfer":
            db.execute("UPDATE accounts SET balance = ROUND(balance + ?, 2) WHERE id = ?", (amount, target_account_id))
        db.execute(
            "INSERT INTO audit_log(action, entity_type, entity_id, details) VALUES (?, ?, ?, ?)",
            ("created", "transaction", cursor.lastrowid, tx_type),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return int(cursor.lastrowid)


def delete_transaction(tx_id: int) -> None:
    db = get_db()
    row = db.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    if not row:
        raise NotFoundError("Операция не найдена")
    if row["tx_type"] == "interest":
        raise DomainError("Автоматическое начисление нельзя удалить вручную")
    try:
        signed_amount = -row["amount"] if row["tx_type"] == "income" else row["amount"]
        db.execute("UPDATE accounts SET balance = ROUND(balance + ?, 2) WHERE id = ?", (signed_amount, row["account_id"]))
        if row["tx_type"] == "transfer":
            db.execute("UPDATE accounts SET balance = ROUND(balance - ?, 2) WHERE id = ?", (row["amount"], row["target_account_id"]))
        db.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
        db.execute("INSERT INTO audit_log(action, entity_type, entity_id) VALUES (?, ?, ?)", ("deleted", "transaction", tx_id))
        db.commit()
    except Exception:
        db.rollback()
        raise
