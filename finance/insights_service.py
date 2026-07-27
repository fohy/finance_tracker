from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import Any

from .db import get_db
from .services import setting


def _month_shift(value: date, offset: int) -> date:
    month = value.month - 1 + offset
    year = value.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def total_capital() -> float:
    row = get_db().execute(
        "SELECT COALESCE(SUM(balance * CASE WHEN account_type = 'currency' THEN exchange_rate ELSE 1 END), 0) value FROM accounts"
    ).fetchone()
    return round(float(row["value"]), 2)


def financial_cushion() -> dict[str, float]:
    db = get_db()
    reserve = db.execute(
        """SELECT COALESCE(SUM(balance * CASE WHEN account_type = 'currency' THEN exchange_rate ELSE 1 END), 0) value
           FROM accounts WHERE is_active = 1 AND account_type IN ('savings', 'deposit', 'currency')"""
    ).fetchone()["value"]
    current = date.today().replace(day=1)
    start = _month_shift(current, -3)
    burn = db.execute(
        """SELECT COALESCE(SUM(amount), 0) / 3.0 value FROM transactions
           WHERE tx_type = 'expense' AND tx_date >= ? AND tx_date < ?""",
        (start.isoformat(), current.isoformat()),
    ).fetchone()["value"]
    monthly_burn = float(burn) or setting("monthly_life_budget", 90_000)
    amount = float(reserve)
    return {
        "amount": round(amount, 2), "monthly_burn": round(monthly_burn, 2),
        "runway_months": round(amount / monthly_burn, 1) if monthly_burn else 0,
        "target_3": round(monthly_burn * 3, 2), "target_6": round(monthly_burn * 6, 2),
        "gap_3": round(max(0, monthly_burn * 3 - amount), 2),
        "gap_6": round(max(0, monthly_burn * 6 - amount), 2),
    }


