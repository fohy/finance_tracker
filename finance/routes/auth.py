from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from ..auth import _is_safe_redirect, csrf_token
from ..db import get_db

auth_bp = Blueprint("auth", __name__)
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW = timedelta(minutes=15)


def _normalise_login(value: str | None) -> str:
    return (value or "").strip().casefold()


def _too_many_attempts(login: str) -> bool:
    since = (datetime.now(UTC) - LOGIN_WINDOW).replace(tzinfo=None).isoformat(sep=" ")
    count = get_db().execute(
        """SELECT COUNT(*) FROM login_attempts
           WHERE login = ? AND succeeded = 0 AND created_at >= ?""",
        (login, since),
    ).fetchone()[0]
    return count >= MAX_LOGIN_ATTEMPTS


def _record_attempt(login: str, succeeded: bool) -> None:
    db = get_db()
    db.execute(
        "INSERT INTO login_attempts(login, succeeded, remote_addr) VALUES (?, ?, ?)",
        (login, int(succeeded), request.remote_addr or ""),
    )
    db.commit()


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("pages.dashboard"))
    if request.method == "GET":
        return render_template("login.html", title="Вход")

    submitted_token = request.form.get("csrf_token", "")
    if not submitted_token or submitted_token != csrf_token():
        flash("Форма устарела. Попробуйте ещё раз.", "error")
        return redirect(url_for("auth.login"))

    login_value = _normalise_login(request.form.get("login"))
    password = request.form.get("password", "")
    if _too_many_attempts(login_value):
        flash("Слишком много попыток. Подождите 15 минут.", "error")
        return redirect(url_for("auth.login"))

    row = get_db().execute(
        "SELECT id, password_hash, is_active FROM users WHERE login = ?", (login_value,)
    ).fetchone()
    valid = bool(row and row["is_active"] and check_password_hash(row["password_hash"], password))
    _record_attempt(login_value, valid)
    if not valid:
        flash("Неверный логин или пароль.", "error")
        return redirect(url_for("auth.login"))

    session.clear()
    session["user_id"] = row["id"]
    session.permanent = True
    csrf_token()
    next_url = request.args.get("next")
    return redirect(next_url if _is_safe_redirect(next_url) else url_for("pages.dashboard"))


@auth_bp.post("/logout")
def logout():
    submitted_token = request.form.get("csrf_token", "")
    if submitted_token != csrf_token():
        flash("Форма устарела. Попробуйте ещё раз.", "error")
        return redirect(url_for("pages.dashboard"))
    session.clear()
    return redirect(url_for("auth.login"))
