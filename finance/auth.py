"""Session authentication and CSRF protection for the private household app."""
from __future__ import annotations

import secrets
from functools import wraps
from urllib.parse import urljoin, urlparse

from flask import Response, current_app, g, jsonify, redirect, request, session, url_for

from .db import get_db


def csrf_token() -> str:
    """Return a session-bound CSRF token, creating it when needed."""
    return session.setdefault("csrf_token", secrets.token_urlsafe(32))


def current_user() -> dict | None:
    if "current_user" not in g:
        user_id = session.get("user_id")
        row = None
        if user_id:
            row = get_db().execute(
                """SELECT u.id, u.login, u.is_admin, u.person_id, p.name person_name
                   FROM users u LEFT JOIN people p ON p.id = u.person_id
                   WHERE u.id = ? AND u.is_active = 1""",
                (user_id,),
            ).fetchone()
        g.current_user = dict(row) if row else None
    return g.current_user


def current_user_id() -> int | None:
    user = current_user()
    return int(user["id"]) if user else None


def _is_safe_redirect(target: str | None) -> bool:
    if not target:
        return False
    host_url = urlparse(request.host_url)
    redirect_url = urlparse(urljoin(request.host_url, target))
    return redirect_url.scheme in {"http", "https"} and redirect_url.netloc == host_url.netloc


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is not None:
            return view(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Требуется вход"}), 401
        return redirect(url_for("auth.login", next=request.full_path))

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return jsonify({"ok": False, "error": "Требуется вход"}), 401
        if not user["is_admin"]:
            return jsonify({"ok": False, "error": "Требуются права администратора"}), 403
        return view(*args, **kwargs)

    return wrapped


def init_auth(app) -> None:
    @app.before_request
    def protect_private_routes() -> Response | None:
        endpoint = request.endpoint or ""
        if endpoint.startswith("static") or endpoint.startswith("auth.") or endpoint == "pages.service_worker":
            return None
        if current_app.config["LOGIN_DISABLED"]:
            return None
        if current_user() is None:
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Требуется вход"}), 401
            return redirect(url_for("auth.login", next=request.full_path))
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            submitted = request.headers.get("X-CSRF-Token")
            if not submitted or not secrets.compare_digest(submitted, csrf_token()):
                return jsonify({"ok": False, "error": "Недействительный CSRF-токен"}), 400
        return None

    @app.context_processor
    def add_auth_context() -> dict[str, object]:
        return {"current_user": current_user(), "csrf_token": csrf_token}
