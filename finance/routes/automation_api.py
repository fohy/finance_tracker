from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import Any

from flask import Blueprint, jsonify, request

from ..auth import current_user_id
from ..db import get_db
from ..import_service import (
    MAX_IMPORT_BYTES,
    parse_statement,
    resolve_category,
    transaction_fingerprint,
)
from ..services import get_summary, parse_date
from ..transaction_service import create_transaction

automation_api_bp = Blueprint("automation_api", __name__)


def ok(data: Any = None, status: int = 200):
    return jsonify({"ok": True, "data": data}), status


def fail(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


@automation_api_bp.errorhandler(ValueError)
def value_error(error: ValueError):
    return fail(str(error))


def _upload() -> tuple[str, bytes]:
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        raise ValueError("Выберите файл выписки")
    raw = uploaded.stream.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise ValueError("Файл больше допустимых 5 МБ")
    return uploaded.filename, raw


def _import_destination() -> tuple[int, int | None]:
    try:
        account_id = int(request.form.get("account_id", ""))
    except ValueError as exc:
        raise ValueError("Выберите счёт для импорта") from exc
    person_id = int(request.form["person_id"]) if request.form.get("person_id") else None
    db = get_db()
    account = db.execute(
        "SELECT account_type FROM accounts WHERE id = ? AND is_active = 1", (account_id,)
    ).fetchone()
    if not account:
        raise ValueError("Выберите активный счёт")
    if account["account_type"] == "currency":
        raise ValueError("Импорт валютных выписок пока не поддерживается без исторического курса")
    if person_id is not None and not db.execute("SELECT 1 FROM people WHERE id = ?", (person_id,)).fetchone():
        raise ValueError("Участник не найден")
    return account_id, person_id


@automation_api_bp.post("/imports/preview")
def preview_import():
    account_id, person_id = _import_destination()
    filename, raw = _upload()
    parsed = parse_statement(filename, raw)
    db = get_db()
    items = []
    for row in parsed["rows"][:100]:
        item = dict(row)
        fingerprint = transaction_fingerprint(row, account_id, person_id)
        item["duplicate"] = db.execute(
            "SELECT 1 FROM imported_transactions WHERE fingerprint = ?", (fingerprint,)
        ).fetchone() is not None
        item["category_id"] = resolve_category(row["category"], row["tx_type"])
        items.append(item)
    return ok({
        "filename": filename,
        "items": items,
        "errors": parsed["errors"][:100],
        "total_rows": parsed["total_rows"],
        "valid_rows": len(parsed["rows"]),
        "preview_limited": len(parsed["rows"]) > 100,
    })


@automation_api_bp.post("/imports/confirm")
def confirm_import():
    account_id, person_id = _import_destination()
    filename, raw = _upload()
    parsed = parse_statement(filename, raw)
    db = get_db()
    imported = 0
    duplicates = 0
    created_ids: list[int] = []
    try:
        batch = db.execute(
            "INSERT INTO import_batches(filename, account_id, person_id) VALUES (?, ?, ?)",
            (filename, account_id, person_id),
        )
        for row in parsed["rows"]:
            fingerprint = transaction_fingerprint(row, account_id, person_id)
            if db.execute(
                "SELECT 1 FROM imported_transactions WHERE fingerprint = ?", (fingerprint,)
            ).fetchone():
                duplicates += 1
                continue
            tx_id = create_transaction(
                tx_type=row["tx_type"], amount=float(row["amount"]), tx_date=row["tx_date"],
                account_id=account_id, target_account_id=None,
                category_id=resolve_category(row["category"], row["tx_type"]),
                person_id=person_id, note=row["note"], actor_user_id=current_user_id(), commit=False,
            )
            db.execute(
                "INSERT INTO imported_transactions(batch_id, transaction_id, fingerprint) VALUES (?, ?, ?)",
                (batch.lastrowid, tx_id, fingerprint),
            )
            created_ids.append(tx_id)
            imported += 1
        skipped = duplicates + len(parsed["errors"])
        db.execute(
            "UPDATE import_batches SET imported_count = ?, skipped_count = ? WHERE id = ?",
            (imported, skipped, batch.lastrowid),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok({
        "batch_id": batch.lastrowid, "imported": imported, "duplicates": duplicates,
        "invalid": len(parsed["errors"]), "skipped": skipped, "transaction_ids": created_ids,
    }, 201)


@automation_api_bp.get("/category-rules")
def list_category_rules():
    rows = get_db().execute(
        """SELECT r.*, c.name category_name, c.type category_type FROM category_rules r
           JOIN categories c ON c.id = r.category_id ORDER BY r.priority, r.id"""
    ).fetchall()
    return ok([dict(row) for row in rows])


def _rule_values(data: dict[str, Any], current: Any = None) -> tuple[str, int, int, int]:
    pattern = str(data.get("pattern", current["pattern"] if current else "")).strip()
    if not pattern or len(pattern) > 200:
        raise ValueError("Шаблон должен содержать от 1 до 200 символов")
    try:
        category_id = int(data.get("category_id", current["category_id"] if current else ""))
        priority = int(data.get("priority", current["priority"] if current else 100))
    except (TypeError, ValueError) as exc:
        raise ValueError("Выберите категорию и числовой приоритет") from exc
    if not 0 <= priority <= 10_000:
        raise ValueError("Приоритет должен быть от 0 до 10000")
    if not get_db().execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone():
        raise ValueError("Категория не найдена")
    raw_active = data.get("is_active", current["is_active"] if current else True)
    active = int(str(raw_active).lower() in {"1", "true", "yes", "on"})
    return pattern, category_id, priority, active


@automation_api_bp.post("/category-rules")
def create_category_rule():
    values = _rule_values(request.get_json(silent=True) or {})
    cursor = get_db().execute(
        "INSERT INTO category_rules(pattern, category_id, priority, is_active) VALUES (?, ?, ?, ?)", values
    )
    get_db().commit()
    return ok({"id": cursor.lastrowid}, 201)


@automation_api_bp.patch("/category-rules/<int:rule_id>")
def update_category_rule(rule_id: int):
    current = get_db().execute("SELECT * FROM category_rules WHERE id = ?", (rule_id,)).fetchone()
    if not current:
        return fail("Правило не найдено", 404)
    values = _rule_values(request.get_json(silent=True) or {}, current)
    get_db().execute(
        "UPDATE category_rules SET pattern = ?, category_id = ?, priority = ?, is_active = ? WHERE id = ?",
        (*values, rule_id),
    )
    get_db().commit()
    return ok()


@automation_api_bp.delete("/category-rules/<int:rule_id>")
def delete_category_rule(rule_id: int):
    cursor = get_db().execute("DELETE FROM category_rules WHERE id = ?", (rule_id,))
    get_db().commit()
    return ok() if cursor.rowcount else fail("Правило не найдено", 404)


def _salary_plan(anchor: str | None = None) -> dict[str, Any]:
    summary = get_summary("month", anchor)
    return {"start": summary["start"], "end": summary["end"], **summary["allocation_plan"]}


@automation_api_bp.get("/salary-plan")
def salary_plan():
    return ok(_salary_plan(request.args.get("anchor")))


@automation_api_bp.post("/salary-plan/apply")
def apply_salary_plan():
    data = request.get_json(silent=True) or {}
    if data.get("confirm") is not True:
        raise ValueError("Подтвердите создание переводов")
    plan = _salary_plan(data.get("anchor"))
    source_id = plan["source_account_id"]
    if not source_id:
        raise ValueError("Нет активного основного счёта")
    db = get_db()
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    destinations = {
        "savings": plan["savings_account_id"],
        "currency": plan["currency_account_id"],
    }
    required = sum(
        float(bucket["remaining"])
        for bucket in plan["buckets"]
        if bucket["key"] in destinations and destinations[bucket["key"]]
    )
    source = db.execute("SELECT balance FROM accounts WHERE id = ?", (source_id,)).fetchone()
    if not source or float(source["balance"]) + 0.005 < required:
        raise ValueError("На основном счёте недостаточно средств для всех переводов плана")
    try:
        for bucket in plan["buckets"]:
            key = bucket["key"]
            if key == "spending":
                skipped.append({"bucket": key, "reason": "Сумма остаётся на основном счёте"})
                continue
            amount = float(bucket["remaining"])
            destination_id = destinations[key]
            if amount <= 0.005:
                skipped.append({"bucket": key, "reason": "План уже выполнен"})
                continue
            if not destination_id:
                skipped.append({"bucket": key, "reason": "Нет активного счёта назначения"})
                continue
            marker = f"Зарплатный план {plan['start'][:7]} · {key}"
            tx_id = create_transaction(
                tx_type="transfer", amount=amount, tx_date=date.today().isoformat(),
                account_id=source_id, target_account_id=destination_id, category_id=None,
                person_id=None, note=marker, actor_user_id=current_user_id(), commit=False,
            )
            created.append({"id": tx_id, "bucket": key, "amount": round(amount, 2)})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok({"created": created, "skipped": skipped})


def _advance(value: date, frequency: str) -> date:
    if frequency == "weekly":
        return value + timedelta(days=7)
    month = value.month % 12 + 1
    year = value.year + value.month // 12
    return value.replace(year=year, month=month, day=min(value.day, monthrange(year, month)[1]))


@automation_api_bp.get("/upcoming-payments")
def upcoming_payments():
    days = int(request.args.get("days", 30))
    if days not in {30, 60}:
        raise ValueError("Горизонт должен быть 30 или 60 дней")
    today = date.today()
    horizon = today + timedelta(days=days)
    occurrences: list[dict[str, Any]] = []
    rows = get_db().execute(
        "SELECT * FROM recurring_transactions WHERE is_active = 1 ORDER BY next_date, id"
    ).fetchall()
    for row in rows:
        occurrence = parse_date(row["next_date"])
        generated = 0
        while occurrence <= horizon and generated < 100:
            occurrences.append({
                "recurring_id": row["id"], "title": row["title"], "tx_type": row["tx_type"],
                "amount": float(row["amount"]), "date": occurrence.isoformat(),
                "status": "overdue" if occurrence < today else "upcoming",
                "week": f"{occurrence.isocalendar().year}-W{occurrence.isocalendar().week:02d}",
                "month": occurrence.strftime("%Y-%m"),
            })
            occurrence = _advance(occurrence, row["frequency"])
            generated += 1
    occurrences.sort(key=lambda item: (item["date"], item["recurring_id"]))
    totals_by_week: dict[str, float] = {}
    totals_by_month: dict[str, float] = {}
    for item in occurrences:
        if item["tx_type"] != "expense":
            continue
        totals_by_week[item["week"]] = round(totals_by_week.get(item["week"], 0) + item["amount"], 2)
        totals_by_month[item["month"]] = round(totals_by_month.get(item["month"], 0) + item["amount"], 2)
    return ok({"days": days, "items": occurrences, "totals_by_week": totals_by_week, "totals_by_month": totals_by_month})
