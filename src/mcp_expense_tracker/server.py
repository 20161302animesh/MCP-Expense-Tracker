from datetime import date
from typing import Annotated, Literal
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field, StringConstraints
import os, sqlite3

# Defaults to expenses.db at the project root (src/mcp_expense_tracker/ -> ../..).
DB_PATH = os.environ.get(
    "EXPENSE_TRACKER_DB",
    os.path.join(os.path.dirname(__file__), "..", "..", "expenses.db"),
)

mcp = FastMCP("ExpenseTracker")

# Dates are stored as ISO text (YYYY-MM-DD) so that string comparison in
# queries orders them chronologically.
IsoDate = Annotated[date, Field(description="Date in ISO format, YYYY-MM-DD")]
Amount = Annotated[float, Field(gt=0, allow_inf_nan=False, description="Amount; must be positive")]
Balance = Annotated[float, Field(allow_inf_nan=False, description="Actual account balance; may be negative")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Kind = Literal["credit", "debit"]


def init_db():
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                product TEXT NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT DEFAULT '',
                note TEXT DEFAULT ''
            )
        """)
        # Every movement of money in or out of the account. Debits created for an
        # expense carry its expense_id and are kept in sync by the expense tools.
        c.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('credit', 'debit')),
                amount REAL NOT NULL,
                description TEXT NOT NULL,
                note TEXT DEFAULT '',
                expense_id INTEGER UNIQUE REFERENCES expenses(id)
            )
        """)
        # Actual balances recorded by the user, as of the end of `date`.
        c.execute("""
            CREATE TABLE IF NOT EXISTS balance_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                balance REAL NOT NULL,
                note TEXT DEFAULT ''
            )
        """)
        # Backfill debits for expenses recorded before transactions existed.
        c.execute("""
            INSERT INTO transactions(date, kind, amount, description, expense_id)
            SELECT e.date, 'debit', e.amount, e.product, e.id
            FROM expenses e
            WHERE NOT EXISTS (SELECT 1 FROM transactions t WHERE t.expense_id = e.id)
        """)

init_db()


def _sync_expense_debit(c: sqlite3.Connection, expense_id: int) -> None:
    '''Create or refresh the debit transaction that mirrors an expense.'''
    cur = c.execute("""
        UPDATE transactions
        SET (date, amount, description) = (SELECT date, amount, product FROM expenses WHERE id = ?)
        WHERE expense_id = ?
    """, (expense_id, expense_id))
    if cur.rowcount == 0:
        c.execute("""
            INSERT INTO transactions(date, kind, amount, description, expense_id)
            SELECT date, 'debit', amount, product, id FROM expenses WHERE id = ?
        """, (expense_id,))


@mcp.tool()
def add_expense(
    date: IsoDate,
    amount: Amount,
    product: Name,
    category: Name,
    subcategory: str = "",
    note: str = "",
) -> dict:
    '''Add an expense entry to the database. Also records a matching debit
    against the account balance.'''
    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute(
            "INSERT INTO expenses(date, amount, product, category, subcategory, note) "
            "VALUES (?,?,?,?,?,?)",
            (date.isoformat(), amount, product, category, subcategory.strip(), note.strip())
        )
        _sync_expense_debit(c, cur.lastrowid)
        return {"status": "ok", "id": cur.lastrowid}

COLUMNS = "id, date, amount, product, category, subcategory, note"
TRANSACTION_COLUMNS = "id, date, kind, amount, description, note, expense_id"


def _check_range(start_date: date | None, end_date: date | None) -> None:
    if start_date and end_date and start_date > end_date:
        raise ToolError(f"start_date ({start_date}) is after end_date ({end_date})")


def _rows(cur: sqlite3.Cursor) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _get_expense(c: sqlite3.Connection, expense_id: int) -> dict:
    cur = c.execute(f"SELECT {COLUMNS} FROM expenses WHERE id = ?", (expense_id,))
    rows = _rows(cur)
    if not rows:
        raise ToolError(f"No expense with id {expense_id}")
    return rows[0]


def _get_transaction(c: sqlite3.Connection, transaction_id: int) -> dict:
    cur = c.execute(f"SELECT {TRANSACTION_COLUMNS} FROM transactions WHERE id = ?", (transaction_id,))
    rows = _rows(cur)
    if not rows:
        raise ToolError(f"No transaction with id {transaction_id}")
    return rows[0]


def _reject_expense_linked(transaction: dict) -> None:
    if transaction["expense_id"] is not None:
        raise ToolError(
            f"Transaction {transaction['id']} is the debit for expense {transaction['expense_id']}; "
            "change it with update_expense or delete_expense instead"
        )


