from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from io import BytesIO

from flask import Blueprint, current_app, jsonify, request, send_file

from ..auth import admin_required, current_user_id
from ..backup_service import MAX_BACKUP_SIZE, create_encrypted_backup, restore_encrypted_backup
from ..db import get_db
from ..push_service import push_configured, remove_subscription, save_subscription

features_api_bp = Blueprint("features_api", __name__)
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def ok(data=None, status: int = 200):
    return jsonify({"ok": True, "data": data}), status


def fail(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


@features_api_bp.errorhandler(ValueError)
def value_error(error: ValueError):
    return fail(str(error), 400)


@features_api_bp.get("/projects")
def list_projects():
    rows = get_db().execute(
        """SELECT p.*, COUNT(t.id) transaction_count,
                  ROUND(COALESCE(SUM(CASE WHEN t.tx_type = 'expense' THEN t.amount ELSE 0 END), 0), 2) spent
           FROM projects p LEFT JOIN transactions t ON t.project_id = p.id
           GROUP BY p.id ORDER BY p.status, p.name COLLATE NOCASE"""
    ).fetchall()
    return ok([dict(row) for row in rows])


@features_api_bp.post("/projects")
def create_project():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    color = str(data.get("color") or "#86aa9a").strip()
    icon = str(data.get("icon") or "briefcase").strip()[:40]
    if not name or len(name) > 80:
        return fail("Название проекта должно содержать от 1 до 80 символов")
    if not COLOR_RE.fullmatch(color):
        return fail("Некорректный цвет проекта")
    db = get_db()
    try:
        cursor = db.execute(
            "INSERT INTO projects(name, color, icon) VALUES (?, ?, ?)", (name, color, icon or "briefcase"),
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        if "UNIQUE" in str(exc).upper():
            return fail("Проект с таким названием уже существует")
        raise
    return ok({"id": cursor.lastrowid}, 201)


@features_api_bp.patch("/projects/<int:project_id>")
def update_project(project_id: int):
    data = request.get_json(silent=True) or {}
    updates: dict[str, object] = {}
    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name or len(name) > 80:
            return fail("Название проекта должно содержать от 1 до 80 символов")
        updates["name"] = name
    if "color" in data:
        color = str(data.get("color") or "").strip()
        if not COLOR_RE.fullmatch(color):
            return fail("Некорректный цвет проекта")
        updates["color"] = color
    if "status" in data:
        if data["status"] not in {"active", "archived"}:
            return fail("Некорректный статус проекта")
        updates["status"] = data["status"]
    if not updates:
        return fail("Нет полей для изменения")
    db = get_db()
    assignments = ", ".join(f"{key} = ?" for key in updates)
    cursor = db.execute(
        f"UPDATE projects SET {assignments} WHERE id = ?", [*updates.values(), project_id]
    )
    if cursor.rowcount == 0:
        db.rollback()
        return fail("Проект не найден", 404)
    db.commit()
    return ok()


@features_api_bp.get("/transactions/<int:tx_id>/history")
def transaction_history(tx_id: int):
    rows = get_db().execute(
        """SELECT l.id, l.action, l.details, l.created_at,
                  COALESCE(p.name, u.login, 'Система') actor
           FROM audit_log l
           LEFT JOIN users u ON u.id = l.actor_user_id
           LEFT JOIN people p ON p.id = u.person_id
           WHERE l.entity_type = 'transaction' AND l.entity_id = ?
           ORDER BY l.id DESC""",
        (tx_id,),
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            item["details"] = json.loads(item["details"])
        except (TypeError, json.JSONDecodeError):
            item["details"] = {"legacy": item["details"]}
        items.append(item)
    return ok(items)


@features_api_bp.get("/push/config")
def push_config():
    user_id = current_user_id()
    count = get_db().execute(
        "SELECT COUNT(*) FROM push_subscriptions WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    return ok({
        "configured": push_configured(),
        "public_key": current_app.config["VAPID_PUBLIC_KEY"] if push_configured() else "",
        "subscribed": count > 0,
    })


@features_api_bp.post("/push/subscriptions")
def subscribe_push():
    if not push_configured():
        return fail("Push-уведомления не настроены на сервере", 503)
    user_id = current_user_id()
    if user_id is None:
        return fail("Требуется вход", 401)
    save_subscription(user_id, request.get_json(silent=True) or {})
    return ok(None, 201)


@features_api_bp.delete("/push/subscriptions")
def unsubscribe_push():
    user_id = current_user_id()
    endpoint = str((request.get_json(silent=True) or {}).get("endpoint") or "")
    if user_id is not None and endpoint:
        remove_subscription(user_id, endpoint)
    return ok()


@features_api_bp.post("/backups/export")
@admin_required
def export_backup():
    password = str((request.get_json(silent=True) or {}).get("password") or "")
    payload = create_encrypted_backup(password)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    response = send_file(
        BytesIO(payload), mimetype="application/octet-stream", as_attachment=True,
        download_name=f"finflow-{stamp}.ffbackup", max_age=0,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@features_api_bp.post("/backups/restore")
@admin_required
def restore_backup():
    uploaded = request.files.get("backup")
    password = str(request.form.get("password") or "")
    if uploaded is None:
        return fail("Выберите файл резервной копии")
    payload = uploaded.read(MAX_BACKUP_SIZE + 1)
    if len(payload) > MAX_BACKUP_SIZE:
        return fail("Файл резервной копии слишком большой", 413)
    rollback_path = restore_encrypted_backup(payload, password)
    return ok({"rollback_created": rollback_path.name})
