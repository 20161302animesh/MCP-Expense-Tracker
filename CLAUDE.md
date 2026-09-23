# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

An MCP (Model Context Protocol) expense and balance tracker built with `fastmcp` and backed by SQLite. The server lives in `src/mcp_expense_tracker/server.py`. Expense tools: `add_expense`, `list_expenses` (optional date-range, category and limit filters), `update_expense`, `delete_expense`, `summarize`. Balance tools: `add_transaction`, `list_transactions`, `update_transaction`, `delete_transaction`, `record_balance`, `get_balance`, `list_balance_snapshots`, `delete_balance_snapshot`. Dates are validated ISO `YYYY-MM-DD` and amounts must be positive. The root-level `test.py` is not a test file: it is a thin wrapper that imports and runs the package server, kept because existing client configs (e.g. Claude Desktop) launch the server with `uv run test.py`.

## Commands

This project uses `uv` for dependency management (Python >=3.13, pinned via `.python-version`).

- Install dependencies: `uv sync`
- Run the MCP server: `uv run mcp-expense-tracker` (or `uv run test.py`, which is equivalent)
- Run tests: `uv run pytest` (a single test: `uv run pytest tests/test_server.py::test_add_then_list`)

Tests live in `tests/` and call tools through an in-memory `fastmcp.Client`, so argument validation runs; `tests/conftest.py` gives each test its own temporary database via `EXPENSE_TRACKER_DB`/`server.DB_PATH`. `testpaths` is set to `tests` so the root `test.py` wrapper is never collected. No linting is configured yet.

## Architecture

- The server is defined with `fastmcp.FastMCP` and tools are registered via the `@mcp.tool()` decorator on plain functions with type-hinted signatures and docstrings (the docstring becomes the tool description exposed over MCP).
- `pyproject.toml` declares `mcp-expense-tracker = "mcp_expense_tracker:main"`; `main()` in `server.py` calls `mcp.run()` (stdio transport).
- Data is stored in `expenses.db` at the project root (git-ignored). Override the location with the `EXPENSE_TRACKER_DB` environment variable. `init_db()` runs on import: it creates the tables and backfills a debit for any expense lacking one, so it must stay idempotent.
- Tables: `expenses`; `transactions` (every credit/debit, one account; `expense_id` is set on the debit mirroring an expense); `balance_snapshots` (actual balances the user records, one per date, meaning "balance at end of that day").
- Expense tools keep their debit in sync via `_sync_expense_debit`; the transaction tools refuse to update or delete expense-linked debits.
- Balance as of a date = latest snapshot on or before it + credits − debits strictly after the snapshot date, up to that date (`_compute_balance`). With no snapshot it starts from 0.
