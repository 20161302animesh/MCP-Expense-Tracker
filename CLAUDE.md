# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

An MCP (Model Context Protocol) expense and balance tracker built with `fastmcp` and backed by SQLite. It tracks two accounts, `bank` (including UPI/Google Pay) and `cash`. The server lives in `src/mcp_expense_tracker/server.py`. Entry tools: `add_expense`, `add_income`, `transfer`, `list_entries`, `update_entry`, `delete_entry`, `summarize`. Balance tools: `record_balance`, `get_balance`, `list_balance_snapshots`, `delete_balance_snapshot`. Dates are validated ISO `YYYY-MM-DD` and amounts must be positive. The root-level `test.py` is not a test file: it is a thin wrapper that imports and runs the package server, kept because existing client configs (e.g. Claude Desktop) launch the server with `uv run test.py`.

## Commands

This project uses `uv` for dependency management (Python >=3.13, pinned via `.python-version`).

- Install dependencies: `uv sync`
- Run the MCP server: `uv run mcp-expense-tracker` (or `uv run test.py`, which is equivalent)
- Run tests: `uv run pytest` (a single test: `uv run pytest tests/test_entries.py::test_add_expense_returns_entry`)

Tests live in `tests/` (`test_entries.py`, `test_balance.py`, `test_migration.py`) and call tools through an in-memory `fastmcp.Client`, so argument validation runs; `tests/conftest.py` gives each test its own temporary database via `EXPENSE_TRACKER_DB`/`server.DB_PATH`. `testpaths` is set to `tests` so the root `test.py` wrapper is never collected. No linting is configured yet.

## Architecture

- The server is defined with `fastmcp.FastMCP` and tools are registered via the `@mcp.tool()` decorator on plain functions with type-hinted signatures and docstrings (the docstring becomes the tool description exposed over MCP).
- `pyproject.toml` declares `mcp-expense-tracker = "mcp_expense_tracker:main"`; `main()` in `server.py` calls `mcp.run()` (stdio transport).
- Data is stored in `expenses.db` at the project root (git-ignored). Override the location with the `EXPENSE_TRACKER_DB` environment variable.
- Tables:
  - `ledger`: one row per money movement. `kind` is `debit` (spending, including P2P payments), `credit` (income) or `transfer` (between own accounts, e.g. ATM withdrawal bank→cash; `account` is the source, `to_account` the destination, no category). Table CHECKs enforce: `to_account` set iff transfer, `category` NULL iff transfer, and source ≠ destination.
  - `balance_snapshots`: actual balances the user records, unique per `(account, date)`, meaning "balance at end of that day".
- Account names are validated only by the `Account` Literal and `ACCOUNTS` tuple in Python, not in the DB, so adding an account means extending those.
- Balance of an account as of a date (`_account_balance`) = its latest snapshot on or before the date + credits and transfers in − debits and transfers out, strictly after the snapshot date up to that date. With no snapshot it starts from 0. Transfers never count as spending in `summarize`.
- `init_db()` runs on import inside a single `autocommit=False` transaction. It creates the tables and migrates older layouts (separate `expenses` + `transactions` tables, and `balance_snapshots` without `account`) into the current one, keeping expense ids and defaulting to `bank`. It must stay idempotent.
