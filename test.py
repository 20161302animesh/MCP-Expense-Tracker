# Kept so existing client configs that run `uv run test.py` keep working.
# The server now lives in src/mcp_expense_tracker/server.py.
from mcp_expense_tracker.server import main, mcp

if __name__ == "__main__":
    main()