def spending_anomalies() -> list[dict[str, Any]]:
    db = get_db()
    current_start = date.today().replace(day=1)
    history_start = _month_shift(current_start, -3)
    category_rows = db.execute(
        """SELECT c.id category_id, c.name category_name,
                  SUM(CASE WHEN t.tx_date >= ? THEN t.amount ELSE 0 END) current_amount,
                  SUM(CASE WHEN t.tx_date >= ? AND t.tx_date < ? THEN t.amount ELSE 0 END) / 3.0 average_amount
           FROM transactions t JOIN categories c ON c.id = t.category_id
           WHERE t.tx_type = 'expense' AND t.tx_date >= ?
           GROUP BY c.id, c.name""",
        (current_start.isoformat(), history_start.isoformat(), current_start.isoformat(), history_start.isoformat()),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in category_rows:
        current_amount = float(row["current_amount"] or 0)
        average = float(row["average_amount"] or 0)
        increase = current_amount - average
        if current_amount >= 2_000 and increase >= max(1_000, average * 0.5):
            result.append({
                "kind": "category_increase", "category_id": row["category_id"],
                "category_name": row["category_name"], "current_amount": round(current_amount, 2),
                "baseline": round(average, 2),
                "increase_percent": round(increase / average * 100, 1) if average else 100.0,
            })
    large_rows = db.execute(
        """SELECT t.id transaction_id, t.amount, t.tx_date, t.note, c.id category_id, c.name category_name,
                  (SELECT AVG(h.amount) FROM transactions h
                   WHERE h.tx_type = 'expense' AND h.category_id = t.category_id
                     AND h.tx_date >= ? AND h.tx_date < ?) baseline
           FROM transactions t JOIN categories c ON c.id = t.category_id
           WHERE t.tx_type = 'expense' AND t.tx_date >= ? ORDER BY t.amount DESC""",
        (history_start.isoformat(), current_start.isoformat(), current_start.isoformat()),
    ).fetchall()
    for row in large_rows:
        baseline = float(row["baseline"] or 0)
        amount = float(row["amount"])
        if baseline > 0 and amount >= max(3_000, baseline * 3):
            result.append({
                "kind": "large_transaction", "transaction_id": row["transaction_id"],
                "category_id": row["category_id"], "category_name": row["category_name"],
                "amount": round(amount, 2), "baseline": round(baseline, 2),
                "tx_date": row["tx_date"], "note": row["note"],
            })
    return result[:20]


def what_if(data: dict[str, Any]) -> dict[str, Any]:
    def number(key: str, default: float, minimum: float = 0) -> float:
        try:
            value = float(data.get(key, default))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Поле «{key}» должно быть числом") from exc
        if value < minimum:
            raise ValueError(f"Поле «{key}» не может быть меньше {minimum}")
        return value

    income = number("income", 0)
    expense = number("expense", 0)
    savings_percent = number("savings_percent", setting("investment_target_percent", 20))
    currency_percent = number("currency_percent", setting("currency_target_percent", 10))
    if savings_percent + currency_percent > 100:
        raise ValueError("Сумма долей накоплений и валюты не может превышать 100%")
    savings_rate = number("savings_rate", 0)
    currency_rate = number("currency_rate", 0)
    months = int(number("horizon_months", number("horizon_years", 1) * 12, 1))
    if months > 600:
        raise ValueError("Горизонт не может превышать 600 месяцев")
    savings = income * savings_percent / 100
    currency = income * currency_percent / 100
    life = income - savings - currency
    free_cash = life - expense
    savings_value = 0.0
    currency_value = 0.0
    cash_value = 0.0
    for _ in range(months):
        savings_value = (savings_value + savings) * (1 + savings_rate / 100 / 12)
        currency_value = (currency_value + currency) * (1 + currency_rate / 100 / 12)
        cash_value += free_cash
    added = savings_value + currency_value + cash_value
    return {
        "inputs": {
            "income": income, "expense": expense, "savings_percent": savings_percent,
            "currency_percent": currency_percent, "savings_rate": savings_rate,
            "currency_rate": currency_rate, "horizon_months": months,
        },
        "allocation": {
            "life": round(life, 2), "expense": round(expense, 2), "savings": round(savings, 2),
            "currency": round(currency, 2), "free_cash": round(free_cash, 2),
        },
        "current_capital": total_capital(), "added_capital": round(added, 2),
        "projected_capital": round(total_capital() + added, 2),
    }


def _week_metrics(start: date, end: date) -> dict[str, float]:
    row = get_db().execute(
        """SELECT COALESCE(SUM(CASE WHEN t.tx_type = 'income' THEN t.amount ELSE 0 END), 0) income,
                  COALESCE(SUM(CASE WHEN t.tx_type = 'expense' THEN t.amount ELSE 0 END), 0) expense,
                  COALESCE(SUM(CASE WHEN t.tx_type = 'transfer' AND a.account_type IN ('savings','deposit') THEN t.amount ELSE 0 END), 0) saved,
                  COALESCE(SUM(CASE WHEN t.tx_type = 'transfer' AND a.account_type = 'currency' THEN t.amount ELSE 0 END), 0) currency_reserved
           FROM transactions t LEFT JOIN accounts a ON a.id = t.target_account_id
           WHERE t.tx_date BETWEEN ? AND ?""",
        (start.isoformat(), end.isoformat()),
    ).fetchone()
    return {key: round(float(row[key]), 2) for key in row.keys()}


def weekly_report() -> dict[str, Any]:
    today = date.today()
    current_start = today - timedelta(days=today.weekday())
    current_end = current_start + timedelta(days=6)
    last_start = current_start - timedelta(days=7)
    last_end = current_start - timedelta(days=1)
    current = _week_metrics(current_start, current_end)
    previous = _week_metrics(last_start, last_end)

    def delta(key: str) -> float:
        old = previous[key]
        if old == 0:
            return 100.0 if current[key] else 0.0
        return round((current[key] - old) / abs(old) * 100, 1)

    top = get_db().execute(
        """SELECT c.name, SUM(t.amount) amount FROM transactions t
           LEFT JOIN categories c ON c.id = t.category_id
           WHERE t.tx_type = 'expense' AND t.tx_date BETWEEN ? AND ?
           GROUP BY c.id, c.name ORDER BY amount DESC LIMIT 3""",
        (current_start.isoformat(), current_end.isoformat()),
    ).fetchall()
    anomalies = spending_anomalies()
    actions: list[str] = []
    if current["expense"] > current["income"] and current["expense"] > 0:
        actions.append("Сократите необязательные расходы: на этой неделе траты выше доходов.")
    if current["saved"] <= 0:
        actions.append("Переведите запланированную долю дохода на накопительный счёт.")
    if current["currency_reserved"] <= 0:
        actions.append("Проверьте план валютного резерва и выполните перевод после подтверждения.")
    if anomalies:
        actions.append(f"Проверьте рост расходов в категории «{anomalies[0]['category_name']}».")
    actions.append("Просмотрите обязательные платежи на ближайшие 30 дней.")
    actions.append("Сверьте операции недели с банковской выпиской.")
    return {
        "current_week": {"start": current_start.isoformat(), "end": current_end.isoformat(), **current},
        "last_week": {"start": last_start.isoformat(), "end": last_end.isoformat(), **previous},
        "deltas": {key: delta(key) for key in current},
        "top_categories": [dict(row) for row in top], "anomalies": anomalies,
        "actions": actions[:3],
    }
