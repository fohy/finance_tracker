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


def send_due_notifications() -> dict[str, int]:
    if not push_configured():
        raise RuntimeError("VAPID-ключи не настроены")
    from pywebpush import WebPushException, webpush

    db = get_db()
    subscriptions = db.execute("SELECT * FROM push_subscriptions ORDER BY id").fetchall()
    events = _notification_events()
    sent = skipped = removed = 0
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
                raise
            db.execute(
                "INSERT INTO push_deliveries(subscription_id, event_key) VALUES (?, ?)",
                (subscription["id"], event["key"]),
            )
            db.commit()
            sent += 1
    return {"sent": sent, "skipped": skipped, "removed": removed}
