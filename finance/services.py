from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any

from .db import get_db


def parse_date(value: str | None, default: date | None = None) -> date:
    if not value:
        return default or date.today()
    return datetime.strptime(value, "%Y-%m-%d").date()


def period_bounds(period: str, anchor: str | None = None) -> tuple[date, date]:
    if period not in {"day", "week", "month"}:
        raise ValueError("Период должен быть day, week или month")
    current = parse_date(anchor)
    if period == "day":
        return current, current
    if period == "week":
        start = current - timedelta(days=current.weekday())
        return start, start + timedelta(days=6)
    start = current.replace(day=1)
    end = current.replace(day=monthrange(current.year, current.month)[1])
    return start, end


def previous_period(start: date, end: date) -> tuple[date, date]:
    span = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    return previous_end - timedelta(days=span - 1), previous_end


def shift_period(period: str, anchor: str | None, direction: int) -> str:
    current = parse_date(anchor)
    if period == "day":
        shifted = current + timedelta(days=direction)
    elif period == "week":
        shifted = current + timedelta(days=7 * direction)
    else:
        month = current.month - 1 + direction
        year = current.year + month // 12
        month = month % 12 + 1
        day = min(current.day, monthrange(year, month)[1])
        shifted = current.replace(year=year, month=month, day=day)
    return shifted.isoformat()


def accrue_interest() -> None:
    db = get_db()
    today = date.today()
    accounts = db.execute(
        "SELECT * FROM accounts WHERE kind = 'investment' AND annual_rate > 0"
    ).fetchall()
    changed = False
    for account in accounts:
        last = parse_date(account["last_accrual_date"], today)
        days = (today - last).days
        if days <= 0:
            continue
        daily_rate = float(account["annual_rate"]) / 100 / 365
        interest = float(account["balance"]) * ((1 + daily_rate) ** days - 1)
        if interest > 0.005:
            db.execute(
                "UPDATE accounts SET balance = balance + ?, last_accrual_date = ? WHERE id = ?",
                (interest, today.isoformat(), account["id"]),
            )
            db.execute(
                """INSERT INTO transactions(tx_type, amount, tx_date, account_id, note)
                   VALUES ('interest', ?, ?, ?, ?)""",
                (interest, today.isoformat(), account["id"], f"Автоначисление за {days} дн."),
            )
            changed = True
    if changed:
        db.commit()


def setting(key: str, default: float = 0) -> float:
    row = get_db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    try:
        return float(row["value"]) if row else default
    except (TypeError, ValueError):
        return default


def get_summary(period: str, anchor: str | None = None, person_id: int | None = None) -> dict[str, Any]:
    accrue_interest()
    db = get_db()
    start, end = period_bounds(period, anchor)
    prev_start, prev_end = previous_period(start, end)

    person_filter = " AND person_id = ?" if person_id else ""
    params: list[Any] = [start.isoformat(), end.isoformat()]
    prev_params: list[Any] = [prev_start.isoformat(), prev_end.isoformat()]
    if person_id:
        params.append(person_id)
        prev_params.append(person_id)

    def aggregate(bounds_params: list[Any]) -> dict[str, float]:
        row = db.execute(
            f"""SELECT
                COALESCE(SUM(CASE WHEN tx_type = 'income' THEN amount ELSE 0 END), 0) AS income,
                COALESCE(SUM(CASE WHEN tx_type = 'expense' THEN amount ELSE 0 END), 0) AS expense,
                COALESCE(SUM(CASE WHEN tx_type = 'transfer' THEN amount ELSE 0 END), 0) AS invested,
                COALESCE(SUM(CASE WHEN tx_type = 'interest' THEN amount ELSE 0 END), 0) AS interest
            FROM transactions
            WHERE tx_date BETWEEN ? AND ? {person_filter}""",
            bounds_params,
        ).fetchone()
        return {k: round(float(row[k]), 2) for k in row.keys()}

    current = aggregate(params)
    previous = aggregate(prev_params)
    current["net"] = round(current["income"] - current["expense"], 2)
    previous["net"] = round(previous["income"] - previous["expense"], 2)

    accounts = [dict(r) for r in db.execute("SELECT * FROM accounts ORDER BY kind")]
    life_balance = sum(a["balance"] for a in accounts if a["kind"] == "life")
    investment_balance = sum(a["balance"] for a in accounts if a["kind"] == "investment")

    def delta(key: str) -> float:
        old = previous[key]
        if old == 0:
            return 100.0 if current[key] > 0 else 0.0
        return round((current[key] - old) / abs(old) * 100, 1)

    score = correctness_score(current, period, start, end)
    forecast = build_forecast(person_id)

    return {
        "period": period,
        "anchor": (parse_date(anchor)).isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "current": current,
        "previous": previous,
        "delta": {k: delta(k) for k in ("income", "expense", "net", "invested")},
        "accounts": accounts,
        "life_balance": round(life_balance, 2),
        "investment_balance": round(investment_balance, 2),
        "score": score,
        "forecast": forecast,
    }