@mcp.tool()
def list_expenses(
    start_date: IsoDate | None = None,
    end_date: IsoDate | None = None,
    category: str | None = None,
    limit: Annotated[int, Field(ge=1)] | None = None,
) -> list[dict]:
    '''List expenses, optionally filtered by an inclusive date range and category.
    Results are ordered by id; limit caps how many are returned.'''
    _check_range(start_date, end_date)

    query = f"SELECT {COLUMNS} FROM expenses WHERE 1=1"
    params: list = []
    if start_date:
        query += " AND date >= ?"
        params.append(start_date.isoformat())
    if end_date:
        query += " AND date <= ?"
        params.append(end_date.isoformat())
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY id ASC"
    if limit:
        query += " LIMIT ?"
        params.append(limit)

    with sqlite3.connect(DB_PATH) as c:
        return _rows(c.execute(query, params))

@mcp.tool()
def update_expense(
    expense_id: int,
    date: IsoDate | None = None,
    amount: Amount | None = None,
    product: Name | None = None,
    category: Name | None = None,
    subcategory: str | None = None,
    note: str | None = None,
) -> dict:
    '''Update fields of an existing expense. Only the fields you pass are changed.
    Its debit transaction is updated to match. Returns the updated expense.'''
    changes = {
        "date": date.isoformat() if date else None,
        "amount": amount,
        "product": product,
        "category": category,
        "subcategory": subcategory.strip() if subcategory is not None else None,
        "note": note.strip() if note is not None else None,
    }
    changes = {k: v for k, v in changes.items() if v is not None}
    if not changes:
        raise ToolError("No fields to update were provided")

    with sqlite3.connect(DB_PATH) as c:
        _get_expense(c, expense_id)
        # Column names come from the fixed dict above, never from user input.
        assignments = ", ".join(f"{k} = ?" for k in changes)
        c.execute(f"UPDATE expenses SET {assignments} WHERE id = ?", [*changes.values(), expense_id])
        _sync_expense_debit(c, expense_id)
        return _get_expense(c, expense_id)

@mcp.tool()
def delete_expense(expense_id: int) -> dict:
    '''Delete an expense by id, along with its debit transaction.
    Returns the deleted expense.'''
    with sqlite3.connect(DB_PATH) as c:
        expense = _get_expense(c, expense_id)
        c.execute("DELETE FROM transactions WHERE expense_id = ?", (expense_id,))
        c.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        return {"status": "deleted", "expense": expense}

@mcp.tool()
def summarize(start_date: IsoDate, end_date: IsoDate, category: str | None = None) -> list[dict]:
    '''Summarize expenses by category within an inclusive date range.'''
    _check_range(start_date, end_date)

    with sqlite3.connect(DB_PATH) as c:
        query = (
            """
            SELECT category, SUM(amount) AS total_amount
            FROM expenses
            WHERE date BETWEEN ? AND ?
            """
        )
        params = [start_date.isoformat(), end_date.isoformat()]

        if category:
            query += " AND category = ?"
            params.append(category)

        query += " GROUP BY category ORDER BY category ASC"

        return _rows(c.execute(query, params))


# Balance tracking

@mcp.tool()
def add_transaction(
    date: IsoDate,
    kind: Kind,
    amount: Amount,
    description: Name,
    note: str = "",
) -> dict:
    '''Record money coming into the account (credit, e.g. salary or a refund) or
    going out that is not an expense (debit, e.g. a transfer or ATM withdrawal).
    Expenses already create their own debits, so don't add those here.'''
    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute(
            "INSERT INTO transactions(date, kind, amount, description, note) VALUES (?,?,?,?,?)",
            (date.isoformat(), kind, amount, description, note.strip())
        )
        return _get_transaction(c, cur.lastrowid)

@mcp.tool()
def list_transactions(
    start_date: IsoDate | None = None,
    end_date: IsoDate | None = None,
    kind: Kind | None = None,
    limit: Annotated[int, Field(ge=1)] | None = None,
) -> list[dict]:
    '''List credits and debits, optionally filtered by an inclusive date range and
    kind. Debits created for an expense have its expense_id set. Ordered by date.'''
    _check_range(start_date, end_date)

    query = f"SELECT {TRANSACTION_COLUMNS} FROM transactions WHERE 1=1"
    params: list = []
    if start_date:
        query += " AND date >= ?"
        params.append(start_date.isoformat())
    if end_date:
        query += " AND date <= ?"
        params.append(end_date.isoformat())
    if kind:
        query += " AND kind = ?"
        params.append(kind)
    query += " ORDER BY date ASC, id ASC"
    if limit:
        query += " LIMIT ?"
        params.append(limit)

    with sqlite3.connect(DB_PATH) as c:
        return _rows(c.execute(query, params))

@mcp.tool()
def update_transaction(
    transaction_id: int,
    date: IsoDate | None = None,
    kind: Kind | None = None,
    amount: Amount | None = None,
    description: Name | None = None,
    note: str | None = None,
) -> dict:
    '''Update fields of a manually added transaction. Only the fields you pass are
    changed. Debits that belong to an expense must be changed via update_expense.'''
    changes = {
        "date": date.isoformat() if date else None,
        "kind": kind,
        "amount": amount,
        "description": description,
        "note": note.strip() if note is not None else None,
    }
    changes = {k: v for k, v in changes.items() if v is not None}
    if not changes:
        raise ToolError("No fields to update were provided")

    with sqlite3.connect(DB_PATH) as c:
        _reject_expense_linked(_get_transaction(c, transaction_id))
        # Column names come from the fixed dict above, never from user input.
        assignments = ", ".join(f"{k} = ?" for k in changes)
        c.execute(f"UPDATE transactions SET {assignments} WHERE id = ?", [*changes.values(), transaction_id])
        return _get_transaction(c, transaction_id)

