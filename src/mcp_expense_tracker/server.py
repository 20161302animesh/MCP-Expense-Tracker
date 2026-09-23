from datetime import date
from typing import Annotated
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
# `summarize` orders them chronologically.
IsoDate = Annotated[date, Field(description="Date in ISO format, YYYY-MM-DD")]
Amount = Annotated[float, Field(gt=0, allow_inf_nan=False, description="Amount spent; must be positive")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


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

init_db()

@mcp.tool()
def add_expense(
    date: IsoDate,
    amount: Amount,
    product: Name,
    category: Name,
    subcategory: str = "",
    note: str = "",
) -> dict:
    '''Add an expense entry to the database'''
    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute(
            "INSERT INTO expenses(date, amount, product, category, subcategory, note) "
            "VALUES (?,?,?,?,?,?)",
            (date.isoformat(), amount, product, category, subcategory.strip(), note.strip())
        )
        return {"status": "ok", "id": cur.lastrowid}

COLUMNS = "id, date, amount, product, category, subcategory, note"


def _check_range(start_date: date | None, end_date: date | None) -> None:
    if start_date and end_date and start_date > end_date:
        raise ToolError(f"start_date ({start_date}) is after end_date ({end_date})")


def _get_expense(c: sqlite3.Connection, expense_id: int) -> dict:
    cur = c.execute(f"SELECT {COLUMNS} FROM expenses WHERE id = ?", (expense_id,))
    row = cur.fetchone()
    if row is None:
        raise ToolError(f"No expense with id {expense_id}")
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


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
        cur = c.execute(query, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

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
    Returns the updated expense.'''
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
        return _get_expense(c, expense_id)

@mcp.tool()
def delete_expense(expense_id: int) -> dict:
    '''Delete an expense by id. Returns the deleted expense.'''
    with sqlite3.connect(DB_PATH) as c:
        expense = _get_expense(c, expense_id)
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

        cur = c.execute(query, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
