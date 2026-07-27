from __future__ import annotations

import click
from flask import Flask
from werkzeug.security import generate_password_hash

from .db import get_db


def init_cli(app: Flask) -> None:
    @app.cli.command("create-user")
    @click.option("--login", prompt="Логин")
    @click.option("--person", prompt="Имя из раздела «Люди»")
    @click.option("--admin", is_flag=True, help="Выдать права администратора.")
    @click.password_option(confirmation_prompt=True)
    def create_user(login: str, person: str, admin: bool, password: str) -> None:
        """Create one of the two private household accounts."""
        normalised_login = login.strip().casefold()
        db = get_db()
        person_row = db.execute("SELECT id FROM people WHERE name = ?", (person.strip(),)).fetchone()
        if not person_row:
            raise click.ClickException("Участник не найден. Сначала добавьте его в таблицу people.")
        if db.execute("SELECT 1 FROM users WHERE login = ?", (normalised_login,)).fetchone():
            raise click.ClickException("Этот логин уже занят.")
        if db.execute("SELECT 1 FROM users WHERE person_id = ?", (person_row["id"],)).fetchone():
            raise click.ClickException("К этому участнику уже привязан аккаунт.")
        db.execute(
            "INSERT INTO users(login, password_hash, person_id, is_admin) VALUES (?, ?, ?, ?)",
            (normalised_login, generate_password_hash(password), person_row["id"], int(admin)),
        )
        db.commit()
        click.echo(f"Пользователь {normalised_login} создан.")

    @app.cli.command("reset-password")
    @click.option("--login", prompt="Логин")
    @click.password_option(confirmation_prompt=True)
    def reset_password(login: str, password: str) -> None:
        """Reset a password without exposing a web reset endpoint."""
        db = get_db()
        cursor = db.execute(
            "UPDATE users SET password_hash = ? WHERE login = ?",
            (generate_password_hash(password), login.strip().casefold()),
        )
        if cursor.rowcount == 0:
            db.rollback()
            raise click.ClickException("Пользователь не найден.")
        db.commit()
        click.echo("Пароль обновлён.")
