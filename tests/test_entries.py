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
        "add_expense", "add_income", "transfer", "list_entries", "update_entry", "delete_entry",
        "summarize", "get_balance", "record_balance", "list_balance_snapshots", "delete_balance_snapshot",
    }


def ids(rows):
    return [r["id"] for r in rows]


# add_expense

def test_add_expense_returns_entry(call):
    entry = call("add_expense", date="2026-09-23", amount=48, product="Auto ride",
                 category="Transport", subcategory="Auto", note="PG to office")
    assert entry == {
        "id": entry["id"], "date": "2026-09-23", "kind": "debit", "account": "bank",
        "to_account": None, "amount": 48.0, "description": "Auto ride", "category": "Transport",
        "subcategory": "Auto", "note": "PG to office",
    }
    assert call("list_entries") == [entry]


def test_add_expense_from_cash(call, add):
    add(account="cash")
    assert call("list_entries")[0]["account"] == "cash"


def test_add_expense_strips_whitespace(call, add):
    add(product="  Tea ", category=" Food ", subcategory=" Hot ", note=" cup ")
    [row] = call("list_entries")
    assert (row["description"], row["category"], row["subcategory"], row["note"]) == ("Tea", "Food", "Hot", "cup")


def test_add_expense_accepts_numeric_string_amount(call, add):
    add(amount="30")
    assert call("list_entries")[0]["amount"] == 30.0


@pytest.mark.parametrize("date", ["24/09/2026", "2026-02-30", "Sept 1", "2026-09-24T10:00:00", 1790000000])
def test_add_expense_rejects_bad_dates(add, date):
    with pytest.raises(ToolError):
        add(date=date)


@pytest.mark.parametrize("amount", [0, -5, "abc", "inf"])
def test_add_expense_rejects_bad_amounts(add, amount):
    with pytest.raises(ToolError):
        add(amount=amount)


@pytest.mark.parametrize("overrides", [{"product": "   "}, {"category": "   "}, {"account": "wallet"}])
def test_add_expense_rejects_bad_fields(add, overrides):
    with pytest.raises(ToolError):
        add(**overrides)


# add_income and transfer

def test_add_income(call):
    entry = call("add_income", date="2026-09-01", amount=50000, description=" Salary ",
                 category="Salary", note=" Sept ")
    assert (entry["kind"], entry["account"], entry["description"], entry["category"], entry["note"]) == (
        "credit", "bank", "Salary", "Salary", "Sept")


def test_add_income_requires_category(call):
    with pytest.raises(ToolError):
        call("add_income", date="2026-09-01", amount=10, description="Refund")


def test_transfer(call):
    entry = call("transfer", date="2026-09-23", amount=2000, from_account="bank",
                 to_account="cash", description="ATM withdrawal")
    assert (entry["kind"], entry["account"], entry["to_account"], entry["category"], entry["description"]) == (
        "transfer", "bank", "cash", None, "ATM withdrawal")
    assert call("transfer", date="2026-09-23", amount=1, from_account="cash", to_account="bank")["description"] == "Transfer"


def test_transfer_rejects_same_account(call):
    with pytest.raises(ToolError, match="must be different"):
        call("transfer", date="2026-09-23", amount=10, from_account="cash", to_account="cash")


# list_entries

@pytest.fixture
def sample(call, add):
    return [
        add(date="2026-09-01", amount=5, category="Food"),
        call("add_income", date="2026-09-02", amount=1000, description="Salary", category="Salary")["id"],
        add(date="2026-09-15", amount=20, category="Transport", account="cash"),
        call("transfer", date="2026-09-20", amount=200, from_account="bank", to_account="cash")["id"],
        add(date="2026-09-30", amount=7, category="Food"),
        add(date="2026-10-01", amount=100, category="Rent"),
    ]


def test_list_orders_by_date(call, add):
    later = add(date="2026-09-30")
    earlier = add(date="2026-09-01")
    assert ids(call("list_entries")) == [earlier, later]


def test_list_date_range_is_inclusive(call, sample):
    assert ids(call("list_entries", start_date="2026-09-01", end_date="2026-09-30")) == sample[:5]
    assert ids(call("list_entries", start_date="2026-09-30")) == sample[4:]
    assert ids(call("list_entries", end_date="2026-09-02")) == sample[:2]


