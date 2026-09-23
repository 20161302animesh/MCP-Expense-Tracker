import asyncio

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from mcp_expense_tracker import server


def test_exposes_all_tools():
    async def names():
        async with Client(server.mcp) as client:
            return {t.name for t in await client.list_tools()}
    assert asyncio.run(names()) == {
        "add_expense", "list_expenses", "update_expense", "delete_expense", "summarize",
        "add_transaction", "list_transactions", "update_transaction", "delete_transaction",
        "get_balance", "record_balance", "list_balance_snapshots", "delete_balance_snapshot",
    }


# add_expense

def test_add_then_list(call, add):
    expense_id = add(amount=48, product="Auto ride", category="Transport",
                     subcategory="Auto", note="PG to office")
    assert call("list_expenses") == [{
        "id": expense_id, "date": "2026-09-23", "amount": 48.0, "product": "Auto ride",
        "category": "Transport", "subcategory": "Auto", "note": "PG to office",
    }]


def test_add_strips_whitespace(call, add):
    add(product="  Tea ", category=" Food ", subcategory=" Hot ", note=" cup ")
    [row] = call("list_expenses")
    assert (row["product"], row["category"], row["subcategory"], row["note"]) == ("Tea", "Food", "Hot", "cup")


def test_add_accepts_numeric_string_amount(call, add):
    add(amount="30")
    assert call("list_expenses")[0]["amount"] == 30.0


@pytest.mark.parametrize("date", ["24/09/2026", "2026-02-30", "Sept 1", "2026-09-24T10:00:00", 1790000000])
def test_add_rejects_bad_dates(add, date):
    with pytest.raises(ToolError):
        add(date=date)


@pytest.mark.parametrize("amount", [0, -5, "abc", "inf"])
def test_add_rejects_bad_amounts(add, amount):
    with pytest.raises(ToolError):
        add(amount=amount)


@pytest.mark.parametrize("field", ["product", "category"])
def test_add_rejects_blank_names(add, field):
    with pytest.raises(ToolError):
        add(**{field: "   "})


# list_expenses

@pytest.fixture
def sample(add):
    return [
        add(date="2026-09-01", amount=5, category="Food"),
        add(date="2026-09-15", amount=20, category="Transport"),
        add(date="2026-09-30", amount=7, category="Food"),
        add(date="2026-10-01", amount=100, category="Rent"),
    ]


def ids(rows):
    return [r["id"] for r in rows]


def test_list_date_range_is_inclusive(call, sample):
    rows = call("list_expenses", start_date="2026-09-01", end_date="2026-09-30")
    assert ids(rows) == sample[:3]


def test_list_open_ended_ranges(call, sample):
    assert ids(call("list_expenses", start_date="2026-09-30")) == sample[2:]
    assert ids(call("list_expenses", end_date="2026-09-15")) == sample[:2]


def test_list_category_and_limit(call, sample):
    assert ids(call("list_expenses", category="Food")) == [sample[0], sample[2]]
    assert ids(call("list_expenses", category="Food", limit=1)) == [sample[0]]


def test_list_rejects_reversed_range(call):
    with pytest.raises(ToolError, match="after end_date"):
        call("list_expenses", start_date="2026-09-30", end_date="2026-09-01")


def test_list_rejects_zero_limit(call):
    with pytest.raises(ToolError):
        call("list_expenses", limit=0)


# update_expense

def test_update_changes_only_given_fields(call, add):
    expense_id = add(note="old")
    updated = call("update_expense", expense_id=expense_id, amount=65, note=" extra cheese ")
    assert updated == {
        "id": expense_id, "date": "2026-09-23", "amount": 65.0, "product": "Tea",
        "category": "Food", "subcategory": "", "note": "extra cheese",
    }
    assert call("list_expenses") == [updated]


def test_update_can_clear_note(call, add):
    expense_id = add(note="old")
    assert call("update_expense", expense_id=expense_id, note="")["note"] == ""


def test_update_validates_fields(call, add):
    expense_id = add()
    with pytest.raises(ToolError):
        call("update_expense", expense_id=expense_id, amount=-1)
    with pytest.raises(ToolError):
        call("update_expense", expense_id=expense_id, date="22/09/2026")
    assert call("list_expenses")[0]["amount"] == 10.0


def test_update_requires_a_field(call, add):
    with pytest.raises(ToolError, match="No fields"):
        call("update_expense", expense_id=add())


def test_update_unknown_id(call):
    with pytest.raises(ToolError, match="No expense with id 999"):
        call("update_expense", expense_id=999, amount=1)


# delete_expense

def test_delete_returns_and_removes_expense(call, add):
    keep, gone = add(product="Keep"), add(product="Gone")
    result = call("delete_expense", expense_id=gone)
    assert result["status"] == "deleted"
    assert result["expense"]["product"] == "Gone"
    assert ids(call("list_expenses")) == [keep]


def test_delete_unknown_id(call):
    with pytest.raises(ToolError, match="No expense with id 1"):
        call("delete_expense", expense_id=1)


# summarize

def test_summarize_totals_by_category(call, sample):
    assert call("summarize", start_date="2026-09-01", end_date="2026-09-30") == [
        {"category": "Food", "total_amount": 12.0},
        {"category": "Transport", "total_amount": 20.0},
    ]


def test_summarize_category_filter(call, sample):
    assert call("summarize", start_date="2026-09-01", end_date="2026-12-31", category="Rent") == [
        {"category": "Rent", "total_amount": 100.0},
    ]


def test_summarize_empty_range(call, sample):
    assert call("summarize", start_date="2025-01-01", end_date="2025-12-31") == []


def test_summarize_rejects_reversed_range(call):
    with pytest.raises(ToolError, match="after end_date"):
        call("summarize", start_date="2026-09-30", end_date="2026-09-01")