def correctness_score(metrics: dict[str, float], period: str, start: date, end: date) -> dict[str, Any]:
    income = metrics["income"]
    expense = metrics["expense"]
    invested = metrics["invested"]
    net = metrics["net"]
    target_pct = setting("investment_target_percent", 20)
    monthly_budget = setting("monthly_life_budget", 90000)
    period_days = (end - start).days + 1
    budget = monthly_budget * period_days / 30.44

    savings_rate = ((income - expense) / income * 100) if income else 0
    investment_rate = (invested / income * 100) if income else 0
    budget_score = max(0, min(100, 100 - max(0, expense - budget) / max(budget, 1) * 100))
    savings_score = max(0, min(100, savings_rate * 3.3))
    investment_score = max(0, min(100, investment_rate / max(target_pct, 1) * 100))
    stability_score = 100 if net >= 0 else max(0, 100 + net / max(expense, 1) * 100)
    score = round(budget_score * 0.3 + savings_score * 0.25 + investment_score * 0.3 + stability_score * 0.15)

    if score >= 80:
        label, tone = "Отличный курс", "good"
    elif score >= 60:
        label, tone = "Всё в целом правильно", "ok"
    elif score >= 40:
        label, tone = "Нужна корректировка", "warn"
    else:
        label, tone = "Финансовый риск", "bad"

    tips: list[str] = []
    if expense > budget:
        tips.append(f"Расходы выше планового лимита на {round(expense - budget):,.0f} ₽".replace(",", " "))
    if investment_rate < target_pct and income > 0:
        tips.append(f"До цели инвестирования не хватает {round(target_pct - investment_rate, 1)} п.п.")
    if net < 0:
        tips.append("Расходы превышают доходы — сократите необязательные траты")
    if not tips:
        tips.append("Темп накоплений и расходов соответствует выбранной стратегии")

    return {
        "value": score,
        "label": label,
        "tone": tone,
        "savings_rate": round(savings_rate, 1),
        "investment_rate": round(investment_rate, 1),
        "budget": round(budget, 2),
        "tips": tips,
    }


def build_forecast(person_id: int | None = None) -> dict[str, Any]:
    db = get_db()
    person_filter = " AND person_id = ?" if person_id else ""
    params: list[Any] = []
    if person_id:
        params.append(person_id)
    rows = db.execute(
        f"""SELECT substr(tx_date, 1, 7) AS month,
            SUM(CASE WHEN tx_type='income' THEN amount ELSE 0 END) income,
            SUM(CASE WHEN tx_type='expense' THEN amount ELSE 0 END) expense,
            SUM(CASE WHEN tx_type='transfer' THEN amount ELSE 0 END) invested
        FROM transactions
        WHERE tx_date >= date('now', '-5 months', 'start of month') {person_filter}
        GROUP BY substr(tx_date, 1, 7)
        ORDER BY month""",
        params,
    ).fetchall()
    data = [dict(r) for r in rows]
    if not data:
        return {"income": 0, "expense": 0, "net": 0, "invested": 0, "months": []}

    tail = data[-3:]
    def average(key: str) -> float:
        return sum(float(row[key] or 0) for row in tail) / len(tail)
    income = average("income")
    expense = average("expense")
    invested = average("invested")
    return {
        "income": round(income, 2),
        "expense": round(expense, 2),
        "net": round(income - expense, 2),
        "invested": round(invested, 2),
        "months": data,
    }


