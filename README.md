# MCP Expense Tracker

An [MCP](https://modelcontextprotocol.io) server for tracking personal expenses and your account balance, built with [FastMCP](https://gofastmcp.com) and stored in a local SQLite database. Connect it to Claude Desktop (or any MCP client) and add, look up, correct and summarize expenses in plain language.

## Tools

### Expenses

| Tool | What it does |
|---|---|
| `add_expense` | Add an expense: `date`, `amount`, `product`, `category`, and optional `subcategory` and `note`. Also records a matching debit. Returns the new id. |
| `list_expenses` | List expenses, optionally filtered by `start_date`, `end_date` (inclusive), `category`, and capped with `limit`. |
| `update_expense` | Change any fields of an expense by `expense_id`; fields you don't pass are left alone. Its debit is updated to match. Returns the updated expense. |
| `delete_expense` | Delete an expense (and its debit) by `expense_id`. Returns what was deleted. |
| `summarize` | Total spending per category between `start_date` and `end_date` (inclusive), optionally for one `category`. |

### Balance

The tracker keeps a single account balance (e.g. a bank account that UPI payments also draw from).

| Tool | What it does |
|---|---|
| `add_transaction` | Record a `credit` (salary, refund) or a non-expense `debit` (transfer, ATM withdrawal): `date`, `kind`, `amount`, `description`, optional `note`. |
| `list_transactions` | List credits and debits, optionally filtered by `start_date`, `end_date`, `kind`, and capped with `limit`. Expense debits show their `expense_id`. |
| `update_transaction` | Change fields of a manually added transaction by `transaction_id`. |
| `delete_transaction` | Delete a manually added transaction by `transaction_id`. |
| `record_balance` | Record the actual balance at the end of a `date` (e.g. from your bank app). Returns the balance the tracker expected and the difference. |
| `get_balance` | Balance at the end of `as_of` (default today): the latest snapshot on or before that date, plus credits and minus debits after it. |
| `list_balance_snapshots` | List recorded balances, optionally within a date range. |
| `delete_balance_snapshot` | Delete the snapshot for a `date`. |

How the balance works:

- Every expense automatically creates a linked debit. Change or remove those through the expense tools; `update_transaction` and `delete_transaction` refuse to touch them.
- A snapshot is the real balance at the end of its date, so transactions on or before that date are already included in it. Only later transactions are added or subtracted.
- There's at most one snapshot per date; recording another for the same date replaces it.
- Before your first snapshot, `get_balance` is just credits minus debits starting from 0. Record a snapshot to anchor it to your real balance.
- When you record a snapshot, a non-zero `difference` means money moved that wasn't logged: negative for untracked spending, positive for untracked income.

### Validation

Inputs are validated before anything is written:

- Dates must be real calendar dates in ISO format, `YYYY-MM-DD`.
- Amounts must be positive numbers. Recorded balances can be negative (for an overdraft) but must be finite.
- `product`, `category` and `description` can't be blank. Surrounding whitespace is trimmed from all text fields.
- `kind` must be `credit` or `debit`.
- Date ranges must not end before they start.

## Setup

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Running

```bash
uv run mcp-expense-tracker
```

The server speaks MCP over stdio, so it's normally started by an MCP client rather than by hand. `uv run test.py` starts the same server; it's kept for existing client configs that use it.

### Claude Desktop

Add this to `claude_desktop_config.json` (adjust the paths), then fully restart Claude Desktop:

```json
{
  "mcpServers": {
    "expense-tracker": {
      "command": "C:\\Users\\<you>\\.local\\bin\\uv.exe",
      "args": ["--directory", "D:\\MCP-Expense-Tracker", "run", "mcp-expense-tracker"]
    }
  }
}
```

Claude Desktop only picks up code changes after a full restart, which relaunches the server.

## Data

Data is stored in `expenses.db` at the project root (git-ignored), in three tables: `expenses`, `transactions` and `balance_snapshots`. Tables are created automatically on startup, and any expense without a debit (such as ones recorded before balance tracking existed) gets one backfilled. To use a different file, set the `EXPENSE_TRACKER_DB` environment variable to its path.

## Tests

```bash
uv run pytest
```

The tests call each tool through an in-memory MCP client, so argument validation is exercised too. Every test uses its own temporary database, so your real `expenses.db` is never touched.
