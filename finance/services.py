from __future__ import annotations

from calendar import isleap, monthrange
from datetime import date, datetime, timedelta
from typing import Any

from .db import get_db


_INVESTED_FLOW_SQL = """
    CASE
        WHEN t.tx_type = 'income' AND sa.account_type IN ('investment', 'currency')
            THEN t.amount * CASE WHEN sa.account_type = 'currency' THEN sa.exchange_rate ELSE 1 END
        ELSE 0
    END
    + CASE
        WHEN t.tx_type = 'transfer' AND sa.account_type IN ('investment', 'currency')
            THEN -t.amount * CASE WHEN sa.account_type = 'currency' THEN sa.exchange_rate ELSE 1 END
        ELSE 0
    END
    + CASE
        WHEN t.tx_type = 'transfer' AND ta.account_type IN ('investment', 'currency')
            THEN COALESCE(t.target_amount, t.amount)
                * CASE WHEN ta.account_type = 'currency' THEN ta.exchange_rate ELSE 1 END
        ELSE 0
    END
"""


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
    previous_end = start - timedelta(days=1)
    if start.day == 1 and end.day == monthrange(end.year, end.month)[1]:
        return previous_end.replace(day=1), previous_end
    span = (end - start).days + 1
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


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _next_month(value: date) -> date:
    return (value.replace(day=28) + timedelta(days=4)).replace(day=1)


def _ledger_balance_before(account_id: int, before: date) -> float:
    row = get_db().execute(
        """SELECT COALESCE(SUM(
               CASE
                 WHEN account_id = ? AND tx_type IN ('income', 'interest') THEN amount
                 WHEN account_id = ? AND tx_type IN ('expense', 'transfer') THEN -amount
                 WHEN target_account_id = ? AND tx_type = 'transfer' THEN COALESCE(target_amount, amount)
                 ELSE 0
               END
           ), 0) balance
           FROM transactions WHERE tx_date < ?""",
        (account_id, account_id, account_id, before.isoformat()),
    ).fetchone()
    return float(row["balance"])


def calculate_monthly_interest(account_id: int, start: date, annual_rate: float) -> float:
    """Calculate simple daily interest on each day's closing ledger balance."""
    db = get_db()
    end = start.replace(day=monthrange(start.year, start.month)[1])
    daily_rows = db.execute(
        """SELECT tx_date, SUM(
               CASE
                 WHEN account_id = ? AND tx_type IN ('income', 'interest') THEN amount
                 WHEN account_id = ? AND tx_type IN ('expense', 'transfer') THEN -amount
                 WHEN target_account_id = ? AND tx_type = 'transfer' THEN COALESCE(target_amount, amount)
                 ELSE 0
               END
           ) delta
           FROM transactions
           WHERE tx_date BETWEEN ? AND ? AND (account_id = ? OR target_account_id = ?)
           GROUP BY tx_date""",
        (account_id, account_id, account_id, start.isoformat(), end.isoformat(), account_id, account_id),
    ).fetchall()
    deltas = {row["tx_date"]: float(row["delta"]) for row in daily_rows}
    rate_rows = db.execute(
        """SELECT effective_date, annual_rate FROM account_rate_history
           WHERE account_id = ? AND effective_date <= ? ORDER BY effective_date""",
        (account_id, end.isoformat()),
    ).fetchall()
    rates = [(parse_date(row["effective_date"]), float(row["annual_rate"])) for row in rate_rows]
    balance = _ledger_balance_before(account_id, start)
    interest = 0.0
    current_rate = annual_rate if not rates else 0.0
    rate_index = 0
    day = start
    while day <= end:
        balance += deltas.get(day.isoformat(), 0.0)
        while rate_index < len(rates) and rates[rate_index][0] <= day:
            current_rate = rates[rate_index][1]
            rate_index += 1
        days_in_year = 366 if isleap(day.year) else 365
        interest += max(0.0, balance) * current_rate / 100 / days_in_year
        day += timedelta(days=1)
    return round(interest, 2)


