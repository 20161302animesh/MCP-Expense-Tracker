# MCP Expense Tracker

An [MCP](https://modelcontextprotocol.io) server for tracking personal expenses, income and the balances of your bank account and cash in hand, built with [FastMCP](https://gofastmcp.com) and stored in a local SQLite database. Connect it to Claude Desktop (or any MCP client) and log, look up, correct and summarize your money in plain language.

## Accounts

There are two accounts:

- **`bank`**: your bank account, including UPI/Google Pay payments drawn from it. This is the default.
- **`cash`**: cash in hand.

## Tools

### Recording and editing entries

| Tool | What it does |
|---|---|
| `add_expense` | Record money spent: `date`, `amount`, `product`, `category`, optional `account` (default `bank`), `subcategory` and `note`. P2P payments to other people are expenses too. |
| `add_income` | Record money received (salary, refunds, P2P payments to you): `date`, `amount`, `description`, `category`, optional `account` and `note`. |
| `transfer` | Move money between your own accounts: `date`, `amount`, `from_account`, `to_account`, optional `description` and `note`. Use it for ATM withdrawals (`bank` → `cash`) and cash deposits (`cash` → `bank`). |
| `list_entries` | List entries by date, optionally filtered by `start_date`, `end_date` (inclusive), `kind` (`debit`, `credit`, `transfer`), `account`, `category`, and capped with `limit`. |
| `update_entry` | Change any fields of an entry by `entry_id`; fields you don't pass are left alone. |
| `delete_entry` | Delete an entry by `entry_id`. Returns what was deleted. |
| `summarize` | Total spending per category between `start_date` and `end_date` (inclusive), optionally for one `category` or `account`. Pass `kind="credit"` to total income instead. |

### Balances

| Tool | What it does |
|---|---|
| `record_balance` | Record the actual balance of an `account` at the end of a `date` (from the bank app, or cash counted in hand). Returns the balance the tracker expected and the difference. |
| `get_balance` | Balances at the end of `as_of` (default today) for each account, plus the total. Pass `account` for just one. |
| `list_balance_snapshots` | List recorded balances, optionally for one `account` and within a date range. |
| `delete_balance_snapshot` | Delete the snapshot for an `account` on a `date`. |

## How it works

Every entry is one row in a single ledger, with a `kind`:

| Kind | Meaning | Effect on balances | Counts as spending? |
|---|---|---|---|
| `debit` | An expense | Takes money out of its account | Yes |
| `credit` | Income | Adds money to its account | No (it's income) |
| `transfer` | Money moved between your own accounts | Out of `account`, into `to_account`; the total is unchanged | No |

Treating an ATM withdrawal as a transfer means every rupee is counted once. The withdrawal moves money from `bank` to `cash`, and what you later buy with that cash is recorded as a `cash` expense.

For each account, the balance is its latest recorded snapshot, plus money in and minus money out after that snapshot's date:

- A snapshot is the real balance at the end of its date, so entries on or before that date are already included in it.
- There's at most one snapshot per account per date. Recording another for the same account and date replaces it.
- Before an account's first snapshot, its balance starts from 0. Record a snapshot to anchor it to reality.
- When you record a snapshot, a non-zero `difference` means money moved that wasn't logged: negative for untracked spending, positive for untracked income.

## Validation

Inputs are validated before anything is written:

- Dates must be real calendar dates in ISO format, `YYYY-MM-DD`.
- Amounts must be positive numbers. Recorded balances can be negative (for an overdraft) but must be finite.
- `account` must be `bank` or `cash`, and a transfer's two accounts must differ.
- `product`, `description` and `category` can't be blank; transfers have no category. Surrounding whitespace is trimmed from all text fields.
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

Data is stored in `expenses.db` at the project root (git-ignored), in two tables:

- **`ledger`**: every expense, income and transfer.
- **`balance_snapshots`**: the actual balances you record, per account and date.

Tables are created automatically on startup. Databases from earlier versions, which had separate `expenses` and `transactions` tables, are migrated in a single transaction. Expense ids are kept, and older entries are assigned to `bank`. To use a different file, set the `EXPENSE_TRACKER_DB` environment variable to its path.

## Tests

```bash
uv run pytest
```

The tests call each tool through an in-memory MCP client, so argument validation is exercised too. Every test uses its own temporary database, so your real `expenses.db` is never touched.
