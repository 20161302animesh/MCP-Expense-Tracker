# MCP Expense Tracker

An [MCP](https://modelcontextprotocol.io) server for tracking personal expenses, built with [FastMCP](https://gofastmcp.com) and stored in a local SQLite database. Connect it to Claude Desktop (or any MCP client) and add, look up, correct and summarize expenses in plain language.

## Tools

| Tool | What it does |
|---|---|
| `add_expense` | Add an expense: `date`, `amount`, `product`, `category`, and optional `subcategory` and `note`. Returns the new id. |
| `list_expenses` | List expenses, optionally filtered by `start_date`, `end_date` (inclusive), `category`, and capped with `limit`. |
| `update_expense` | Change any fields of an expense by `expense_id`; fields you don't pass are left alone. Returns the updated expense. |
| `delete_expense` | Delete an expense by `expense_id`. Returns what was deleted. |
| `summarize` | Total spending per category between `start_date` and `end_date` (inclusive), optionally for one `category`. |

Inputs are validated before anything is written:

- Dates must be real calendar dates in ISO format, `YYYY-MM-DD`.
- Amounts must be positive numbers.
- `product` and `category` can't be blank. Surrounding whitespace is trimmed from all text fields.
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

Expenses are stored in `expenses.db` at the project root (git-ignored). The table is created automatically on first run. To use a different file, set the `EXPENSE_TRACKER_DB` environment variable to its path.

## Tests

```bash
uv run pytest
```

The tests call each tool through an in-memory MCP client, so argument validation is exercised too. Every test uses its own temporary database, so your real `expenses.db` is never touched.
