from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

from flask import current_app, g

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    avatar_color TEXT NOT NULL DEFAULT '#7c5cff'
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('income', 'expense')),
    icon TEXT NOT NULL DEFAULT '•',
    color TEXT NOT NULL DEFAULT '#7c5cff',
    parent_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    is_custom INTEGER NOT NULL DEFAULT 0,
    UNIQUE(name, type)
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK(kind IN ('life', 'investment')),
    balance REAL NOT NULL DEFAULT 0,
    annual_rate REAL NOT NULL DEFAULT 0,
    last_accrual_date TEXT NOT NULL DEFAULT (date('now'))
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_type TEXT NOT NULL CHECK(tx_type IN ('income', 'expense', 'transfer', 'interest')),
    amount REAL NOT NULL CHECK(amount > 0),
    tx_date TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    target_account_id INTEGER REFERENCES accounts(id) ON DELETE RESTRICT,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    target_amount REAL NOT NULL CHECK(target_amount > 0),
    current_amount REAL NOT NULL DEFAULT 0,
    target_date TEXT,
    person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
    priority TEXT NOT NULL DEFAULT 'medium' CHECK(priority IN ('low','medium','high')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','done','paused')),
    note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    cost REAL NOT NULL CHECK(cost > 0),
    saved_amount REAL NOT NULL DEFAULT 0,
    target_date TEXT,
    person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
    priority TEXT NOT NULL DEFAULT 'medium' CHECK(priority IN ('low','medium','high')),
    status TEXT NOT NULL DEFAULT 'planned' CHECK(status IN ('planned','bought','paused')),
    note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(tx_date);
CREATE INDEX IF NOT EXISTS idx_transactions_person ON transactions(person_id);
CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions(tx_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id);
"""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        db_path = Path(current_app.config["DATABASE"])
        db_path.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_: object | None = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app) -> None:
    app.teardown_appcontext(close_db)


def _insert_many(db: sqlite3.Connection, sql: str, rows: Iterator[tuple]) -> None:
    db.executemany(sql, rows)


def init_db(seed_demo: bool = True) -> None:
    db = get_db()
    db.executescript(SCHEMA)

    if db.execute("SELECT COUNT(*) FROM people").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO people(name, avatar_color) VALUES (?, ?)",
            [("Саша", "#6c8cff"), ("Настя", "#ff6fae")],
        )

    if db.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
        categories = [
            ("Зарплата", "income", "₽", "#33d69f", None, 0),
            ("Подработка", "income", "↗", "#5b8cff", None, 0),
            ("Подарки", "income", "✦", "#b879ff", None, 0),
            ("Возвраты", "income", "↩", "#55c2ff", None, 0),
            ("Продукты", "expense", "🛒", "#ff8d6c", None, 0),
            ("Кафе и рестораны", "expense", "☕", "#ffad66", None, 0),
            ("Транспорт", "expense", "🚕", "#6c8cff", None, 0),
            ("Жильё", "expense", "⌂", "#b879ff", None, 0),
            ("Коммунальные услуги", "expense", "⚡", "#55c2ff", None, 0),
            ("Здоровье", "expense", "✚", "#ff6f91", None, 0),
            ("Одежда", "expense", "◈", "#d09bff", None, 0),
            ("Развлечения", "expense", "🎮", "#f9c74f", None, 0),
            ("Образование", "expense", "⌁", "#43c6ac", None, 0),
            ("Подписки", "expense", "◉", "#7f8cff", None, 0),
            ("Подарки и помощь", "expense", "♡", "#ff78a8", None, 0),
            ("Путешествия", "expense", "✈", "#4ecdc4", None, 0),
            ("Дом и быт", "expense", "▣", "#f9844a", None, 0),
            ("Красота и уход", "expense", "✧", "#f78fb3", None, 0),
            ("Связь и интернет", "expense", "⌁", "#54a0ff", None, 0),
            ("Непредвиденное", "expense", "!", "#ff5c5c", None, 0),
        ]
        db.executemany(
            "INSERT INTO categories(name, type, icon, color, parent_id, is_custom) VALUES (?, ?, ?, ?, ?, ?)",
            categories,
        )

    if db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0:
        today = date.today().isoformat()
        db.executemany(
            "INSERT INTO accounts(name, kind, balance, annual_rate, last_accrual_date) VALUES (?, ?, ?, ?, ?)",
            [
                ("Баланс на жизнь", "life", 0, 0, today),
                ("Инвестиционный баланс", "investment", 0, 12.5, today),
            ],
        )

    defaults = {
        "investment_target_percent": "20",
        "monthly_life_budget": "90000",
        "currency": "₽",
    }
    for key, value in defaults.items():
        db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))

    if seed_demo and db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0:
        _seed_demo(db)

    db.commit()


def _seed_demo(db: sqlite3.Connection) -> None:
    people = {r["name"]: r["id"] for r in db.execute("SELECT id, name FROM people")}
    cats = {(r["name"], r["type"]): r["id"] for r in db.execute("SELECT id, name, type FROM categories")}
    accounts = {r["kind"]: r["id"] for r in db.execute("SELECT id, kind FROM accounts")}

    today = date.today()
    rows: list[tuple] = []
    for month_offset in range(0, 4):
        base = (today.replace(day=1) - timedelta(days=month_offset * 30)).replace(day=1)
        for person_name, salary in [("Саша", 120000), ("Настя", 85000)]:
            rows.append(("income", salary, (base + timedelta(days=4)).isoformat(), cats[("Зарплата", "income")], people[person_name], accounts["life"], None, "Основная выплата"))
        expenses = [
            ("Продукты", 18500, 8, "Саша"),
            ("Кафе и рестораны", 7200, 12, "Настя"),
            ("Транспорт", 5400, 15, "Саша"),
            ("Жильё", 36000, 2, "Настя"),
            ("Подписки", 2400, 18, "Саша"),
            ("Развлечения", 6800, 22, "Настя"),
            ("Здоровье", 3100, 25, "Саша"),
            ("Дом и быт", 4600, 27, "Настя"),
        ]
        for cat_name, amount, day_num, person_name in expenses:
            safe_day = min(day_num, 28)
            rows.append(("expense", amount, base.replace(day=safe_day).isoformat(), cats[(cat_name, "expense")], people[person_name], accounts["life"], None, "Демо-операция"))
        rows.append(("transfer", 35000, base.replace(day=10).isoformat(), None, people["Саша"], accounts["life"], accounts["investment"], "Регулярное пополнение инвестиций"))

    db.executemany(
        """INSERT INTO transactions(tx_type, amount, tx_date, category_id, person_id, account_id, target_account_id, note)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )

    # Demo account balances must be reproducible from the ledger just like real ones.
    db.execute(
        """UPDATE accounts
           SET balance = ROUND(COALESCE((
               SELECT SUM(CASE
                   WHEN t.tx_type = 'income' THEN t.amount
                   WHEN t.tx_type = 'expense' THEN -t.amount
                   WHEN t.tx_type = 'interest' THEN t.amount
                   WHEN t.tx_type = 'transfer' AND t.account_id = accounts.id THEN -t.amount
                   WHEN t.tx_type = 'transfer' AND t.target_account_id = accounts.id THEN t.amount
                   ELSE 0 END)
               FROM transactions t
               WHERE t.account_id = accounts.id OR t.target_account_id = accounts.id
           ), 0), 2)"""
    )

    if db.execute("SELECT COUNT(*) FROM goals").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO goals(title, target_amount, current_amount, target_date, person_id, priority, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("Финансовая подушка", 500000, 320000, (today + timedelta(days=180)).isoformat(), None, "high", "6 месяцев обязательных расходов"),
                ("Путешествие", 180000, 65000, (today + timedelta(days=120)).isoformat(), people["Настя"], "medium", "Отпуск вдвоём"),
            ],
        )

    if db.execute("SELECT COUNT(*) FROM purchases").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO purchases(title, cost, saved_amount, target_date, person_id, priority, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("Новый ноутбук", 190000, 45000, (today + timedelta(days=150)).isoformat(), people["Саша"], "high", "Для работы"),
                ("Кофемашина", 42000, 12000, (today + timedelta(days=75)).isoformat(), people["Настя"], "medium", "Домой"),
            ],
        )