@mcp.tool()
def delete_transaction(transaction_id: int) -> dict:
    '''Delete a manually added transaction by id. Debits that belong to an expense
    are removed by deleting the expense instead. Returns the deleted transaction.'''
    with sqlite3.connect(DB_PATH) as c:
        transaction = _get_transaction(c, transaction_id)
        _reject_expense_linked(transaction)
        c.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
        return {"status": "deleted", "transaction": transaction}


def _compute_balance(c: sqlite3.Connection, as_of: str) -> dict:
    '''Balance at the end of `as_of`: the latest snapshot on or before that date,
    plus credits and minus debits dated after the snapshot, up to `as_of`.
    With no snapshot, it is the net of all transactions (starting from 0).'''
    snapshot = _rows(c.execute(
        "SELECT date, balance FROM balance_snapshots WHERE date <= ? ORDER BY date DESC LIMIT 1",
        (as_of,),
    ))
    start, opening = (snapshot[0]["date"], snapshot[0]["balance"]) if snapshot else ("", 0.0)
    credits, debits = c.execute("""
        SELECT COALESCE(SUM(CASE WHEN kind = 'credit' THEN amount END), 0),
               COALESCE(SUM(CASE WHEN kind = 'debit' THEN amount END), 0)
        FROM transactions WHERE date > ? AND date <= ?
    """, (start, as_of)).fetchone()
    return {
        "as_of": as_of,
        "balance": round(opening + credits - debits, 2),
        "snapshot_date": snapshot[0]["date"] if snapshot else None,
        "snapshot_balance": opening if snapshot else None,
        "credits_since_snapshot": round(credits, 2),
        "debits_since_snapshot": round(debits, 2),
    }


@mcp.tool()
def get_balance(as_of: IsoDate | None = None) -> dict:
    '''Get the account balance at the end of a date (default: today), computed from
    the most recent recorded balance snapshot plus credits minus debits since then.
    If no snapshot exists yet, the balance is just the net of all transactions.'''
    with sqlite3.connect(DB_PATH) as c:
        return _compute_balance(c, (as_of or date.today()).isoformat())

@mcp.tool()
def record_balance(date: IsoDate, balance: Balance, note: str = "") -> dict:
    '''Record the actual account balance (e.g. as shown in the bank app) at the end
    of a date. Replaces any snapshot already recorded for that date. Returns the
    balance the tracker expected beforehand and the difference, which shows
    spending or income that was not logged.'''
    day = date.isoformat()
    with sqlite3.connect(DB_PATH) as c:
        # Compare against what the tracker would have said without this snapshot.
        c.execute("DELETE FROM balance_snapshots WHERE date = ?", (day,))
        expected = _compute_balance(c, day)
        c.execute(
            "INSERT INTO balance_snapshots(date, balance, note) VALUES (?,?,?)",
            (day, balance, note.strip())
        )
        return {
            "status": "ok",
            "date": day,
            "balance": balance,
            "expected_balance": expected["balance"] if expected["snapshot_date"] else None,
            "difference": round(balance - expected["balance"], 2) if expected["snapshot_date"] else None,
        }

@mcp.tool()
def list_balance_snapshots(
    start_date: IsoDate | None = None,
    end_date: IsoDate | None = None,
) -> list[dict]:
    '''List recorded balance snapshots, oldest first, optionally within an
    inclusive date range.'''
    _check_range(start_date, end_date)
    query = "SELECT id, date, balance, note FROM balance_snapshots WHERE 1=1"
    params: list = []
    if start_date:
        query += " AND date >= ?"
        params.append(start_date.isoformat())
    if end_date:
        query += " AND date <= ?"
        params.append(end_date.isoformat())
    query += " ORDER BY date ASC"
    with sqlite3.connect(DB_PATH) as c:
        return _rows(c.execute(query, params))

@mcp.tool()
def delete_balance_snapshot(date: IsoDate) -> dict:
    '''Delete the balance snapshot recorded for a date. Returns what was deleted.'''
    with sqlite3.connect(DB_PATH) as c:
        rows = _rows(c.execute(
            "SELECT id, date, balance, note FROM balance_snapshots WHERE date = ?", (date.isoformat(),)
        ))
        if not rows:
            raise ToolError(f"No balance snapshot for {date.isoformat()}")
        c.execute("DELETE FROM balance_snapshots WHERE date = ?", (date.isoformat(),))
        return {"status": "deleted", "snapshot": rows[0]}

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
