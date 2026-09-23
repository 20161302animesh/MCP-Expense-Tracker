import sqlite3

import pytest

from mcp_expense_tracker import server

EXPENSES = """
    CREATE TABLE expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, amount REAL NOT NULL,
        product TEXT NOT NULL, category TEXT NOT NULL, subcategory TEXT DEFAULT '', note TEXT DEFAULT ''
    )
"""
TRANSACTIONS = """
    CREATE TABLE transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, kind TEXT NOT NULL,
        amount REAL NOT NULL, description TEXT NOT NULL, note TEXT DEFAULT '',
        expense_id INTEGER UNIQUE REFERENCES expenses(id)
    )
"""
SNAPSHOTS = """
    CREATE TABLE balance_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL UNIQUE,
        balance REAL NOT NULL, note TEXT DEFAULT ''
    )
"""


@pytest.fixture
def legacy_db(tmp_path, monkeypatch):
    """Point the server at a fresh file for a hand-built legacy database."""
    path = str(tmp_path / "legacy.db")
    monkeypatch.setattr(server, "DB_PATH", path)
    return path


def tables(path):
    with sqlite3.connect(path) as c:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} - {"sqlite_sequence"}


def seed_expenses(c):
    c.execute(EXPENSES)
    c.executemany(
        "INSERT INTO expenses(id, date, amount, product, category, subcategory, note) VALUES (?,?,?,?,?,?,?)",
        [(2, "2026-09-23", 48, "Auto ride", "Transport", "Auto", "PG to office"),
         (6, "2026-09-22", 60, "Chicken burger", "Food", "", ""),
         (7, "2026-09-23", 60, "Chicken burger", "Food", "", "")],
    )


def test_migrates_expenses_only_layout(legacy_db, call):
    with sqlite3.connect(legacy_db) as c:
        seed_expenses(c)
    server.init_db()

    assert tables(legacy_db) == {"ledger", "balance_snapshots"}
    entries = call("list_entries")
    assert [(e["id"], e["kind"], e["account"], e["description"], e["amount"]) for e in entries] == [
        (6, "debit", "bank", "Chicken burger", 60.0),
        (2, "debit", "bank", "Auto ride", 48.0),
        (7, "debit", "bank", "Chicken burger", 60.0),
    ]
    assert entries[1]["subcategory"] == "Auto" and entries[1]["note"] == "PG to office"
    # New entries continue after the highest migrated id.
    assert call("add_expense", date="2026-09-24", amount=1, product="Tea", category="Food")["id"] == 8


def test_migrates_transactions_and_snapshots_layout(legacy_db, call):
    with sqlite3.connect(legacy_db) as c:
        seed_expenses(c)
        c.execute(TRANSACTIONS)
        c.executemany(
            "INSERT INTO transactions(date, kind, amount, description, note, expense_id) VALUES (?,?,?,?,?,?)",
            [("2026-09-23", "debit", 48, "Auto ride", "", 2),          # mirrors an expense: dropped
             ("2026-09-01", "credit", 50000, "Salary", "Sept", None),  # manual: kept
             ("2026-09-10", "debit", 500, "Rent share", "", None)],    # manual: kept
        )
        c.execute(SNAPSHOTS)
        c.execute("INSERT INTO balance_snapshots(date, balance, note) VALUES ('2026-09-15', 12000, 'app')")
    server.init_db()

    assert tables(legacy_db) == {"ledger", "balance_snapshots"}
    entries = call("list_entries")
    assert len(entries) == 5
    manual = [e for e in entries if e["id"] not in (2, 6, 7)]
    assert [(e["kind"], e["description"], e["category"], e["note"]) for e in manual] == [
        ("credit", "Salary", "Uncategorized", "Sept"),
        ("debit", "Rent share", "Uncategorized", ""),
    ]
    assert call("list_balance_snapshots") == [
        {"id": 1, "account": "bank", "date": "2026-09-15", "balance": 12000.0, "note": "app"},
    ]


def test_init_db_is_idempotent(legacy_db, call):
    with sqlite3.connect(legacy_db) as c:
        seed_expenses(c)
    server.init_db()
    server.init_db()
    assert len(call("list_entries")) == 3


def test_failed_migration_leaves_legacy_tables_untouched(legacy_db):
    with sqlite3.connect(legacy_db) as c:
        seed_expenses(c)
        # A NULL product violates the ledger's NOT NULL description, failing the copy.
        c.execute("DROP TABLE expenses")
        c.execute(EXPENSES.replace("product TEXT NOT NULL", "product TEXT"))
        c.execute("INSERT INTO expenses(date, amount, product, category) VALUES ('2026-09-01', 5, NULL, 'Food')")
    with pytest.raises(sqlite3.IntegrityError):
        server.init_db()
    assert "ledger" not in tables(legacy_db)
    with sqlite3.connect(legacy_db) as c:
        assert c.execute("SELECT COUNT(*) FROM expenses").fetchone() == (1,)
