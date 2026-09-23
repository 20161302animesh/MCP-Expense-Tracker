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
Limit = Annotated[int, Field(ge=1)]
# Account names are validated here rather than in the database, so adding an
# account only means extending this list.
Account = Literal["bank", "cash"]
ACCOUNTS: tuple[Account, ...] = ("bank", "cash")
Kind = Literal["debit", "credit", "transfer"]

ENTRY_COLUMNS = "id, date, kind, account, to_account, amount, description, category, subcategory, note"
SNAPSHOT_COLUMNS = "id, account, date, balance, note"


def _table_columns(c: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in c.execute(f"PRAGMA table_info({table})")}


def _migrate_legacy_entries(c: sqlite3.Connection, tables: set[str]) -> None:
    '''Move entries from the older layout into the ledger. Expenses used to live in
    their own table, with a mirrored debit in `transactions`. Expenses keep their
    ids, and everything defaults to the bank account.'''
    c.execute("""
        INSERT INTO ledger(id, date, kind, account, amount, description, category, subcategory, note)
        SELECT id, date, 'debit', 'bank', amount, product, category,
               COALESCE(subcategory, ''), COALESCE(note, '')
        FROM expenses ORDER BY id
    """)
    if "transactions" in tables:
        # Mirrored expense debits are already covered by the expenses above.
        c.execute("""
            INSERT INTO ledger(date, kind, account, amount, description, category, note)
            SELECT date, kind, 'bank', amount, description, 'Uncategorized', COALESCE(note, '')
            FROM transactions WHERE expense_id IS NULL ORDER BY date, id
        """)
        c.execute("DROP TABLE transactions")
    c.execute("DROP TABLE expenses")


def init_db():
    # autocommit=False runs the schema changes and migration in one transaction,
    # so a failed migration leaves the old tables untouched.
    with sqlite3.connect(DB_PATH, autocommit=False) as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

        # Every movement of money. A debit is spending (including P2P payments), a
        # credit is income, and a transfer moves money between your own accounts
        # (e.g. an ATM withdrawal from bank to cash), so it is never spending.
        c.execute("""
            CREATE TABLE IF NOT EXISTS ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('debit', 'credit', 'transfer')),
                account TEXT NOT NULL,
                to_account TEXT,
                amount REAL NOT NULL CHECK (amount > 0),
                description TEXT NOT NULL,
                category TEXT,
                subcategory TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                CHECK ((kind = 'transfer') = (to_account IS NOT NULL)),
                CHECK ((kind = 'transfer') = (category IS NULL)),
                CHECK (to_account IS NULL OR to_account != account)
            )
        """)
        if "expenses" in tables:
            _migrate_legacy_entries(c, tables)

        # Actual balances recorded by the user, per account, as of the end of `date`.
        legacy_snapshots = (
            "balance_snapshots" in tables and "account" not in _table_columns(c, "balance_snapshots")
        )
        if legacy_snapshots:
            c.execute("ALTER TABLE balance_snapshots RENAME TO legacy_balance_snapshots")
        c.execute("""
            CREATE TABLE IF NOT EXISTS balance_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account TEXT NOT NULL,
                date TEXT NOT NULL,
                balance REAL NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                UNIQUE (account, date)
            )
        """)
        if legacy_snapshots:
            c.execute("""
                INSERT INTO balance_snapshots(account, date, balance, note)
                SELECT 'bank', date, balance, COALESCE(note, '') FROM legacy_balance_snapshots
            """)
            c.execute("DROP TABLE legacy_balance_snapshots")

init_db()


def _check_range(start_date: date | None, end_date: date | None) -> None:
    if start_date and end_date and start_date > end_date:
        raise ToolError(f"start_date ({start_date}) is after end_date ({end_date})")


def _rows(cur: sqlite3.Cursor) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _get_entry(c: sqlite3.Connection, entry_id: int) -> dict:
    rows = _rows(c.execute(f"SELECT {ENTRY_COLUMNS} FROM ledger WHERE id = ?", (entry_id,)))
    if not rows:
        raise ToolError(f"No entry with id {entry_id}")
    return rows[0]


def _insert_entry(**fields) -> dict:
    # Column names come from the calling tool, never from user input.
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute(f"INSERT INTO ledger({cols}) VALUES ({marks})", list(fields.values()))
        return _get_entry(c, cur.lastrowid)


# Entries

@mcp.tool()
def add_expense(
    date: IsoDate,
    amount: Amount,
    product: Name,
    category: Name,
    account: Account = "bank",
    subcategory: str = "",
    note: str = "",
) -> dict:
    '''Record money spent. Use account "bank" (the default) for bank and UPI/Google
    Pay payments and "cash" for cash purchases. P2P payments to other people are
    expenses too. Returns the new entry.'''
    return _insert_entry(
        date=date.isoformat(), kind="debit", account=account, amount=amount,
        description=product, category=category, subcategory=subcategory.strip(), note=note.strip(),
    )

