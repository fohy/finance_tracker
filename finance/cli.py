from __future__ import annotations

import click
import base64
import os
from pathlib import Path
from flask import Flask
from werkzeug.security import generate_password_hash

from .db import get_db
from .push_service import send_due_notifications


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

    @app.cli.command("generate-vapid-keys")
    @click.option(
        "--private-key-path", type=click.Path(path_type=Path),
        default=lambda: Path.home() / ".config" / "finflow" / "vapid_private.pem",
        show_default=True,
    )
    @click.option("--subject", prompt="VAPID contact (mailto:...)")
    def generate_vapid_keys(private_key_path: Path, subject: str) -> None:
        """Generate a Web Push VAPID key pair; keep the private file outside Git."""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        if private_key_path.exists():
            raise click.ClickException(f"Файл уже существует: {private_key_path}")
        private_key_path.parent.mkdir(parents=True, exist_ok=True)
        private_key = ec.generate_private_key(ec.SECP256R1())
        private_key_path.write_bytes(private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        os.chmod(private_key_path, 0o600)
        public_bytes = private_key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
        )
        public_key = base64.urlsafe_b64encode(public_bytes).rstrip(b"=").decode("ascii")
        private_key_path.with_name("vapid_public_key").write_text(public_key, encoding="utf-8")
        private_key_path.with_name("vapid_subject").write_text(subject.strip(), encoding="utf-8")
        click.echo(f"Ключи сохранены в {private_key_path.parent}")
        click.echo("Перезагрузите приложение и добавьте ежедневную задачу send-push-notifications.")

    @app.cli.command("send-push-notifications")
    def send_push_notifications() -> None:
        """Send due budget and recurring-operation notifications."""
        result = send_due_notifications()
        click.echo(
            f"Отправлено: {result['sent']}; пропущено: {result['skipped']}; "
            f"удалено подписок: {result['removed']}"
        )
