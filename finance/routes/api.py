from __future__ import annotations

from datetime import date
from typing import Any

from flask import Blueprint, jsonify, request

from ..db import get_db
from ..errors import NotFoundError
from ..services import (
    accrue_interest,
    available_for_purchases,
    category_breakdown,
    get_summary,
    goal_progress,
    period_bounds,
    purchase_plan,
    shift_period,
    trend_series,
)
from ..transaction_service import create_transaction as create_transaction_record
from ..transaction_service import delete_transaction as delete_transaction_record

api_bp = Blueprint("api", __name__)


def payload() -> dict[str, Any]:
    return request.get_json(silent=True) or request.form.to_dict()


def as_float(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Поле «{field}» должно быть числом") from exc
    if result <= 0:
        raise ValueError(f"Поле «{field}» должно быть больше нуля")
    return result


def as_int_or_none(value: Any) -> int | None:
    if value in (None, "", "null"):
        return None
    return int(value)


def ok(data: Any = None, status: int = 200):
    return jsonify({"ok": True, "data": data}), status


def fail(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


@api_bp.errorhandler(ValueError)
def value_error(error: ValueError):
    return fail(str(error), 400)


@api_bp.errorhandler(NotFoundError)
def not_found_error(error: NotFoundError):
    return fail(str(error), 404)


@api_bp.get("/bootstrap")
def bootstrap():
    accrue_interest()
    db = get_db()
    return ok({
        "people": [dict(r) for r in db.execute("SELECT * FROM people ORDER BY id")],
        "categories": [dict(r) for r in db.execute("SELECT * FROM categories ORDER BY type, name")],
        "accounts": [dict(r) for r in db.execute("SELECT * FROM accounts ORDER BY kind")],
        "settings": {r["key"]: r["value"] for r in db.execute("SELECT * FROM settings")},
        "today": date.today().isoformat(),
    })


@api_bp.get("/summary")
def summary():
    period = request.args.get("period", "month")
    anchor = request.args.get("anchor")
    person_id = as_int_or_none(request.args.get("person_id"))
    data = get_summary(period, anchor, person_id)
    data["breakdown"] = category_breakdown(period, anchor, person_id)
    data["trend"] = trend_series(period, anchor, person_id)
    data["prev_anchor"] = shift_period(period, anchor, -1)
    data["next_anchor"] = shift_period(period, anchor, 1)
    return ok(data)


@api_bp.get("/transactions")
def list_transactions():
    db = get_db()
    period = request.args.get("period", "month")
    anchor = request.args.get("anchor")
    person_id = as_int_or_none(request.args.get("person_id"))
    tx_type = request.args.get("type")
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, max(1, int(request.args.get("per_page", 20))))
    start, end = period_bounds(period, anchor)

    filters = ["t.tx_date BETWEEN ? AND ?"]
    params: list[Any] = [start.isoformat(), end.isoformat()]
    if person_id:
        filters.append("t.person_id = ?")
        params.append(person_id)
    if tx_type:
        filters.append("t.tx_type = ?")
        params.append(tx_type)
    where = " AND ".join(filters)

    total = db.execute(f"SELECT COUNT(*) FROM transactions t WHERE {where}", params).fetchone()[0]
    rows = db.execute(
        f"""SELECT t.*, c.name category_name, c.icon category_icon, c.color category_color,
                   p.name person_name, p.avatar_color,
                   a.name account_name, ta.name target_account_name
            FROM transactions t
            LEFT JOIN categories c ON c.id=t.category_id
            LEFT JOIN people p ON p.id=t.person_id
            LEFT JOIN accounts a ON a.id=t.account_id
            LEFT JOIN accounts ta ON ta.id=t.target_account_id
            WHERE {where}
            ORDER BY t.tx_date DESC, t.id DESC
            LIMIT ? OFFSET ?""",
        [*params, per_page, (page - 1) * per_page],
    ).fetchall()
    return ok({
        "items": [dict(r) for r in rows],
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": max(1, (total + per_page - 1) // per_page),
    })


@api_bp.post("/transactions")
def create_transaction():
    data = payload()
    tx_type = data.get("tx_type")
    if tx_type not in {"income", "expense", "transfer"}:
        raise ValueError("Неверный тип операции")
    amount = as_float(data.get("amount"), "Сумма")
    tx_date = str(data.get("tx_date") or date.today().isoformat())
    account_id = int(data.get("account_id"))
    target_account_id = as_int_or_none(data.get("target_account_id"))
    category_id = as_int_or_none(data.get("category_id"))
    person_id = as_int_or_none(data.get("person_id"))
    note = str(data.get("note") or "").strip()

    transaction_id = create_transaction_record(
        tx_type=tx_type, amount=amount, tx_date=tx_date, account_id=account_id,
        target_account_id=target_account_id, category_id=category_id,
        person_id=person_id, note=note,
    )
    return ok({"id": transaction_id}, 201)


@api_bp.delete("/transactions/<int:tx_id>")
def delete_transaction(tx_id: int):
    delete_transaction_record(tx_id)
    return ok()


@api_bp.post("/categories")
def create_category():
    data = payload()
    name = str(data.get("name") or "").strip()
    category_type = data.get("type")
    if not name:
        raise ValueError("Введите название категории")
    if category_type not in {"income", "expense"}:
        raise ValueError("Неверный тип категории")
    db = get_db()
    try:
        cursor = db.execute(
            "INSERT INTO categories(name, type, icon, color, parent_id, is_custom) VALUES (?, ?, ?, ?, ?, 1)",
            (name, category_type, data.get("icon") or "•", data.get("color") or "#7c5cff", as_int_or_none(data.get("parent_id"))),
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        if "UNIQUE" in str(exc):
            raise ValueError("Такая категория уже существует") from exc
        raise
    return ok({"id": cursor.lastrowid}, 201)


@api_bp.get("/accounts")
def accounts():
    accrue_interest()
    return ok([dict(r) for r in get_db().execute("SELECT * FROM accounts ORDER BY kind")])


@api_bp.patch("/accounts/<int:account_id>")
def update_account(account_id: int):
    data = payload()
    allowed = {"name", "annual_rate"}
    updates = {k: data[k] for k in allowed if k in data}
    if not updates:
        raise ValueError("Можно изменить только название или годовую ставку; баланс меняется операциями")
    if "name" in updates and not str(updates["name"]).strip():
        raise ValueError("Название счёта не может быть пустым")
    if "annual_rate" in updates:
        try:
            updates["annual_rate"] = float(updates["annual_rate"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Годовая ставка должна быть числом") from exc
        if updates["annual_rate"] < 0:
            raise ValueError("Годовая ставка не может быть отрицательной")
    parts = ", ".join(f"{key} = ?" for key in updates)
    db = get_db()
    cursor = db.execute(f"UPDATE accounts SET {parts} WHERE id = ?", [*updates.values(), account_id])
    if cursor.rowcount == 0:
        db.rollback()
        return fail("Счёт не найден", 404)
    db.commit()
    return ok()


@api_bp.get("/goals")
def list_goals():
    rows = get_db().execute(
        """SELECT g.*, p.name person_name, p.avatar_color
           FROM goals g LEFT JOIN people p ON p.id=g.person_id
           ORDER BY CASE g.status WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END,
                    CASE g.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, g.target_date"""
    ).fetchall()
    return ok([goal_progress(dict(r)) for r in rows])


@api_bp.post("/goals")
def create_goal():
    data = payload()
    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("Введите название цели")
    target = as_float(data.get("target_amount"), "Сумма цели")
    current = max(0, float(data.get("current_amount") or 0))
    db = get_db()
    cursor = db.execute(
        """INSERT INTO goals(title, target_amount, current_amount, target_date, person_id, priority, note)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (title, target, current, data.get("target_date") or None, as_int_or_none(data.get("person_id")), data.get("priority") or "medium", data.get("note") or ""),
    )
    db.commit()
    return ok({"id": cursor.lastrowid}, 201)


@api_bp.patch("/goals/<int:item_id>")
def update_goal(item_id: int):
    data = payload()
    allowed = {"title", "target_amount", "current_amount", "target_date", "person_id", "priority", "status", "note"}
    updates = {k: data[k] for k in allowed if k in data}
    if not updates:
        raise ValueError("Нет данных для обновления")
    parts = ", ".join(f"{key} = ?" for key in updates)
    db = get_db()
    db.execute(f"UPDATE goals SET {parts} WHERE id = ?", [*updates.values(), item_id])
    db.commit()
    return ok()


@api_bp.delete("/goals/<int:item_id>")
def delete_goal(item_id: int):
    db = get_db()
    db.execute("DELETE FROM goals WHERE id = ?", (item_id,))
    db.commit()
    return ok()


@api_bp.get("/purchases")
def list_purchases():
    available = available_for_purchases()
    rows = get_db().execute(
        """SELECT b.*, p.name person_name, p.avatar_color
           FROM purchases b LEFT JOIN people p ON p.id=b.person_id
           ORDER BY CASE b.status WHEN 'planned' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END,
                    CASE b.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, b.target_date"""
    ).fetchall()
    return ok({
        "available_monthly": round(available, 2),
        "items": [purchase_plan(dict(r), available) for r in rows],
    })


@api_bp.post("/purchases")
def create_purchase():
    data = payload()
    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("Введите название покупки")
    cost = as_float(data.get("cost"), "Стоимость")
    saved = max(0, float(data.get("saved_amount") or 0))
    db = get_db()
    cursor = db.execute(
        """INSERT INTO purchases(title, cost, saved_amount, target_date, person_id, priority, note)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (title, cost, saved, data.get("target_date") or None, as_int_or_none(data.get("person_id")), data.get("priority") or "medium", data.get("note") or ""),
    )
    db.commit()
    return ok({"id": cursor.lastrowid}, 201)


@api_bp.patch("/purchases/<int:item_id>")
def update_purchase(item_id: int):
    data = payload()
    allowed = {"title", "cost", "saved_amount", "target_date", "person_id", "priority", "status", "note"}
    updates = {k: data[k] for k in allowed if k in data}
    if not updates:
        raise ValueError("Нет данных для обновления")
    parts = ", ".join(f"{key} = ?" for key in updates)
    db = get_db()
    db.execute(f"UPDATE purchases SET {parts} WHERE id = ?", [*updates.values(), item_id])
    db.commit()
    return ok()


@api_bp.delete("/purchases/<int:item_id>")
def delete_purchase(item_id: int):
    db = get_db()
    db.execute("DELETE FROM purchases WHERE id = ?", (item_id,))
    db.commit()
    return ok()


@api_bp.get("/people-metrics")
def people_metrics():
    db = get_db()
    period = request.args.get("period", "month")
    anchor = request.args.get("anchor")
    people = [dict(r) for r in db.execute("SELECT * FROM people ORDER BY id")]
    result = []
    for person in people:
        data = get_summary(period, anchor, person["id"])
        data["person"] = person
        data["breakdown"] = category_breakdown(period, anchor, person["id"])
        result.append(data)
    return ok(result)


@api_bp.get("/settings")
def get_settings():
    rows = get_db().execute("SELECT * FROM settings ORDER BY key").fetchall()
    return ok({r["key"]: r["value"] for r in rows})


@api_bp.put("/settings")
def update_settings():
    data = payload()
    if "investment_target_percent" in data:
        target = as_float(data["investment_target_percent"], "Цель инвестирования")
        if target > 100:
            raise ValueError("Цель инвестирования не может быть больше 100%")
    if "monthly_life_budget" in data:
        as_float(data["monthly_life_budget"], "Месячный бюджет")
    if "currency" in data and not str(data["currency"]).strip():
        raise ValueError("Укажите валюту")
    db = get_db()
    for key in ("investment_target_percent", "monthly_life_budget", "currency"):
        if key in data:
            db.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(data[key])),
            )
    db.commit()
    return ok()