@mcp.tool()
def add_income(
    date: IsoDate,
    amount: Amount,
    description: Name,
    category: Name,
    account: Account = "bank",
    note: str = "",
) -> dict:
    '''Record money received into an account, e.g. salary, a refund, or a P2P
    payment from someone. Returns the new entry.'''
    return _insert_entry(
        date=date.isoformat(), kind="credit", account=account, amount=amount,
        description=description, category=category, note=note.strip(),
    )

@mcp.tool()
def transfer(
    date: IsoDate,
    amount: Amount,
    from_account: Account,
    to_account: Account,
    description: Name = "Transfer",
    note: str = "",
) -> dict:
    '''Move money between your own accounts, e.g. an ATM withdrawal (bank to cash,
    description "ATM withdrawal") or a cash deposit (cash to bank). Transfers change
    both balances but are never counted as spending. Returns the new entry.'''
    if from_account == to_account:
        raise ToolError("from_account and to_account must be different")
    return _insert_entry(
        date=date.isoformat(), kind="transfer", account=from_account, to_account=to_account,
        amount=amount, description=description, note=note.strip(),
    )

@mcp.tool()
def list_entries(
    start_date: IsoDate | None = None,
    end_date: IsoDate | None = None,
    kind: Kind | None = None,
    account: Account | None = None,
    category: str | None = None,
    limit: Limit | None = None,
) -> list[dict]:
    '''List ledger entries (expenses, income and transfers), ordered by date, with
    optional filters: an inclusive date range, kind ("debit" = expense, "credit" =
    income, "transfer"), account (matches transfers into or out of it), category,
    and a limit.'''
    _check_range(start_date, end_date)

    query = f"SELECT {ENTRY_COLUMNS} FROM ledger WHERE 1=1"
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
    if account:
        query += " AND (account = ? OR to_account = ?)"
        params += [account, account]
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY date ASC, id ASC"
    if limit:
        query += " LIMIT ?"
        params.append(limit)

    with sqlite3.connect(DB_PATH) as c:
        return _rows(c.execute(query, params))

@mcp.tool()
def update_entry(
    entry_id: int,
    date: IsoDate | None = None,
    amount: Amount | None = None,
    description: Name | None = None,
    category: Name | None = None,
    subcategory: str | None = None,
    note: str | None = None,
    account: Account | None = None,
    to_account: Account | None = None,
) -> dict:
    '''Update fields of an entry. Only the fields you pass are changed. For a
    transfer, `account` is where the money came from and `to_account` where it
    went; transfers have no category. To change an entry's kind, delete it and add
    it again. Returns the updated entry.'''
    changes = {
        "date": date.isoformat() if date else None,
        "amount": amount,
        "description": description,
        "category": category,
        "subcategory": subcategory.strip() if subcategory is not None else None,
        "note": note.strip() if note is not None else None,
        "account": account,
        "to_account": to_account,
    }
    changes = {k: v for k, v in changes.items() if v is not None}
    if not changes:
        raise ToolError("No fields to update were provided")

    with sqlite3.connect(DB_PATH) as c:
        entry = _get_entry(c, entry_id)
        if entry["kind"] == "transfer":
            if "category" in changes or "subcategory" in changes:
                raise ToolError("Transfers have no category or subcategory")
            if {**entry, **changes}["account"] == {**entry, **changes}["to_account"]:
                raise ToolError("A transfer's account and to_account must be different")
        elif "to_account" in changes:
            raise ToolError("Only transfers have a to_account")
        # Column names come from the fixed dict above, never from user input.
        assignments = ", ".join(f"{k} = ?" for k in changes)
        c.execute(f"UPDATE ledger SET {assignments} WHERE id = ?", [*changes.values(), entry_id])
        return _get_entry(c, entry_id)

@mcp.tool()
def delete_entry(entry_id: int) -> dict:
    '''Delete an entry by id. Returns the deleted entry.'''
    with sqlite3.connect(DB_PATH) as c:
        entry = _get_entry(c, entry_id)
        c.execute("DELETE FROM ledger WHERE id = ?", (entry_id,))
        return {"status": "deleted", "entry": entry}

@mcp.tool()
def summarize(
    start_date: IsoDate,
    end_date: IsoDate,
    category: str | None = None,
    account: Account | None = None,
    kind: Literal["debit", "credit"] = "debit",
) -> list[dict]:
    '''Total spending per category within an inclusive date range, across all
    accounts unless `account` is given. Pass kind="credit" to total income instead.
    Transfers between your own accounts (e.g. ATM withdrawals) are not spending;
    what you buy with the cash is.'''
    _check_range(start_date, end_date)

    query = """
        SELECT category, ROUND(SUM(amount), 2) AS total_amount
        FROM ledger
        WHERE kind = ? AND date BETWEEN ? AND ?
    """
    params = [kind, start_date.isoformat(), end_date.isoformat()]
    if category:
        query += " AND category = ?"
        params.append(category)
    if account:
        query += " AND account = ?"
        params.append(account)
    query += " GROUP BY category ORDER BY category ASC"

    with sqlite3.connect(DB_PATH) as c:
        return _rows(c.execute(query, params))


