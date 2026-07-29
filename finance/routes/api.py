from __future__ import annotations

import csv
from calendar import monthrange
from datetime import date, timedelta
from io import StringIO
from typing import Any

from flask import Blueprint, Response, jsonify, request

from ..auth import current_user_id
from ..db import get_db
from ..errors import NotFoundError
from ..services import (
    accrue_interest,
    available_for_purchases,
    category_breakdown,
    category_budget_status,
    get_summary,
    goal_progress,
    parse_date,
    period_bounds,
    purchase_plan,
    shift_period,
    spending_statistics,
    trend_series,
)
from ..transaction_service import create_transaction as create_transaction_record
from ..transaction_service import delete_transaction as delete_transaction_record
from ..transaction_service import update_transaction_metadata

api_bp = Blueprint("api", __name__)

ACCOUNT_TYPES = frozenset({"checking", "cash", "savings", "deposit", "currency", "investment"})


def account_kind(account_type: str) -> str:
    return "investment" if account_type == "investment" else "life"


def account_rate(value: Any, account_type: str) -> float:
    try:
        rate = float(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Годовая ставка должна быть числом") from exc
    if rate < 0 or rate > 100:
        raise ValueError("Годовая ставка должна быть от 0 до 100%")
    return round(rate, 3) if account_type in {"savings", "deposit", "investment"} else 0


def account_currency(data: dict[str, Any], account_type: str, current: Any = None) -> tuple[str, float]:
    db = get_db()
    base_row = db.execute("SELECT value FROM settings WHERE key = 'base_currency_code'").fetchone()
    base_code = str(base_row["value"] if base_row else "RUB").upper()
    if account_type != "currency":
        return base_code, 1.0
    code = str(data.get("currency_code", current["currency_code"] if current else base_code)).strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError("Код валюты должен состоять из трёх букв")
    try:
        exchange_rate = float(data.get("exchange_rate", current["exchange_rate"] if current else 1))
    except (TypeError, ValueError) as exc:
        raise ValueError("Курс валюты должен быть числом") from exc
    if exchange_rate <= 0:
        raise ValueError("Курс валюты должен быть больше нуля")
    return code, round(exchange_rate, 6)


def account_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["base_equivalent"] = round(
        float(item["balance"]) * (float(item["exchange_rate"]) if item["account_type"] == "currency" else 1), 2
    )
    return item


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
        "accounts": [account_dict(r) for r in db.execute(
            "SELECT * FROM accounts WHERE is_active = 1 ORDER BY account_type, name"
        )],
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
    data["spending_stats"] = spending_statistics(period, anchor, person_id)
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
    if request.args.get("from"):
        start = parse_date(request.args["from"])
    if request.args.get("to"):
        end = parse_date(request.args["to"])
    if start > end:
        raise ValueError("Начальная дата позже конечной")

    filters = ["t.tx_date BETWEEN ? AND ?"]
    params: list[Any] = [start.isoformat(), end.isoformat()]
    if person_id:
        filters.append("t.person_id = ?")
        params.append(person_id)
    if tx_type:
        if tx_type not in {"income", "expense", "transfer", "interest"}:
            raise ValueError("Неверный тип операции")
        filters.append("t.tx_type = ?")
        params.append(tx_type)
    category_id = as_int_or_none(request.args.get("category_id"))
    if category_id:
        filters.append("t.category_id = ?")
        params.append(category_id)
    search = str(request.args.get("q") or "").strip()
    if search:
        filters.append("(t.note LIKE ? OR c.name LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
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


@api_bp.patch("/transactions/<int:tx_id>")
def update_transaction(tx_id: int):
    data = payload()
    update_transaction_metadata(
        tx_id,
        tx_date=data.get("tx_date"),
        note=data.get("note"),
        person_id=as_int_or_none(data.get("person_id")) if "person_id" in data else None,
        category_id=as_int_or_none(data.get("category_id")) if "category_id" in data else None,
        actor_user_id=current_user_id(),
    )
    return ok()


@api_bp.post("/transactions/<int:tx_id>/duplicate")
def duplicate_transaction(tx_id: int):
    row = get_db().execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    if not row:
        return fail("Операция не найдена", 404)
    if row["tx_type"] == "interest":
        raise ValueError("Автоматическое начисление нельзя дублировать")
    transaction_id = create_transaction_record(
        tx_type=row["tx_type"], amount=float(row["amount"]), tx_date=date.today().isoformat(),
        account_id=row["account_id"], target_account_id=row["target_account_id"],
        category_id=row["category_id"], person_id=row["person_id"], note=row["note"],
        target_amount=row["target_amount"],
        actor_user_id=current_user_id(),
    )
    return ok({"id": transaction_id}, 201)


@api_bp.get("/transactions/export.csv")
def export_transactions():
    period = request.args.get("period", "month")
    start, end = period_bounds(period, request.args.get("anchor"))
    rows = get_db().execute(
        """SELECT t.tx_date, t.tx_type, t.amount, c.name category, p.name person,
                   a.name account, ta.name target_account, t.note
           FROM transactions t
           LEFT JOIN categories c ON c.id = t.category_id
           LEFT JOIN people p ON p.id = t.person_id
           JOIN accounts a ON a.id = t.account_id
           LEFT JOIN accounts ta ON ta.id = t.target_account_id
           WHERE t.tx_date BETWEEN ? AND ? ORDER BY t.tx_date, t.id""",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Дата", "Тип", "Сумма", "Категория", "Участник", "Счёт", "Счёт назначения", "Заметка"])
    writer.writerows([list(row) for row in rows])
    return Response("\ufeff" + output.getvalue(), mimetype="text/csv", headers={
        "Content-Disposition": "attachment; filename=finflow-transactions.csv"
    })


@api_bp.post("/transactions")
def create_transaction():
    data = payload()
    tx_type = data.get("tx_type")
    if tx_type not in {"income", "expense", "transfer"}:
        raise ValueError("Неверный тип операции")
    amount = as_float(data.get("amount"), "Сумма")
    tx_date = str(data.get("tx_date") or date.today().isoformat())
    try:
        account_id = int(data.get("account_id"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Выберите счёт") from exc
    target_account_id = as_int_or_none(data.get("target_account_id"))
    category_id = as_int_or_none(data.get("category_id"))
    person_id = as_int_or_none(data.get("person_id"))
    note = str(data.get("note") or "").strip()
    target_amount = as_float(data.get("target_amount"), "Сумма зачисления") if data.get("target_amount") not in (None, "") else None

    transaction_id = create_transaction_record(
        tx_type=tx_type, amount=amount, tx_date=tx_date, account_id=account_id,
        target_account_id=target_account_id, category_id=category_id,
        person_id=person_id, note=note, actor_user_id=current_user_id(),
        target_amount=target_amount,
    )
    return ok({"id": transaction_id}, 201)


@api_bp.delete("/transactions/<int:tx_id>")
def delete_transaction(tx_id: int):
    delete_transaction_record(tx_id, actor_user_id=current_user_id())
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
            (name, category_type, data.get("icon") or "category", data.get("color") or "#7c5cff", as_int_or_none(data.get("parent_id"))),
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
    return ok([account_dict(r) for r in get_db().execute(
        "SELECT * FROM accounts ORDER BY is_active DESC, account_type, name"
    )])


@api_bp.post("/accounts")
def create_account():
    data = payload()
    name = str(data.get("name") or "").strip()
    account_type = str(data.get("account_type") or "checking")
    if not name:
        raise ValueError("Введите название счёта")
    if account_type not in ACCOUNT_TYPES:
        raise ValueError("Неизвестный тип счёта")
    rate = account_rate(data.get("annual_rate"), account_type)
    interest_enabled = (
        str(data.get("interest_enabled", "false")).lower() in {"1", "true", "yes", "on"}
        and account_type in {"savings", "deposit", "investment"}
    )
    if interest_enabled and rate <= 0:
        raise ValueError("Для автоначисления укажите ставку больше 0%")
    currency_code, exchange_rate = account_currency(data, account_type)
    db = get_db()
    try:
        today = date.today()
        previous_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        cursor = db.execute(
            """INSERT INTO accounts(name, kind, account_type, balance, annual_rate, last_accrual_date,
                       interest_enabled, interest_last_posted_month, is_active, currency_code, exchange_rate)
               VALUES (?, ?, ?, 0, ?, ?, ?, ?, 1, ?, ?)""",
            (name, account_kind(account_type), account_type, rate, today.isoformat(),
             int(interest_enabled), previous_month if interest_enabled else None,
             currency_code, exchange_rate),
        )
        if rate > 0:
            db.execute(
                "INSERT INTO account_rate_history(account_id, effective_date, annual_rate) VALUES (?, ?, ?)",
                (cursor.lastrowid, today.isoformat(), rate),
            )
        db.commit()
    except Exception as exc:
        db.rollback()
        if "UNIQUE" in str(exc):
            raise ValueError("Счёт с таким названием уже существует") from exc
        raise
    return ok({"id": cursor.lastrowid}, 201)


@api_bp.patch("/accounts/<int:account_id>")
def update_account(account_id: int):
    data = payload()
    allowed = {
        "name", "account_type", "annual_rate", "interest_enabled", "is_active",
        "currency_code", "exchange_rate",
    }
    updates = {k: data[k] for k in allowed if k in data}
    if not updates:
        raise ValueError("Нет полей для изменения")
    db = get_db()
    account = db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if not account:
        return fail("Счёт не найден", 404)
    if "name" in updates:
        updates["name"] = str(updates["name"]).strip()
        if not updates["name"]:
            raise ValueError("Название счёта не может быть пустым")
    account_type = str(updates.get("account_type", account["account_type"]))
    if account_type not in ACCOUNT_TYPES:
        raise ValueError("Неизвестный тип счёта")
    if account_type != account["account_type"]:
        has_history = db.execute(
            "SELECT 1 FROM transactions WHERE account_id = ? OR target_account_id = ? LIMIT 1",
            (account_id, account_id),
        ).fetchone()
        if has_history:
            raise ValueError("Тип счёта с операциями изменить нельзя")
        updates["kind"] = account_kind(account_type)
    if "annual_rate" in updates or "account_type" in updates:
        updates["annual_rate"] = account_rate(updates.get("annual_rate", account["annual_rate"]), account_type)
    eligible_for_interest = account_type in {"savings", "deposit", "investment"}
    if "interest_enabled" in updates:
        updates["interest_enabled"] = int(
            str(updates["interest_enabled"]).lower() in {"1", "true", "yes", "on"}
        )
    if not eligible_for_interest:
        updates["interest_enabled"] = 0
    resulting_enabled = bool(updates.get("interest_enabled", account["interest_enabled"]))
    resulting_rate = float(updates.get("annual_rate", account["annual_rate"]))
    if resulting_enabled and resulting_rate <= 0:
        raise ValueError("Для автоначисления укажите ставку больше 0%")
    if resulting_enabled and not account["interest_enabled"]:
        previous_month = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        updates["interest_last_posted_month"] = previous_month
    if {"currency_code", "exchange_rate", "account_type"} & updates.keys():
        updates["currency_code"], updates["exchange_rate"] = account_currency(updates, account_type, account)
    if "is_active" in updates:
        updates["is_active"] = int(str(updates["is_active"]).lower() in {"1", "true", "yes", "on"})
        if not updates["is_active"] and abs(float(account["balance"])) > 0.005:
            raise ValueError("Сначала переведите остаток с этого счёта")
    parts = ", ".join(f"{key} = ?" for key in updates)
    try:
        db.execute(f"UPDATE accounts SET {parts} WHERE id = ?", [*updates.values(), account_id])
        if "annual_rate" in updates and resulting_rate != float(account["annual_rate"]):
            db.execute(
                """INSERT INTO account_rate_history(account_id, effective_date, annual_rate)
                   VALUES (?, ?, ?)
                   ON CONFLICT(account_id, effective_date) DO UPDATE SET annual_rate = excluded.annual_rate""",
                (account_id, date.today().isoformat(), resulting_rate),
            )
        db.commit()
    except Exception as exc:
        db.rollback()
        if "UNIQUE" in str(exc):
            raise ValueError("Счёт с таким названием уже существует") from exc
        raise
    return ok()


@api_bp.delete("/accounts/<int:account_id>")
def delete_account(account_id: int):
    db = get_db()
    account = db.execute("SELECT balance FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if not account:
        return fail("Счёт не найден", 404)
    if abs(float(account["balance"])) > 0.005:
        raise ValueError("Нельзя удалить счёт с ненулевым остатком")
    has_history = db.execute(
        """SELECT 1 FROM transactions WHERE account_id = ? OR target_account_id = ?
           UNION ALL
           SELECT 1 FROM recurring_transactions WHERE account_id = ? OR target_account_id = ?
           LIMIT 1""",
        (account_id, account_id, account_id, account_id),
    ).fetchone()
    if has_history:
        raise ValueError("Счёт связан с операциями — его можно только отключить")
    db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    db.commit()
    return ok()


@api_bp.get("/goals")
def list_goals():
    rows = get_db().execute(
        """SELECT g.*, p.name person_name, p.avatar_color, a.name account_name,
                  a.balance account_balance, a.exchange_rate account_exchange_rate
           FROM goals g LEFT JOIN people p ON p.id=g.person_id
           LEFT JOIN accounts a ON a.id = g.account_id
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
    account_id = as_int_or_none(data.get("account_id"))
    if account_id and not db.execute(
        """SELECT 1 FROM accounts WHERE id = ? AND is_active = 1
           AND account_type IN ('savings','deposit','currency','investment')""", (account_id,)
    ).fetchone():
        raise ValueError("Выберите активный накопительный счёт")
    cursor = db.execute(
        """INSERT INTO goals(title, target_amount, current_amount, target_date, person_id, priority, note, account_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (title, target, current, data.get("target_date") or None, as_int_or_none(data.get("person_id")),
         data.get("priority") or "medium", data.get("note") or "", account_id),
    )
    db.commit()
    return ok({"id": cursor.lastrowid}, 201)


@api_bp.patch("/goals/<int:item_id>")
def update_goal(item_id: int):
    data = payload()
    allowed = {"title", "target_amount", "current_amount", "target_date", "person_id", "priority", "status", "note", "account_id"}
    updates = {k: data[k] for k in allowed if k in data}
    if not updates:
        raise ValueError("Нет данных для обновления")
    if "account_id" in updates:
        updates["account_id"] = as_int_or_none(updates["account_id"])
        if updates["account_id"] and not get_db().execute(
            """SELECT 1 FROM accounts WHERE id = ? AND is_active = 1
               AND account_type IN ('savings','deposit','currency','investment')""",
            (updates["account_id"],),
        ).fetchone():
            raise ValueError("Выберите активный накопительный счёт")
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
        target = as_float(data["investment_target_percent"], "Доля накоплений")
        if target > 100:
            raise ValueError("Доля накоплений не может быть больше 100%")
    if "currency_target_percent" in data:
        currency_target = as_float(data["currency_target_percent"], "Доля валютного резерва")
        if currency_target > 100:
            raise ValueError("Доля валютного резерва не может быть больше 100%")
    current = {row["key"]: row["value"] for row in get_db().execute("SELECT key, value FROM settings")}
    savings_target = float(data.get("investment_target_percent", current.get("investment_target_percent", 20)))
    currency_target = float(data.get("currency_target_percent", current.get("currency_target_percent", 10)))
    if savings_target + currency_target > 100:
        raise ValueError("Сумма долей накоплений и валютного резерва не может превышать 100%")
    if "monthly_life_budget" in data:
        as_float(data["monthly_life_budget"], "Месячный бюджет")
    if "currency" in data and not str(data["currency"]).strip():
        raise ValueError("Укажите валюту")
    if "currency" in data:
        data["currency"] = str(data["currency"]).strip()
    if "base_currency_code" in data:
        base_code = str(data["base_currency_code"]).strip().upper()
        if len(base_code) != 3 or not base_code.isalpha():
            raise ValueError("Код основной валюты должен состоять из трёх букв")
        data["base_currency_code"] = base_code
    db = get_db()
    for key in ("investment_target_percent", "currency_target_percent", "monthly_life_budget", "currency", "base_currency_code"):
        if key in data:
            db.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(data[key])),
            )
    db.commit()
    return ok()


@api_bp.get("/budgets")
def list_budgets():
    return ok(category_budget_status(request.args.get("anchor")))


@api_bp.put("/budgets/<int:category_id>")
def save_budget(category_id: int):
    limit = as_float(payload().get("monthly_limit"), "Месячный лимит")
    db = get_db()
    category = db.execute("SELECT type FROM categories WHERE id = ?", (category_id,)).fetchone()
    if not category:
        return fail("Категория не найдена", 404)
    if category["type"] != "expense":
        raise ValueError("Лимит можно задать только для расходной категории")
    db.execute(
        """INSERT INTO category_budgets(category_id, monthly_limit) VALUES (?, ?)
           ON CONFLICT(category_id) DO UPDATE SET monthly_limit = excluded.monthly_limit""",
        (category_id, limit),
    )
    db.commit()
    return ok()


@api_bp.delete("/budgets/<int:category_id>")
def delete_budget(category_id: int):
    get_db().execute("DELETE FROM category_budgets WHERE category_id = ?", (category_id,))
    get_db().commit()
    return ok()


def _next_recurrence_date(value: str, frequency: str) -> str:
    current = parse_date(value)
    if frequency == "weekly":
        return (current + timedelta(days=7)).isoformat()
    month = current.month % 12 + 1
    year = current.year + (current.month // 12)
    return current.replace(year=year, month=month, day=min(current.day, monthrange(year, month)[1])).isoformat()


@api_bp.get("/recurring-transactions")
def list_recurring_transactions():
    rows = get_db().execute(
        """SELECT r.*, c.name category_name, p.name person_name, a.name account_name
           FROM recurring_transactions r
           LEFT JOIN categories c ON c.id = r.category_id
           LEFT JOIN people p ON p.id = r.person_id
           JOIN accounts a ON a.id = r.account_id
           ORDER BY r.is_active DESC, r.next_date, r.id"""
    ).fetchall()
    return ok([dict(row) for row in rows])


@api_bp.post("/recurring-transactions")
def create_recurring_transaction():
    data = payload()
    title = str(data.get("title") or "").strip()
    tx_type = data.get("tx_type")
    frequency = data.get("frequency")
    if not title:
        raise ValueError("Введите название регулярной операции")
    if tx_type not in {"income", "expense", "transfer"} or frequency not in {"weekly", "monthly"}:
        raise ValueError("Неверный тип операции или периодичность")
    db = get_db()
    account_id = as_int_or_none(data.get("account_id"))
    target_account_id = as_int_or_none(data.get("target_account_id"))
    category_id = as_int_or_none(data.get("category_id"))
    if not account_id or not db.execute("SELECT 1 FROM accounts WHERE id = ? AND is_active = 1", (account_id,)).fetchone():
        raise ValueError("Выберите активный счёт")
    if tx_type == "transfer":
        if not target_account_id or not db.execute(
            "SELECT 1 FROM accounts WHERE id = ? AND is_active = 1", (target_account_id,)
        ).fetchone():
            raise ValueError("Выберите активный счёт назначения")
        if target_account_id == account_id:
            raise ValueError("Счета перевода должны отличаться")
        category_id = None
    else:
        target_account_id = None
        category = db.execute("SELECT type FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not category or category["type"] != tx_type:
            raise ValueError("Выберите категорию нужного типа")
    cursor = db.execute(
        """INSERT INTO recurring_transactions(title, tx_type, amount, frequency, next_date, category_id,
                   person_id, account_id, target_account_id, note)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (title, tx_type, as_float(data.get("amount"), "Сумма"), frequency,
         parse_date(data.get("next_date")).isoformat(), category_id,
         as_int_or_none(data.get("person_id")), account_id,
         target_account_id, str(data.get("note") or "").strip()),
    )
    db.commit()
    return ok({"id": cursor.lastrowid}, 201)


@api_bp.post("/recurring-transactions/<int:item_id>/apply")
def apply_recurring_transaction(item_id: int):
    db = get_db()
    row = db.execute("SELECT * FROM recurring_transactions WHERE id = ? AND is_active = 1", (item_id,)).fetchone()
    if not row:
        return fail("Активное регулярное правило не найдено", 404)
    if parse_date(row["next_date"]) > date.today():
        raise ValueError("Дата следующей операции ещё не наступила")
    transaction_id = create_transaction_record(
        tx_type=row["tx_type"], amount=float(row["amount"]), tx_date=row["next_date"],
        account_id=row["account_id"], target_account_id=row["target_account_id"], category_id=row["category_id"],
        person_id=row["person_id"], note=row["note"] or row["title"], actor_user_id=current_user_id(),
    )
    db.execute("UPDATE recurring_transactions SET next_date = ? WHERE id = ?", (_next_recurrence_date(row["next_date"], row["frequency"]), item_id))
    db.commit()
    return ok({"id": transaction_id})


@api_bp.patch("/recurring-transactions/<int:item_id>")
def update_recurring_transaction(item_id: int):
    data = payload()
    if "is_active" not in data:
        raise ValueError("Можно изменить только активность правила")
    active = str(data["is_active"]).lower() in {"1", "true", "yes"}
    cursor = get_db().execute("UPDATE recurring_transactions SET is_active = ? WHERE id = ?", (int(active), item_id))
    if cursor.rowcount == 0:
        get_db().rollback()
        return fail("Регулярное правило не найдено", 404)
    get_db().commit()
    return ok()


@api_bp.delete("/recurring-transactions/<int:item_id>")
def delete_recurring_transaction(item_id: int):
    cursor = get_db().execute("DELETE FROM recurring_transactions WHERE id = ?", (item_id,))
    if cursor.rowcount == 0:
        get_db().rollback()
        return fail("Регулярное правило не найдено", 404)
    get_db().commit()
    return ok()


@api_bp.get("/activity")
def activity():
    rows = get_db().execute(
        """SELECT l.*, u.login actor_login FROM audit_log l
           LEFT JOIN users u ON u.id = l.actor_user_id
           ORDER BY l.created_at DESC, l.id DESC LIMIT 50"""
    ).fetchall()
    return ok([dict(row) for row in rows])
