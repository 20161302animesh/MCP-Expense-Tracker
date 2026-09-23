import asyncio
import os
import tempfile

# Point the server at a throwaway database before it is imported, so importing
# it (which runs init_db) never touches the real expenses.db.
os.environ["EXPENSE_TRACKER_DB"] = os.path.join(tempfile.mkdtemp(), "import.db")

import pytest
from fastmcp import Client

from mcp_expense_tracker import server


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    """Give every test its own empty database."""
    monkeypatch.setattr(server, "DB_PATH", str(tmp_path / "expenses.db"))
    server.init_db()


@pytest.fixture
def call():
    """Call a tool over MCP (so argument validation runs) and return its data."""
    def _call(tool: str, **args):
        async def run():
            async with Client(server.mcp) as client:
                result = await client.call_tool(tool, args)
                return result.structured_content.get("result", result.structured_content)
        return asyncio.run(run())
    return _call


@pytest.fixture
def add(call):
    """Add an expense with sensible defaults; returns its id."""
    def _add(**overrides):
        args = {"date": "2026-09-23", "amount": 10.0, "product": "Tea", "category": "Food"}
        args.update(overrides)
        return call("add_expense", **args)["id"]
    return _add