# Balances

def _account_balance(c: sqlite3.Connection, account: str, as_of: str) -> dict:
    '''Balance of one account at the end of `as_of`: its latest snapshot on or before
    that date, plus money in and minus money out dated after the snapshot, up to
    `as_of`. With no snapshot it starts from 0.'''
    snapshot = _rows(c.execute(
        "SELECT date, balance FROM balance_snapshots WHERE account = ? AND date <= ? "
        "ORDER BY date DESC LIMIT 1",
        (account, as_of),
    ))
    start, opening = (snapshot[0]["date"], snapshot[0]["balance"]) if snapshot else ("", 0.0)
    # Only rows touching this account are selected, so a credit here is income into
    # it and a transfer is either into it (to_account) or out of it (account).
    money_in, money_out = c.execute("""
        SELECT COALESCE(SUM(CASE WHEN kind = 'credit' OR to_account = :a THEN amount END), 0),
               COALESCE(SUM(CASE WHEN kind IN ('debit', 'transfer') AND account = :a THEN amount END), 0)
        FROM ledger
        WHERE (account = :a OR to_account = :a) AND date > :start AND date <= :as_of
    """, {"a": account, "start": start, "as_of": as_of}).fetchone()
    return {
        "account": account,
        "balance": round(opening + money_in - money_out, 2),
        "snapshot_date": snapshot[0]["date"] if snapshot else None,
        "snapshot_balance": opening if snapshot else None,
        "money_in_since_snapshot": round(money_in, 2),
        "money_out_since_snapshot": round(money_out, 2),
    }


@mcp.tool()
def get_balance(as_of: IsoDate | None = None, account: Account | None = None) -> dict:
    '''Get account balances at the end of a date (default: today): each account's
    most recent recorded snapshot plus money in and minus money out since then, and
    the total across accounts. Pass `account` for just one. An account with no
    snapshot yet starts from 0.'''
    day = (as_of or date.today()).isoformat()
    with sqlite3.connect(DB_PATH) as c:
        balances = [_account_balance(c, a, day) for a in ([account] if account else ACCOUNTS)]
    return {
        "as_of": day,
        "accounts": balances,
        "total": round(sum(b["balance"] for b in balances), 2),
    }

@mcp.tool()
def record_balance(account: Account, date: IsoDate, balance: Balance, note: str = "") -> dict:
    '''Record the actual balance of an account at the end of a date (e.g. from the
    bank app, or cash counted in hand). Replaces any snapshot already recorded for
    that account and date. Returns the balance the tracker expected beforehand and
    the difference, which shows spending or income that was not logged.'''
    day = date.isoformat()
    with sqlite3.connect(DB_PATH) as c:
        # Compare against what the tracker would have said without this snapshot.
        c.execute("DELETE FROM balance_snapshots WHERE account = ? AND date = ?", (account, day))
        expected = _account_balance(c, account, day)
        c.execute(
            "INSERT INTO balance_snapshots(account, date, balance, note) VALUES (?,?,?,?)",
            (account, day, balance, note.strip())
        )
        anchored = expected["snapshot_date"] is not None
        return {
            "status": "ok",
            "account": account,
            "date": day,
            "balance": balance,
            "expected_balance": expected["balance"] if anchored else None,
            "difference": round(balance - expected["balance"], 2) if anchored else None,
        }

@mcp.tool()
def list_balance_snapshots(
    account: Account | None = None,
    start_date: IsoDate | None = None,
    end_date: IsoDate | None = None,
) -> list[dict]:
    '''List recorded balance snapshots, oldest first, optionally for one account
    and within an inclusive date range.'''
    _check_range(start_date, end_date)
    query = f"SELECT {SNAPSHOT_COLUMNS} FROM balance_snapshots WHERE 1=1"
    params: list = []
    if account:
        query += " AND account = ?"
        params.append(account)
    if start_date:
        query += " AND date >= ?"
        params.append(start_date.isoformat())
    if end_date:
        query += " AND date <= ?"
        params.append(end_date.isoformat())
    query += " ORDER BY date ASC, account ASC"
    with sqlite3.connect(DB_PATH) as c:
        return _rows(c.execute(query, params))

@mcp.tool()
def delete_balance_snapshot(account: Account, date: IsoDate) -> dict:
    '''Delete the balance snapshot recorded for an account on a date. Returns what
    was deleted.'''
    with sqlite3.connect(DB_PATH) as c:
        rows = _rows(c.execute(
            f"SELECT {SNAPSHOT_COLUMNS} FROM balance_snapshots WHERE account = ? AND date = ?",
            (account, date.isoformat()),
        ))
        if not rows:
            raise ToolError(f"No {account} balance snapshot for {date.isoformat()}")
        c.execute("DELETE FROM balance_snapshots WHERE id = ?", (rows[0]["id"],))
        return {"status": "deleted", "snapshot": rows[0]}

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
