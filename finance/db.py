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

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    login TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    person_id INTEGER NOT NULL UNIQUE REFERENCES people(id) ON DELETE RESTRICT,
    is_admin INTEGER NOT NULL DEFAULT 0 CHECK(is_admin IN (0, 1)),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    login TEXT NOT NULL,
    succeeded INTEGER NOT NULL CHECK(succeeded IN (0, 1)),
    remote_addr TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('income', 'expense')),
    icon TEXT NOT NULL DEFAULT 'category',
    color TEXT NOT NULL DEFAULT '#7c5cff',
    parent_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    is_custom INTEGER NOT NULL DEFAULT 0,
    UNIQUE(name, type)
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK(kind IN ('life', 'investment')),
    account_type TEXT NOT NULL DEFAULT 'checking',
    balance REAL NOT NULL DEFAULT 0,
    annual_rate REAL NOT NULL DEFAULT 0,
    last_accrual_date TEXT NOT NULL DEFAULT (date('now')),
    interest_enabled INTEGER NOT NULL DEFAULT 0 CHECK(interest_enabled IN (0, 1)),
    interest_last_posted_month TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    currency_code TEXT NOT NULL DEFAULT 'RUB',
    exchange_rate REAL NOT NULL DEFAULT 1 CHECK(exchange_rate > 0)
);

CREATE TABLE IF NOT EXISTS account_rate_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    effective_date TEXT NOT NULL,
    annual_rate REAL NOT NULL CHECK(annual_rate >= 0),
    UNIQUE(account_id, effective_date)
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
    target_amount REAL,
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
    note TEXT NOT NULL DEFAULT '',
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL
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

