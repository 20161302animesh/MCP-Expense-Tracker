# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

An MCP (Model Context Protocol) expense tracker built with `fastmcp` and backed by SQLite. The server lives in `src/mcp_expense_tracker/server.py` and exposes five tools: `add_expense`, `list_expenses` (optional date-range, category and limit filters), `update_expense`, `delete_expense` and `summarize`. Dates are validated ISO `YYYY-MM-DD` and amounts must be positive. The root-level `test.py` is not a test file: it is a thin wrapper that imports and runs the package server, kept because existing client configs (e.g. Claude Desktop) launch the server with `uv run test.py`.

## Commands

This project uses `uv` for dependency management (Python >=3.13, pinned via `.python-version`).

- Install dependencies: `uv sync`
- Run the MCP server: `uv run mcp-expense-tracker` (or `uv run test.py`, which is equivalent)
- Run tests: `uv run pytest` (a single test: `uv run pytest tests/test_server.py::test_add_then_list`)

Tests live in `tests/` and call tools through an in-memory `fastmcp.Client`, so argument validation runs; `tests/conftest.py` gives each test its own temporary database via `EXPENSE_TRACKER_DB`/`server.DB_PATH`. `testpaths` is set to `tests` so the root `test.py` wrapper is never collected. No linting is configured yet.

## Architecture

- The server is defined with `fastmcp.FastMCP` and tools are registered via the `@mcp.tool()` decorator on plain functions with type-hinted signatures and docstrings (the docstring becomes the tool description exposed over MCP).
- `pyproject.toml` declares `mcp-expense-tracker = "mcp_expense_tracker:main"`; `main()` in `server.py` calls `mcp.run()` (stdio transport).
- Data is stored in `expenses.db` at the project root (git-ignored). Override the location with the `EXPENSE_TRACKER_DB` environment variable. The table is created on import by `init_db()`.
