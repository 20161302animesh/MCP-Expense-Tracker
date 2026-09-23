# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

This is an early-stage scaffold for an MCP (Model Context Protocol) server built with `fastmcp`, intended to become an expense tracker. Currently `main.py` at the repo root only contains placeholder demo tools (`roll_dice`, `add_num`) and is the file actually run; the installed package `src/mcp_expense_tracker/` is a separate, unused `uv` project skeleton (its `main()` just prints a hello message) wired up via the `mcp-expense-tracker` console script entry point in `pyproject.toml`. Expect to consolidate these into one real implementation as the project grows.

## Commands

This project uses `uv` for dependency management (Python >=3.13, pinned via `.python-version`).

- Install dependencies: `uv sync`
- Run the MCP server (root demo file): `uv run main.py`
- Run the installed package entry point: `uv run mcp-expense-tracker`

There are no lint, test, or build tooling configured yet.

## Architecture

- The server is defined with `fastmcp.FastMCP` and tools are registered via the `@mcp.tool` decorator on plain functions with type-hinted signatures and docstrings (the docstring becomes the tool description exposed over MCP).
- The server runs via `mcp.run()` under a `if __name__ == "__main__"` guard.
- `pyproject.toml` declares `mcp-expense-tracker = "mcp_expense_tracker:main"` as a console script, but that target is currently unrelated placeholder code, not the FastMCP server in `main.py`.
