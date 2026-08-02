from __future__ import annotations

import json
from datetime import date
from typing import Any

from flask import current_app

from .db import get_db
from .services import category_budget_status


def push_configured() -> bool:
    return bool(current_app.config["VAPID_PUBLIC_KEY"] and current_app.config["VAPID_PRIVATE_KEY"])


def save_subscription(user_id: int, subscription: dict[str, Any]) -> None:
    endpoint = str(subscription.get("endpoint") or "").strip()
    keys = subscription.get("keys") or {}
    p256dh = str(keys.get("p256dh") or "").strip()
    auth = str(keys.get("auth") or "").strip()
    if not endpoint.startswith("https://") or not p256dh or not auth:
        raise ValueError("Некорректная push-подписка")
    db = get_db()
    db.execute(
        """INSERT INTO push_subscriptions(user_id, endpoint, p256dh, auth)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(endpoint) DO UPDATE SET user_id = excluded.user_id,
               p256dh = excluded.p256dh, auth = excluded.auth, last_seen_at = CURRENT_TIMESTAMP""",
        (user_id, endpoint, p256dh, auth),
    )
    db.commit()


def remove_subscription(user_id: int, endpoint: str) -> None:
    db = get_db()
    db.execute("DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?", (user_id, endpoint))
    db.commit()


def _notification_events() -> list[dict[str, str]]:
    today = date.today().isoformat()
    events: list[dict[str, str]] = []
    for budget in category_budget_status(today):
        if budget["status"] in {"warning", "over"}:
            level = "Превышен" if budget["status"] == "over" else "Почти исчерпан"
            events.append({
                "key": f"budget:{today[:7]}:{budget['category_id']}:{budget['status']}",
                "title": f"{level} бюджет",
                "body": f"{budget['name']}: {budget['progress']:.0f}% лимита",
                "url": "/settings",
            })
    due = get_db().execute(
        """SELECT id, title, amount FROM recurring_transactions
           WHERE is_active = 1 AND next_date <= ? ORDER BY next_date, id""",
        (today,),
    ).fetchall()
    for row in due:
        events.append({
            "key": f"recurring:{row['id']}:{today}",
            "title": "Запланированная операция",
            "body": f"{row['title']}: {float(row['amount']):,.2f}",
            "url": "/recurring",
        })
    return events


def _send_events(events: list[dict[str, str]]) -> dict[str, int]:
    if not push_configured() or not events:
        return {"sent": 0, "skipped": 0, "removed": 0, "errors": 0}
    from pywebpush import WebPushException, webpush

    db = get_db()
    subscriptions = db.execute("SELECT * FROM push_subscriptions ORDER BY id").fetchall()
    sent = skipped = removed = errors = 0
    for subscription in subscriptions:
        for event in events:
            exists = db.execute(
                "SELECT 1 FROM push_deliveries WHERE subscription_id = ? AND event_key = ?",
                (subscription["id"], event["key"]),
            ).fetchone()
            if exists:
                skipped += 1
                continue
            try:
                webpush(
                    subscription_info={
                        "endpoint": subscription["endpoint"],
                        "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
                    },
                    data=json.dumps(event, ensure_ascii=False),
                    vapid_private_key=current_app.config["VAPID_PRIVATE_KEY"],
                    vapid_claims={"sub": current_app.config["VAPID_SUBJECT"]},
                    timeout=15,
                )
            except WebPushException as exc:
                status = getattr(exc.response, "status_code", None)
                if status in {404, 410}:
                    db.execute("DELETE FROM push_subscriptions WHERE id = ?", (subscription["id"],))
                    db.commit()
                    removed += 1
                    break
                current_app.logger.warning("Push delivery failed: %s", exc)
                errors += 1
                continue
            db.execute(
                "INSERT INTO push_deliveries(subscription_id, event_key) VALUES (?, ?)",
                (subscription["id"], event["key"]),
            )
            db.commit()
            sent += 1
    return {"sent": sent, "skipped": skipped, "removed": removed, "errors": errors}


def notify_transaction_created(transaction_id: int, actor_user_id: int | None) -> dict[str, int]:
    if not push_configured():
        return {"sent": 0, "skipped": 0, "removed": 0, "errors": 0}
    db = get_db()
    row = db.execute(
        """SELECT t.*, c.name category_name, p.name person_name,
                  a.name account_name, ta.name target_account_name
           FROM transactions t
           LEFT JOIN categories c ON c.id = t.category_id
           LEFT JOIN people p ON p.id = t.person_id
           LEFT JOIN accounts a ON a.id = t.account_id
           LEFT JOIN accounts ta ON ta.id = t.target_account_id
           WHERE t.id = ?""",
        (transaction_id,),
    ).fetchone()
    if row is None:
        return {"sent": 0, "skipped": 0, "removed": 0, "errors": 0}
    actor = None
    if actor_user_id is not None:
        actor_row = db.execute(
            """SELECT COALESCE(p.name, u.login) name FROM users u
               LEFT JOIN people p ON p.id = u.person_id WHERE u.id = ?""",
            (actor_user_id,),
        ).fetchone()
        actor = actor_row["name"] if actor_row else None
    who = row["person_name"] or actor or "Общее"
    labels = {"income": "Доход", "expense": "Расход", "transfer": "Перевод", "interest": "Проценты"}
    amount = f"{float(row['amount']):,.2f}".replace(",", " ").replace(".", ",")
    currency = db.execute("SELECT value FROM settings WHERE key = 'currency'").fetchone()
    amount = f"{amount} {currency['value'] if currency else '₽'}"
    if row["tx_type"] == "transfer":
        purpose = f"{row['account_name']} → {row['target_account_name']}"
    else:
        purpose = row["category_name"] or "Без категории"
    note = str(row["note"] or "").strip()
    body = purpose if not note else f"{purpose} · {note[:100]}"
    try:
        return _send_events([{
            "key": f"transaction:{transaction_id}:created",
            "title": f"{labels.get(row['tx_type'], 'Операция')} {amount} · {who}",
            "body": body,
            "url": "/transactions",
        }])
    except Exception:
        current_app.logger.exception("Не удалось отправить push для операции %s", transaction_id)
        return {"sent": 0, "skipped": 0, "removed": 0, "errors": 1}


def send_due_notifications() -> dict[str, int]:
    if not push_configured():
        raise RuntimeError("VAPID-ключи не настроены")
    return _send_events(_notification_events())