def test_list_filters(call, sample):
    assert ids(call("list_entries", kind="credit")) == [sample[1]]
    assert ids(call("list_entries", kind="transfer")) == [sample[3]]
    assert ids(call("list_entries", category="Food")) == [sample[0], sample[4]]
    assert ids(call("list_entries", category="Food", limit=1)) == [sample[0]]


def test_list_account_includes_transfers_both_ways(call, sample):
    assert ids(call("list_entries", account="cash")) == [sample[2], sample[3]]
    assert sample[3] in ids(call("list_entries", account="bank"))


def test_list_rejects_reversed_range_and_zero_limit(call):
    with pytest.raises(ToolError, match="after end_date"):
        call("list_entries", start_date="2026-09-30", end_date="2026-09-01")
    with pytest.raises(ToolError):
        call("list_entries", limit=0)


# update_entry

def test_update_changes_only_given_fields(call, add):
    entry_id = add(note="old")
    updated = call("update_entry", entry_id=entry_id, amount=65, note=" extra cheese ", account="cash")
    assert updated == {
        "id": entry_id, "date": "2026-09-23", "kind": "debit", "account": "cash", "to_account": None,
        "amount": 65.0, "description": "Tea", "category": "Food", "subcategory": "", "note": "extra cheese",
    }
    assert call("list_entries") == [updated]


def test_update_can_clear_note(call, add):
    entry_id = add(note="old")
    assert call("update_entry", entry_id=entry_id, note="")["note"] == ""


def test_update_validates_fields(call, add):
    entry_id = add()
    for bad in [{"amount": -1}, {"date": "22/09/2026"}, {"description": " "}, {"account": "wallet"}]:
        with pytest.raises(ToolError):
            call("update_entry", entry_id=entry_id, **bad)
    assert call("list_entries")[0]["amount"] == 10.0


def test_update_transfer_accounts(call):
    t = call("transfer", date="2026-09-23", amount=500, from_account="bank", to_account="cash")
    flipped = call("update_entry", entry_id=t["id"], account="cash", to_account="bank")
    assert (flipped["account"], flipped["to_account"]) == ("cash", "bank")
    with pytest.raises(ToolError, match="must be different"):
        call("update_entry", entry_id=t["id"], to_account="cash")
    with pytest.raises(ToolError, match="no category"):
        call("update_entry", entry_id=t["id"], category="Food")


def test_update_to_account_only_for_transfers(call, add):
    with pytest.raises(ToolError, match="Only transfers"):
        call("update_entry", entry_id=add(), to_account="cash")


def test_update_requires_a_field_and_known_id(call, add):
    with pytest.raises(ToolError, match="No fields"):
        call("update_entry", entry_id=add())
    with pytest.raises(ToolError, match="No entry with id 999"):
        call("update_entry", entry_id=999, amount=1)


# delete_entry

def test_delete_returns_and_removes_entry(call, add):
    keep, gone = add(product="Keep"), add(product="Gone")
    result = call("delete_entry", entry_id=gone)
    assert result["status"] == "deleted"
    assert result["entry"]["description"] == "Gone"
    assert ids(call("list_entries")) == [keep]
    with pytest.raises(ToolError, match=f"No entry with id {gone}"):
        call("delete_entry", entry_id=gone)


# summarize

def test_summarize_spending_excludes_income_and_transfers(call, sample):
    assert call("summarize", start_date="2026-09-01", end_date="2026-09-30") == [
        {"category": "Food", "total_amount": 12.0},
        {"category": "Transport", "total_amount": 20.0},
    ]


def test_summarize_filters(call, sample):
    assert call("summarize", start_date="2026-09-01", end_date="2026-12-31", category="Rent") == [
        {"category": "Rent", "total_amount": 100.0},
    ]
    assert call("summarize", start_date="2026-09-01", end_date="2026-09-30", account="cash") == [
        {"category": "Transport", "total_amount": 20.0},
    ]


def test_summarize_income(call, sample):
    assert call("summarize", start_date="2026-09-01", end_date="2026-09-30", kind="credit") == [
        {"category": "Salary", "total_amount": 1000.0},
    ]


def test_summarize_empty_and_reversed_ranges(call, sample):
    assert call("summarize", start_date="2025-01-01", end_date="2025-12-31") == []
    with pytest.raises(ToolError, match="after end_date"):
        call("summarize", start_date="2026-09-30", end_date="2026-09-01")