def accrue_interest(as_of: date | None = None) -> None:
    """Post one interest transaction for each completed, not-yet-posted month."""
    db = get_db()
    today = as_of or date.today()
    current_month = _month_start(today)
    accounts = db.execute(
        """SELECT * FROM accounts
           WHERE is_active = 1 AND interest_enabled = 1 AND annual_rate > 0
             AND account_type IN ('savings', 'deposit', 'investment')"""
    ).fetchall()
    changed = False
    for account in accounts:
        last_key = account["interest_last_posted_month"]
        if not last_key:
            previous = current_month - timedelta(days=1)
            db.execute(
                "UPDATE accounts SET interest_last_posted_month = ? WHERE id = ?",
                (previous.strftime("%Y-%m"), account["id"]),
            )
            changed = True
            continue
        period = _next_month(parse_date(f"{last_key}-01"))
        processed = 0
        while period < current_month and processed < 24:
            period_end = period.replace(day=monthrange(period.year, period.month)[1])
            interest = calculate_monthly_interest(account["id"], period, float(account["annual_rate"]))
            if interest > 0.005:
                db.execute(
                    "UPDATE accounts SET balance = balance + ? WHERE id = ?",
                    (interest, account["id"]),
                )
                db.execute(
                    """INSERT INTO transactions(tx_type, amount, tx_date, account_id, note)
                       VALUES ('interest', ?, ?, ?, ?)""",
                    (interest, period_end.isoformat(), account["id"], f"Проценты за {period:%m.%Y}"),
                )
            db.execute(
                """UPDATE accounts
                   SET last_accrual_date = ?, interest_last_posted_month = ? WHERE id = ?""",
                (period_end.isoformat(), period.strftime("%Y-%m"), account["id"]),
            )
            changed = True
            period = _next_month(period)
            processed += 1
    if changed:
        db.commit()


def setting(key: str, default: float = 0) -> float:
    row = get_db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    try:
        return float(row["value"]) if row else default
    except (TypeError, ValueError):
        return default


def setting_text(key: str, default: str = "") -> str:
    row = get_db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else default


def get_summary(period: str, anchor: str | None = None, person_id: int | None = None) -> dict[str, Any]:
    accrue_interest()
    db = get_db()
    start, end = period_bounds(period, anchor)
    prev_start, prev_end = previous_period(start, end)

    person_filter = " AND t.person_id = ?" if person_id else ""
    params: list[Any] = [start.isoformat(), end.isoformat()]
    prev_params: list[Any] = [prev_start.isoformat(), prev_end.isoformat()]
    if person_id:
        params.append(person_id)
        prev_params.append(person_id)

    def aggregate(bounds_params: list[Any]) -> dict[str, float]:
        row = db.execute(
            f"""SELECT
                COALESCE(SUM(CASE WHEN t.tx_type = 'income' THEN t.amount ELSE 0 END), 0) AS income,
                COALESCE(SUM(CASE WHEN t.tx_type = 'expense' THEN t.amount ELSE 0 END), 0) AS expense,
                COALESCE(SUM({_INVESTED_FLOW_SQL}), 0) AS invested,
                COALESCE(SUM(CASE
                    WHEN t.tx_type = 'transfer' AND ta.account_type IN ('savings', 'deposit', 'investment') THEN t.amount
                    WHEN t.tx_type = 'income' AND sa.account_type IN ('savings', 'deposit', 'investment') THEN t.amount
                    ELSE 0 END), 0) AS saved,
                COALESCE(SUM(CASE
                    WHEN t.tx_type = 'transfer' AND ta.account_type = 'currency' THEN t.amount
                    WHEN t.tx_type = 'income' AND sa.account_type = 'currency' THEN t.amount
                    ELSE 0 END), 0) AS currency_reserved,
                COALESCE(SUM(CASE WHEN t.tx_type = 'interest' THEN t.amount ELSE 0 END), 0) AS interest
            FROM transactions t
            LEFT JOIN accounts sa ON sa.id = t.account_id
            LEFT JOIN accounts ta ON ta.id = t.target_account_id
            WHERE t.tx_date BETWEEN ? AND ? {person_filter}""",
            bounds_params,
        ).fetchone()
        return {k: round(float(row[k]), 2) for k in row.keys()}

    current = aggregate(params)
    previous = aggregate(prev_params)
    current["net"] = round(current["income"] - current["expense"], 2)
    previous["net"] = round(previous["income"] - previous["expense"], 2)

    accounts = [dict(r) for r in db.execute("SELECT * FROM accounts ORDER BY is_active DESC, account_type, name")]
    for account in accounts:
        rate = float(account.get("exchange_rate") or 1)
        account["base_equivalent"] = round(float(account["balance"]) * rate, 2)
    life_balance = sum(a["balance"] for a in accounts if a["account_type"] in {"checking", "cash"})
    savings_balance = sum(a["balance"] for a in accounts if a["account_type"] in {"savings", "deposit"})
    currency_balance = sum(a["base_equivalent"] for a in accounts if a["account_type"] == "currency")
    investment_balance = sum(a["balance"] for a in accounts if a["account_type"] == "investment")
    invested_balance = savings_balance + currency_balance + investment_balance

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
        "previous_start": prev_start.isoformat(),
        "previous_end": prev_end.isoformat(),
        "current": current,
        "previous": previous,
        "delta": {k: delta(k) for k in ("income", "expense", "net", "invested")},
        "accounts": accounts,
        "life_balance": round(life_balance, 2),
        "savings_balance": round(savings_balance, 2),
        "currency_balance": round(currency_balance, 2),
        "investment_balance": round(investment_balance, 2),
        "invested_balance": round(invested_balance, 2),
        "total_capital": round(life_balance + invested_balance, 2),
        "score": score,
        "forecast": forecast,
    }


