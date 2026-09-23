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

@mcp.tool()
def list_expenses() -> list[dict]:
    '''List all expenses from the database'''
    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute("SELECT id, date, amount, product, category, subcategory, note FROM expenses ORDER BY id ASC")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

@mcp.tool()
def summarize(start_date: IsoDate, end_date: IsoDate, category: str | None = None) -> list[dict]:
    '''Summarize expenses by category within an inclusive date range.'''
    if start_date > end_date:
        raise ToolError(f"start_date ({start_date}) is after end_date ({end_date})")

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
