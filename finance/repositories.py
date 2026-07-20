from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .db import get_db


class Repository:
    @staticmethod
    def all(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in get_db().execute(sql, tuple(params)).fetchall()]

    @staticmethod
    def one(sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        row = get_db().execute(sql, tuple(params)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def execute(sql: str, params: Iterable[Any] = ()) -> int:
        db = get_db()
        cursor = db.execute(sql, tuple(params))
        db.commit()
        return int(cursor.lastrowid)