CREATE TABLE IF NOT EXISTS category_budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL UNIQUE REFERENCES categories(id) ON DELETE CASCADE,
    monthly_limit REAL NOT NULL CHECK(monthly_limit > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recurring_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    tx_type TEXT NOT NULL CHECK(tx_type IN ('income', 'expense', 'transfer')),
    amount REAL NOT NULL CHECK(amount > 0),
    frequency TEXT NOT NULL CHECK(frequency IN ('weekly', 'monthly')),
    next_date TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    target_account_id INTEGER REFERENCES accounts(id) ON DELETE RESTRICT,
    note TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS category_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    priority INTEGER NOT NULL DEFAULT 100,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
    imported_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS imported_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
    transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS receipt_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,
    transaction_ids TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'proverkacheka',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS receipt_product_categories (
    normalized_name TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    times_used INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_receipt_product_category
ON receipt_product_categories(category_id);

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
CREATE INDEX IF NOT EXISTS idx_login_attempts_login_time ON login_attempts(login, created_at);
CREATE INDEX IF NOT EXISTS idx_recurring_next_date ON recurring_transactions(next_date, is_active);
CREATE INDEX IF NOT EXISTS idx_category_rules_priority ON category_rules(is_active, priority, id);
CREATE INDEX IF NOT EXISTS idx_import_batches_created ON import_batches(created_at);
CREATE INDEX IF NOT EXISTS idx_account_rate_history_date ON account_rate_history(account_id, effective_date);
"""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        db_path = Path(current_app.config["DATABASE"])
        db_path.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(db_path, timeout=30)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 30000")
        g.db.execute("PRAGMA journal_mode = WAL")
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
    _apply_compatible_schema_changes(db)

    if db.execute("SELECT COUNT(*) FROM people").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO people(name, avatar_color) VALUES (?, ?)",
            [("Саша", "#6c8cff"), ("Настя", "#ff6fae")],
        )

    categories = [
        ("Зарплата", "income", "wallet", "#33d69f", None, 0),
        ("Подработка", "income", "briefcase", "#5b8cff", None, 0),
        ("Подарки", "income", "gift", "#b879ff", None, 0),
        ("Возвраты", "income", "refund", "#55c2ff", None, 0),
        ("Продукты", "expense", "groceries", "#ff8d6c", None, 0),
        ("Кафе и рестораны", "expense", "cafe", "#ffad66", None, 0),
        ("Транспорт", "expense", "transport", "#6c8cff", None, 0),
        ("Жильё", "expense", "housing", "#b879ff", None, 0),
        ("Коммунальные услуги", "expense", "utilities", "#55c2ff", None, 0),
        ("Здоровье", "expense", "health", "#ff6f91", None, 0),
        ("Одежда", "expense", "clothing", "#d09bff", None, 0),
        ("Развлечения", "expense", "entertainment", "#f9c74f", None, 0),
        ("Образование", "expense", "education", "#43c6ac", None, 0),
        ("Подписки", "expense", "subscriptions", "#7f8cff", None, 0),
        ("Подарки и помощь", "expense", "aid", "#ff78a8", None, 0),
        ("Путешествия", "expense", "travel", "#4ecdc4", None, 0),
        ("Дом и быт", "expense", "home-care", "#f9844a", None, 0),
        ("Красота и уход", "expense", "beauty", "#f78fb3", None, 0),
        ("Связь и интернет", "expense", "internet", "#54a0ff", None, 0),
        ("Непредвиденное", "expense", "alert", "#ff5c5c", None, 0),
        ("Автомобиль", "expense", "car", "#5b8cff", None, 0),
        ("Спорт и фитнес", "expense", "fitness", "#84cc16", None, 0),
        ("Дети", "expense", "children", "#f9c74f", None, 0),
        ("Питомцы", "expense", "pets", "#f59e0b", None, 0),
        ("Техника", "expense", "devices", "#8b91a7", None, 0),
        ("Ремонт", "expense", "repair", "#f97316", None, 0),
        ("Налоги и комиссии", "expense", "taxes", "#ef4444", None, 0),
        ("Страхование", "expense", "insurance", "#38bdf8", None, 0),
        ("Хобби", "expense", "hobby", "#a78bfa", None, 0),
        ("Благотворительность", "expense", "charity", "#fb7185", None, 0),
        ("Алкоголь", "expense", "cafe", "#c084fc", None, 0),
        ("Приколюхи", "expense", "hobby", "#f472b6", None, 0),
    ]
    db.executemany(
        "INSERT OR IGNORE INTO categories(name, type, icon, color, parent_id, is_custom) VALUES (?, ?, ?, ?, ?, ?)",
        categories,
    )
    db.executemany(
        "UPDATE categories SET icon = ? WHERE name = ? AND type = ? AND is_custom = 0",
        ((icon, name, category_type) for name, category_type, icon, *_ in categories),
    )

    if db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0:
        today = date.today().isoformat()
        db.executemany(
            "INSERT INTO accounts(name, kind, account_type, balance, annual_rate, last_accrual_date) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("Баланс на жизнь", "life", "checking", 0, 0, today),
                ("Инвестиционный баланс", "investment", "investment", 0, 12.5, today),
            ],
        )

    defaults = {
        "investment_target_percent": "20",
        "currency_target_percent": "10",
        "monthly_life_budget": "90000",
        "currency": "₽",
        "base_currency_code": "RUB",
    }
    for key, value in defaults.items():
        db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))

    if seed_demo and db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0:
        _seed_demo(db)

    db.commit()


def _apply_compatible_schema_changes(db: sqlite3.Connection) -> None:
    """Apply small additive changes for databases created before migrations existed."""
    columns = {row["name"] for row in db.execute("PRAGMA table_info(audit_log)")}
    if "actor_user_id" not in columns:
        db.execute("ALTER TABLE audit_log ADD COLUMN actor_user_id INTEGER REFERENCES users(id)")

    account_columns = {row["name"] for row in db.execute("PRAGMA table_info(accounts)")}
    if "account_type" not in account_columns:
        db.execute("ALTER TABLE accounts ADD COLUMN account_type TEXT NOT NULL DEFAULT 'checking'")
        db.execute("UPDATE accounts SET account_type = 'investment' WHERE kind = 'investment'")
    if "is_active" not in account_columns:
        db.execute("ALTER TABLE accounts ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    if "currency_code" not in account_columns:
        db.execute("ALTER TABLE accounts ADD COLUMN currency_code TEXT NOT NULL DEFAULT 'RUB'")
    if "exchange_rate" not in account_columns:
        db.execute("ALTER TABLE accounts ADD COLUMN exchange_rate REAL NOT NULL DEFAULT 1")
    if "interest_enabled" not in account_columns:
        db.execute("ALTER TABLE accounts ADD COLUMN interest_enabled INTEGER NOT NULL DEFAULT 0")
    if "interest_last_posted_month" not in account_columns:
        db.execute("ALTER TABLE accounts ADD COLUMN interest_last_posted_month TEXT")
    db.execute(
        """INSERT OR IGNORE INTO account_rate_history(account_id, effective_date, annual_rate)
           SELECT id, date('now', 'start of month'), annual_rate FROM accounts WHERE annual_rate > 0"""
    )

    transaction_columns = {row["name"] for row in db.execute("PRAGMA table_info(transactions)")}
    if "target_amount" not in transaction_columns:
        db.execute("ALTER TABLE transactions ADD COLUMN target_amount REAL")
        db.execute("UPDATE transactions SET target_amount = amount WHERE tx_type = 'transfer'")

    goal_columns = {row["name"] for row in db.execute("PRAGMA table_info(goals)")}
    if "account_id" not in goal_columns:
        db.execute("ALTER TABLE goals ADD COLUMN account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL")


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