def category_breakdown(period: str, anchor: str | None, person_id: int | None = None) -> list[dict[str, Any]]:
    db = get_db()
    start, end = period_bounds(period, anchor)
    person_filter = " AND t.person_id = ?" if person_id else ""
    params: list[Any] = [start.isoformat(), end.isoformat()]
    if person_id:
        params.append(person_id)
    rows = db.execute(
        f"""SELECT COALESCE(c.name, 'Без категории') name, COALESCE(c.icon, '•') icon,
            COALESCE(c.color, '#8b91a7') color, SUM(t.amount) amount
        FROM transactions t
        LEFT JOIN categories c ON c.id=t.category_id
        WHERE t.tx_type='expense' AND t.tx_date BETWEEN ? AND ? {person_filter}
        GROUP BY c.id, c.name, c.icon, c.color
        ORDER BY amount DESC""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def trend_series(period: str, anchor: str | None, person_id: int | None = None) -> list[dict[str, Any]]:
    db = get_db()
    start, end = period_bounds(period, anchor)
    person_filter = " AND person_id = ?" if person_id else ""
    params: list[Any] = [start.isoformat(), end.isoformat()]
    if person_id:
        params.append(person_id)
    group_expr = "tx_date" if period in {"day", "week"} else "strftime('%Y-%m-%d', tx_date)"
    rows = db.execute(
        f"""SELECT {group_expr} label,
            SUM(CASE WHEN tx_type='income' THEN amount ELSE 0 END) income,
            SUM(CASE WHEN tx_type='expense' THEN amount ELSE 0 END) expense,
            SUM(CASE WHEN tx_type='transfer' THEN amount ELSE 0 END) invested
        FROM transactions
        WHERE tx_date BETWEEN ? AND ? {person_filter}
        GROUP BY {group_expr}
        ORDER BY label""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def purchase_plan(item: dict[str, Any], available_monthly: float) -> dict[str, Any]:
    remaining = max(0, float(item["cost"]) - float(item["saved_amount"]))
    target = parse_date(item.get("target_date"), date.today() + timedelta(days=90))
    days = max(1, (target - date.today()).days)
    daily = remaining / days
    weekly = daily * 7
    monthly = daily * 30.44
    affordability = "safe" if monthly <= max(0, available_monthly * 0.5) else "tight" if monthly <= max(0, available_monthly) else "risk"
    return {
        **item,
        "remaining": round(remaining, 2),
        "days_left": days,
        "daily_save": round(daily, 2),
        "weekly_save": round(weekly, 2),
        "monthly_save": round(monthly, 2),
        "affordability": affordability,
        "progress": round(min(100, float(item["saved_amount"]) / max(float(item["cost"]), 1) * 100), 1),
    }


def available_for_purchases() -> float:
    forecast = build_forecast()
    target_pct = setting("investment_target_percent", 20) / 100
    protected_investment = forecast["income"] * target_pct
    return max(0, forecast["income"] - forecast["expense"] - protected_investment)


def goal_progress(item: dict[str, Any]) -> dict[str, Any]:
    remaining = max(0, float(item["target_amount"]) - float(item["current_amount"]))
    target = parse_date(item.get("target_date"), date.today() + timedelta(days=365))
    days = max(1, (target - date.today()).days)
    return {
        **item,
        "remaining": round(remaining, 2),
        "days_left": days,
        "monthly_needed": round(remaining / max(1, days / 30.44), 2),
        "progress": round(min(100, float(item["current_amount"]) / max(float(item["target_amount"]), 1) * 100), 1),
    }


def category_budget_status(anchor: str | None = None) -> list[dict[str, Any]]:
    """Return monthly category limits with actual spending and an actionable status."""
    current = parse_date(anchor)
    start = current.replace(day=1).isoformat()
    end = current.replace(day=monthrange(current.year, current.month)[1]).isoformat()
    rows = get_db().execute(
        """SELECT b.id, b.category_id, b.monthly_limit, c.name, c.icon, c.color,
            COALESCE(SUM(t.amount), 0) spent
           FROM category_budgets b
           JOIN categories c ON c.id = b.category_id
           LEFT JOIN transactions t ON t.category_id = b.category_id
               AND t.tx_type = 'expense' AND t.tx_date BETWEEN ? AND ?
           GROUP BY b.id, b.category_id, b.monthly_limit, c.name, c.icon, c.color
           ORDER BY (COALESCE(SUM(t.amount), 0) / b.monthly_limit) DESC""",
        (start, end),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["spent"] = round(float(item["spent"]), 2)
        item["monthly_limit"] = round(float(item["monthly_limit"]), 2)
        item["remaining"] = round(item["monthly_limit"] - item["spent"], 2)
        item["progress"] = round(item["spent"] / item["monthly_limit"] * 100, 1)
        item["status"] = "over" if item["progress"] > 100 else "warning" if item["progress"] >= 80 else "ok"
        result.append(item)
    return result
