"""Write-side business rules for transactions.

Keeping balance changes here is intentional: a transaction and every affected
account are committed or rolled back together.  HTTP routes should only parse
requests and translate domain errors to responses.
"""
from __future__ import annotations

import re
from collections import Counter

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


def _merchant_key(note: str) -> str:
    """Reduce changing order/card details while keeping a recognizable merchant label."""
    value = note.casefold().replace("ё", "е")
    value = re.sub(r"\b(?:заказ|операция|платеж|чек|карта)\b", " ", value)
    value = re.sub(r"\d+", " ", value)
    value = re.sub(r"[^a-zа-я]+", " ", value)
    return " ".join(value.split())[:80]


def category_for_note(note: str, tx_type: str) -> int | None:
    """Infer a category conservatively from consistent corrected history."""
    if not note.strip() or tx_type not in {"income", "expense"}:
        return None
    key = _merchant_key(note)
    if len(key) < 3:
        return None
    history = get_db().execute(
        """SELECT t.category_id, t.note FROM transactions t
           JOIN categories c ON c.id = t.category_id
           WHERE t.tx_type = ? AND t.category_id IS NOT NULL AND TRIM(t.note) <> ''
           ORDER BY t.id DESC LIMIT 1000""",
        (tx_type,),
    ).fetchall()
    categories = [int(row["category_id"]) for row in history if _merchant_key(str(row["note"])) == key]
    if len(categories) < 3:
        return None
    ranking = Counter(categories).most_common(2)
    category_id, count = ranking[0]
    confidence = count / len(categories)
    if confidence < 0.8 or (len(ranking) > 1 and count == ranking[1][1]):
        return None
    return category_id


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
    actor_user_id: int | None = None,
    target_amount: float | None = None,
    commit: bool = True,
) -> int:
    if tx_type not in USER_TRANSACTION_TYPES:
        raise DomainError("Неверный тип операции")
    if amount <= 0:
        raise DomainError("Сумма должна быть больше нуля")
    source = get_db().execute(
        "SELECT account_type, is_active FROM accounts WHERE id = ?", (account_id,)
    ).fetchone()
    if not source:
        raise NotFoundError("Счёт не найден")
    if not source["is_active"]:
        raise DomainError("Исходный счёт отключён")
    if source["account_type"] == "currency":
        raise DomainError("Валютный счёт пока можно использовать только как счёт назначения")
    if person_id is not None:
        _require_entity("people", person_id, "Участник")
    if tx_type == "transfer":
        target = get_db().execute(
            "SELECT account_type, exchange_rate, is_active FROM accounts WHERE id = ?", (target_account_id,)
        ).fetchone()
        if not target:
            raise NotFoundError("Счёт назначения не найден")
        if not target["is_active"]:
            raise DomainError("Счёт назначения отключён")
        if account_id == target_account_id:
            raise DomainError("Нельзя перевести деньги на тот же счёт")
        if category_id is not None:
            raise DomainError("У перевода не может быть категории")
        if target["account_type"] == "currency":
            expected = amount / float(target["exchange_rate"])
            if target_amount is None:
                target_amount = expected
            effective_rate = amount / target_amount
            configured_rate = float(target["exchange_rate"])
            if not configured_rate * 0.75 <= effective_rate <= configured_rate * 1.25:
                raise DomainError("Сумма зачисления слишком сильно отличается от настроенного курса")
        else:
            if target_amount is not None and abs(target_amount - amount) > 0.005:
                raise DomainError("Для обычного счёта сумма списания и зачисления должна совпадать")
            target_amount = amount
        if target_amount <= 0:
            raise DomainError("Сумма зачисления должна быть больше нуля")
    else:
        if category_id is None:
            category_id = category_for_note(note, tx_type)
        if category_id is not None:
            _require_entity("categories", category_id, "Категория")
            category = get_db().execute("SELECT type FROM categories WHERE id = ?", (category_id,)).fetchone()
            if category["type"] != tx_type:
                raise DomainError("Тип категории не соответствует типу операции")

    db = get_db()
    try:
        cursor = db.execute(
            """INSERT INTO transactions(tx_type, amount, tx_date, category_id, person_id,
                       account_id, target_account_id, note, target_amount)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tx_type, round(amount, 2), _validate_date(tx_date), category_id, person_id,
             account_id, target_account_id, note, round(target_amount, 2) if target_amount else None),
        )
        signed_amount = amount if tx_type == "income" else -amount
        db.execute("UPDATE accounts SET balance = ROUND(balance + ?, 2) WHERE id = ?", (signed_amount, account_id))
        if tx_type == "transfer":
            db.execute(
                "UPDATE accounts SET balance = ROUND(balance + ?, 2) WHERE id = ?",
                (target_amount, target_account_id),
            )
        db.execute(
            """INSERT INTO audit_log(action, entity_type, entity_id, details, actor_user_id)
               VALUES (?, ?, ?, ?, ?)""",
            ("created", "transaction", cursor.lastrowid, tx_type, actor_user_id),
        )
        if commit:
            db.commit()
    except Exception:
        if commit:
            db.rollback()
        raise
    return int(cursor.lastrowid)


def delete_transaction(tx_id: int, actor_user_id: int | None = None) -> None:
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
            credited = row["target_amount"] if row["target_amount"] is not None else row["amount"]
            db.execute("UPDATE accounts SET balance = ROUND(balance - ?, 2) WHERE id = ?", (credited, row["target_account_id"]))
        db.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
        db.execute(
            """INSERT INTO audit_log(action, entity_type, entity_id, actor_user_id)
               VALUES (?, ?, ?, ?)""",
            ("deleted", "transaction", tx_id, actor_user_id),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def update_transaction_metadata(
    tx_id: int, *, tx_date: str | None, note: str | None, person_id: int | None, category_id: int | None,
    actor_user_id: int | None = None,
) -> None:
    """Edit non-balance fields without ever rewriting the financial ledger."""
    db = get_db()
    row = db.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    if not row:
        raise NotFoundError("Операция не найдена")
    if row["tx_type"] == "interest":
        raise DomainError("Автоматическое начисление нельзя редактировать вручную")
    updates: dict[str, object] = {}
    if tx_date is not None:
        updates["tx_date"] = _validate_date(tx_date)
    if note is not None:
        updates["note"] = note.strip()
    if person_id is not None:
        _require_entity("people", person_id, "Участник")
        updates["person_id"] = person_id
    if category_id is not None:
        _require_entity("categories", category_id, "Категория")
        category = db.execute("SELECT type FROM categories WHERE id = ?", (category_id,)).fetchone()
        if category["type"] != row["tx_type"]:
            raise DomainError("Тип категории не соответствует типу операции")
        updates["category_id"] = category_id
    if not updates:
        raise DomainError("Нет полей для изменения")
    try:
        assignments = ", ".join(f"{field} = ?" for field in updates)
        db.execute(f"UPDATE transactions SET {assignments} WHERE id = ?", [*updates.values(), tx_id])
        db.execute(
            """INSERT INTO audit_log(action, entity_type, entity_id, details, actor_user_id)
               VALUES (?, ?, ?, ?, ?)""",
            ("updated", "transaction", tx_id, ",".join(updates), actor_user_id),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
