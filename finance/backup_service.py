from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from flask import current_app

from .db import get_db, init_db
from .errors import DomainError

MAGIC = b"FINFLOW-BACKUP\x01"
SALT_SIZE = 16
NONCE_SIZE = 12
MAX_BACKUP_SIZE = 100 * 1024 * 1024
KDF_ITERATIONS = 600_000
REQUIRED_TABLES = {"users", "accounts", "transactions", "categories", "settings", "audit_log"}


def _key(password: str, salt: bytes) -> bytes:
    if len(password) < 12:
        raise DomainError("Пароль резервной копии должен содержать минимум 12 символов")
    return PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=KDF_ITERATIONS,
    ).derive(password.encode("utf-8"))


def create_encrypted_backup(password: str) -> bytes:
    source = get_db()
    source.commit()
    descriptor, name = tempfile.mkstemp(suffix=".db")
    os.close(descriptor)
    snapshot_path = Path(name)
    try:
        snapshot = sqlite3.connect(snapshot_path)
        try:
            source.backup(snapshot)
        finally:
            snapshot.close()
        plaintext = snapshot_path.read_bytes()
    finally:
        snapshot_path.unlink(missing_ok=True)
    salt = os.urandom(SALT_SIZE)
    nonce = os.urandom(NONCE_SIZE)
    ciphertext = AESGCM(_key(password, salt)).encrypt(nonce, plaintext, MAGIC)
    return MAGIC + salt + nonce + ciphertext


def _decrypt_backup(payload: bytes, password: str) -> bytes:
    minimum = len(MAGIC) + SALT_SIZE + NONCE_SIZE + 16
    if len(payload) < minimum or len(payload) > MAX_BACKUP_SIZE or not payload.startswith(MAGIC):
        raise DomainError("Файл не является резервной копией FinFlow")
    offset = len(MAGIC)
    salt = payload[offset:offset + SALT_SIZE]
    nonce = payload[offset + SALT_SIZE:offset + SALT_SIZE + NONCE_SIZE]
    ciphertext = payload[offset + SALT_SIZE + NONCE_SIZE:]
    try:
        return AESGCM(_key(password, salt)).decrypt(nonce, ciphertext, MAGIC)
    except InvalidTag as exc:
        raise DomainError("Неверный пароль или повреждённая резервная копия") from exc


def restore_encrypted_backup(payload: bytes, password: str) -> Path:
    plaintext = _decrypt_backup(payload, password)
    descriptor, name = tempfile.mkstemp(suffix=".db")
    os.close(descriptor)
    incoming_path = Path(name)
    backup_dir = Path(current_app.config["DATABASE"]).parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    rollback_path = backup_dir / f"before-restore-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}.db"
    live = get_db()
    try:
        incoming_path.write_bytes(plaintext)
        incoming = sqlite3.connect(incoming_path)
        incoming.row_factory = sqlite3.Row
        try:
            check = incoming.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise DomainError("Проверка целостности резервной копии не пройдена")
            tables = {
                row[0] for row in incoming.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if not REQUIRED_TABLES.issubset(tables):
                raise DomainError("В резервной копии отсутствуют обязательные таблицы")

            rollback = sqlite3.connect(rollback_path)
            try:
                live.commit()
                live.backup(rollback)
            finally:
                rollback.close()
            try:
                incoming.backup(live)
                live.commit()
                init_db(seed_demo=False)
            except Exception:
                rollback = sqlite3.connect(rollback_path)
                try:
                    rollback.backup(live)
                    live.commit()
                finally:
                    rollback.close()
                raise
        finally:
            incoming.close()
    finally:
        incoming_path.unlink(missing_ok=True)
    return rollback_path