def correctness_score(metrics: dict[str, float], period: str, start: date, end: date) -> dict[str, Any]:
    income = metrics["income"]
    expense = metrics["expense"]
    invested = metrics["saved"]
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
        currency = setting_text("currency", "₽")
        tips.append(
            f"Расходы выше планового лимита на {round(expense - budget):,.0f} {currency}".replace(",", " ")
        )
    if investment_rate < target_pct and income > 0:
        tips.append(f"До цели накоплений не хватает {round(target_pct - investment_rate, 1)} п.п.")
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
    person_filter = " AND t.person_id = ?" if person_id else ""
    params: list[Any] = []
    if person_id:
        params.append(person_id)
    rows = db.execute(
        f"""SELECT substr(t.tx_date, 1, 7) AS month,
            SUM(CASE WHEN t.tx_type='income' THEN t.amount ELSE 0 END) income,
            SUM(CASE WHEN t.tx_type='expense' THEN t.amount ELSE 0 END) expense,
            SUM({_INVESTED_FLOW_SQL}) invested
        FROM transactions t
        LEFT JOIN accounts sa ON sa.id = t.account_id
        LEFT JOIN accounts ta ON ta.id = t.target_account_id
        WHERE t.tx_date >= date('now', '-5 months', 'start of month') {person_filter}
        GROUP BY substr(t.tx_date, 1, 7)
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
        f"""SELECT COALESCE(c.name, 'Без категории') name, COALESCE(c.icon, 'category') icon,
            COALESCE(c.color, '#8b91a7') color, SUM(t.amount) amount,
            COUNT(*) transaction_count, AVG(t.amount) average_transaction
        FROM transactions t
        LEFT JOIN categories c ON c.id=t.category_id
        WHERE t.tx_type='expense' AND t.tx_date BETWEEN ? AND ? {person_filter}
        GROUP BY c.id, c.name, c.icon, c.color
        ORDER BY amount DESC""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def spending_statistics(period: str, anchor: str | None, person_id: int | None = None) -> dict[str, Any]:
    db = get_db()
    start, end = period_bounds(period, anchor)
    person_filter = " AND t.person_id = ?" if person_id else ""
    params: list[Any] = [start.isoformat(), end.isoformat()]
    if person_id:
        params.append(person_id)

    totals = db.execute(
        f"""SELECT COUNT(*) transaction_count, COALESCE(SUM(t.amount), 0) total,
            COALESCE(AVG(t.amount), 0) average_transaction, COUNT(DISTINCT t.tx_date) active_days
        FROM transactions t
        WHERE t.tx_type='expense' AND t.tx_date BETWEEN ? AND ? {person_filter}""",
        params,
    ).fetchone()
    largest = db.execute(
        f"""SELECT t.amount, t.tx_date, COALESCE(c.name, 'Без категории') category_name,
            COALESCE(c.icon, 'category') category_icon
        FROM transactions t
        LEFT JOIN categories c ON c.id = t.category_id
        WHERE t.tx_type='expense' AND t.tx_date BETWEEN ? AND ? {person_filter}
        ORDER BY t.amount DESC, t.tx_date DESC, t.id DESC
        LIMIT 1""",
        params,
    ).fetchone()
    total = float(totals["total"])
    effective_end = min(end, date.today()) if start <= date.today() else end
    period_days = max(1, (effective_end - start).days + 1)
    return {
        "total": round(total, 2),
        "average_per_day": round(total / period_days, 2),
        "average_transaction": round(float(totals["average_transaction"]), 2),
        "transaction_count": totals["transaction_count"],
        "active_days": totals["active_days"],
        "largest": dict(largest) if largest else None,
    }


def trend_series(period: str, anchor: str | None, person_id: int | None = None) -> list[dict[str, Any]]:
    db = get_db()
    start, end = period_bounds(period, anchor)
    person_filter = " AND t.person_id = ?" if person_id else ""
    params: list[Any] = [start.isoformat(), end.isoformat()]
    if person_id:
        params.append(person_id)
    group_expr = "tx_date" if period in {"day", "week"} else "strftime('%Y-%m-%d', tx_date)"
    rows = db.execute(
        f"""SELECT {group_expr} label,
            SUM(CASE WHEN t.tx_type='income' THEN t.amount ELSE 0 END) income,
            SUM(CASE WHEN t.tx_type='expense' THEN t.amount ELSE 0 END) expense,
            SUM({_INVESTED_FLOW_SQL}) invested
        FROM transactions t
        LEFT JOIN accounts sa ON sa.id = t.account_id
        LEFT JOIN accounts ta ON ta.id = t.target_account_id
        WHERE t.tx_date BETWEEN ? AND ? {person_filter}
        GROUP BY {group_expr}
        ORDER BY label""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def investment_balance_series() -> list[dict[str, Any]]:
    """Return the ledger history of investment and currency account balances in base currency."""
    db = get_db()
    current_row = db.execute(
        """SELECT COALESCE(SUM(balance * CASE WHEN account_type = 'currency' THEN exchange_rate ELSE 1 END), 0) balance
           FROM accounts WHERE account_type IN ('investment', 'currency')"""
    ).fetchone()
    current_balance = float(current_row["balance"])
    rows = db.execute(
        """SELECT t.tx_date label, SUM(
               CASE
                   WHEN sa.account_type IN ('investment', 'currency') AND t.tx_type IN ('income', 'interest')
                       THEN t.amount * CASE WHEN sa.account_type = 'currency' THEN sa.exchange_rate ELSE 1 END
                   WHEN sa.account_type IN ('investment', 'currency') AND t.tx_type IN ('expense', 'transfer')
                       THEN -t.amount * CASE WHEN sa.account_type = 'currency' THEN sa.exchange_rate ELSE 1 END
                   ELSE 0
               END
               + CASE
                   WHEN ta.account_type IN ('investment', 'currency') AND t.tx_type = 'transfer'
                       THEN COALESCE(t.target_amount, t.amount)
                           * CASE WHEN ta.account_type = 'currency' THEN ta.exchange_rate ELSE 1 END
                   ELSE 0
               END
           ) delta
           FROM transactions t
           LEFT JOIN accounts sa ON sa.id = t.account_id
           LEFT JOIN accounts ta ON ta.id = t.target_account_id
           WHERE sa.account_type IN ('investment', 'currency')
              OR ta.account_type IN ('investment', 'currency')
           GROUP BY t.tx_date
           ORDER BY t.tx_date"""
    ).fetchall()
    if not rows:
        return [{"label": date.today().isoformat(), "invested": round(current_balance, 2)}] if current_balance else []

    opening_balance = current_balance - sum(float(row["delta"] or 0) for row in rows)
    running_balance = opening_balance
    result = [{
        "label": (parse_date(rows[0]["label"]) - timedelta(days=1)).isoformat(),
        "invested": round(opening_balance, 2),
    }]
    for row in rows:
        running_balance += float(row["delta"] or 0)
        result.append({"label": row["label"], "invested": round(running_balance, 2)})
    today = date.today().isoformat()
    if result[-1]["label"] < today:
        result.append({"label": today, "invested": round(current_balance, 2)})
    return result


def capital_history_series() -> list[dict[str, Any]]:
    """Reconstruct total capital from current balances and transaction ledger deltas."""
    db = get_db()
    current_row = db.execute(
        """SELECT COALESCE(SUM(balance * CASE WHEN account_type = 'currency' THEN exchange_rate ELSE 1 END), 0) capital
           FROM accounts
           WHERE account_type IN ('checking', 'cash', 'savings', 'deposit', 'currency', 'investment')"""
    ).fetchone()
    current_capital = float(current_row["capital"])
    rows = db.execute(
        """SELECT t.tx_date label, SUM(
               CASE
                   WHEN t.tx_type IN ('income', 'interest')
                       THEN t.amount * CASE WHEN sa.account_type = 'currency' THEN sa.exchange_rate ELSE 1 END
                   WHEN t.tx_type IN ('expense', 'transfer')
                       THEN -t.amount * CASE WHEN sa.account_type = 'currency' THEN sa.exchange_rate ELSE 1 END
                   ELSE 0
               END
               + CASE
                   WHEN t.tx_type = 'transfer'
                       THEN COALESCE(t.target_amount, t.amount)
                           * CASE WHEN ta.account_type = 'currency' THEN ta.exchange_rate ELSE 1 END
                   ELSE 0
               END
           ) delta
           FROM transactions t
           JOIN accounts sa ON sa.id = t.account_id
           LEFT JOIN accounts ta ON ta.id = t.target_account_id
           GROUP BY t.tx_date
           ORDER BY t.tx_date"""
    ).fetchall()
    if not rows:
        return [{"label": date.today().isoformat(), "capital": round(current_capital, 2)}] if current_capital else []

    opening_capital = current_capital - sum(float(row["delta"] or 0) for row in rows)
    running_capital = opening_capital
    result = [{
        "label": (parse_date(rows[0]["label"]) - timedelta(days=1)).isoformat(),
        "capital": round(opening_capital, 2),
    }]
    for row in rows:
        running_capital += float(row["delta"] or 0)
        result.append({"label": row["label"], "capital": round(running_capital, 2)})
    today = date.today().isoformat()
    if result[-1]["label"] < today:
        result.append({"label": today, "capital": round(current_capital, 2)})
    return result


def goal_progress(item: dict[str, Any]) -> dict[str, Any]:
    if item.get("account_id") is not None and item.get("account_balance") is not None:
        item["current_amount"] = round(
            float(item["account_balance"]) * float(item.get("account_exchange_rate") or 1), 2
        )
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


def visual_analytics(period: str, anchor: str | None, person_id: int | None) -> dict[str, Any]:
    """Return compact datasets used by the optional visual analytics widgets."""
    db = get_db()
    start, end = period_bounds(period, anchor)
    person_sql = " AND t.person_id = ?" if person_id else ""
    params: list[Any] = [start.isoformat(), end.isoformat()]
    if person_id:
        params.append(person_id)

    totals = db.execute(
        f"""SELECT
               COALESCE(SUM(CASE WHEN t.tx_type IN ('income', 'interest') THEN t.amount ELSE 0 END), 0) income,
               COALESCE(SUM(CASE WHEN t.tx_type = 'expense' THEN t.amount ELSE 0 END), 0) expense,
               COALESCE(SUM(CASE WHEN t.tx_type = 'transfer' AND ta.kind = 'investment' THEN t.amount ELSE 0 END), 0) invested
            FROM transactions t LEFT JOIN accounts ta ON ta.id = t.target_account_id
            WHERE t.tx_date BETWEEN ? AND ?{person_sql}""",
        params,
    ).fetchone()
    categories = db.execute(
        f"""SELECT COALESCE(c.name, 'Без категории') label, ROUND(SUM(t.amount), 2) amount,
                   COALESCE(c.color, '#86aa9a') color
            FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.tx_type = 'expense' AND t.tx_date BETWEEN ? AND ?{person_sql}
            GROUP BY c.id, c.name, c.color ORDER BY amount DESC""",
        params,
    ).fetchall()
    top = [dict(row) for row in categories[:6]]
    other_amount = round(sum(float(row["amount"]) for row in categories[6:]), 2)
    if other_amount:
        top.append({"label": "Остальное", "amount": other_amount, "color": "#74847c"})
    income = round(float(totals["income"]), 2)
    expense = round(float(totals["expense"]), 2)
    invested = round(float(totals["invested"]), 2)

    heatmap_start = end - timedelta(days=83)
    heatmap_params: list[Any] = [heatmap_start.isoformat(), end.isoformat()]
    if person_id:
        heatmap_params.append(person_id)
    heatmap_rows = db.execute(
        f"""SELECT t.tx_date date, ROUND(SUM(t.amount), 2) amount
            FROM transactions t WHERE t.tx_type = 'expense'
              AND t.tx_date BETWEEN ? AND ?{person_sql}
            GROUP BY t.tx_date ORDER BY t.tx_date""",
        heatmap_params,
    ).fetchall()

    accounts = db.execute(
        "SELECT id, name, account_type, currency_code, balance FROM accounts WHERE is_active = 1 ORDER BY id"
    ).fetchall()
    account_series = []
    cutoff = end - timedelta(days=44)
    for account in accounts:
        rows = db.execute(
            """SELECT tx_date, SUM(delta) delta FROM (
                   SELECT tx_date, CASE
                       WHEN tx_type IN ('income', 'interest') THEN amount
                       WHEN tx_type IN ('expense', 'transfer') THEN -amount ELSE 0 END delta
                   FROM transactions WHERE account_id = ?
                   UNION ALL
                   SELECT tx_date, COALESCE(target_amount, amount) delta
                   FROM transactions WHERE tx_type = 'transfer' AND target_account_id = ?
               ) GROUP BY tx_date ORDER BY tx_date""",
            (account["id"], account["id"]),
        ).fetchall()
        opening = float(account["balance"]) - sum(float(row["delta"] or 0) for row in rows)
        running = opening
        points = []
        for row in rows:
            if row["tx_date"] < cutoff.isoformat():
                running += float(row["delta"] or 0)
                continue
            if not points:
                points.append({"label": cutoff.isoformat(), "balance": round(running, 2)})
            if row["tx_date"] > end.isoformat():
                break
            running += float(row["delta"] or 0)
            points.append({"label": row["tx_date"], "balance": round(running, 2)})
        if not points:
            points.append({"label": cutoff.isoformat(), "balance": round(running, 2)})
        if points[-1]["label"] < end.isoformat():
            points.append({"label": end.isoformat(), "balance": round(running, 2)})
        account_series.append({
            "id": account["id"], "name": account["name"], "account_type": account["account_type"],
            "currency_code": account["currency_code"], "points": points,
        })

    return {
        "flow": {"income": income, "expense": expense, "invested": invested, "categories": top},
        "heatmap": [dict(row) for row in heatmap_rows],
        "waterfall": {
            "income": income, "categories": top,
            "remainder": round(income - expense, 2),
        },
        "account_series": account_series,
    }
