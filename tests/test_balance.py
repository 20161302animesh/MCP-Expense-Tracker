import sqlite3
from datetime import date

import pytest
from fastmcp.exceptions import ToolError

from mcp_expense_tracker import server


# Expenses keep a linked debit in sync

def test_add_expense_creates_debit(call, add):
    expense_id = add(date="2026-09-23", amount=48, product="Auto ride")
    [debit] = call("list_transactions")
    assert debit == {
        "id": debit["id"], "date": "2026-09-23", "kind": "debit", "amount": 48.0,
        "description": "Auto ride", "note": "", "expense_id": expense_id,
    }


def test_update_expense_updates_debit(call, add):
    expense_id = add(amount=48, product="Auto ride")
    call("update_expense", expense_id=expense_id, amount=55, date="2026-09-24", product="Cab")
    [debit] = call("list_transactions")
    assert (debit["date"], debit["amount"], debit["description"]) == ("2026-09-24", 55.0, "Cab")


def test_update_expense_category_only_keeps_debit(call, add):
    expense_id = add(amount=48)
    call("update_expense", expense_id=expense_id, category="Travel")
    [debit] = call("list_transactions")
    assert debit["amount"] == 48.0 and debit["expense_id"] == expense_id


def test_delete_expense_removes_debit(call, add):
    keep, gone = add(product="Keep"), add(product="Gone")
    call("delete_expense", expense_id=gone)
    assert [t["expense_id"] for t in call("list_transactions")] == [keep]


def test_init_db_backfills_debits_for_existing_expenses(call):
    with sqlite3.connect(server.DB_PATH) as c:
        c.execute("DROP TABLE transactions")
        c.execute("INSERT INTO expenses(date, amount, product, category) VALUES ('2026-09-01', 12, 'Old', 'Food')")
    server.init_db()
    server.init_db()  # running again must not duplicate the debit
    [debit] = call("list_transactions")
    assert (debit["kind"], debit["amount"], debit["description"], debit["expense_id"]) == ("debit", 12.0, "Old", 1)


# Manual transactions

def test_add_and_list_transactions(call, add):
    add(date="2026-09-10", amount=100)
    salary = call("add_transaction", date="2026-09-01", kind="credit", amount=50000,
                  description=" Salary ", note=" Sept ")
    assert salary == {"id": salary["id"], "date": "2026-09-01", "kind": "credit", "amount": 50000.0,
                      "description": "Salary", "note": "Sept", "expense_id": None}
    # Ordered by date, not id.
    assert [t["description"] for t in call("list_transactions")] == ["Salary", "Tea"]
    assert [t["kind"] for t in call("list_transactions", kind="debit")] == ["debit"]
    assert call("list_transactions", start_date="2026-09-05", end_date="2026-09-30", kind="credit") == []


@pytest.mark.parametrize("args", [
    {"kind": "refund"}, {"amount": 0}, {"amount": -1}, {"description": "  "}, {"date": "01/09/2026"},
])
def test_add_transaction_validates(call, args):
    base = {"date": "2026-09-01", "kind": "credit", "amount": 10, "description": "Salary"}
    with pytest.raises(ToolError):
        call("add_transaction", **{**base, **args})


def test_update_and_delete_manual_transaction(call):
    t = call("add_transaction", date="2026-09-01", kind="credit", amount=10, description="Refund")
    updated = call("update_transaction", transaction_id=t["id"], kind="debit", amount=15)
    assert (updated["kind"], updated["amount"], updated["description"]) == ("debit", 15.0, "Refund")
    assert call("delete_transaction", transaction_id=t["id"])["transaction"] == updated
    assert call("list_transactions") == []


def test_expense_debits_cannot_be_edited_directly(call, add):
    add()
    [debit] = call("list_transactions")
    with pytest.raises(ToolError, match="update_expense or delete_expense"):
        call("update_transaction", transaction_id=debit["id"], amount=1)
    with pytest.raises(ToolError, match="update_expense or delete_expense"):
        call("delete_transaction", transaction_id=debit["id"])
    assert call("list_transactions") == [debit]


def test_transaction_unknown_id_and_empty_update(call):
    with pytest.raises(ToolError, match="No transaction with id 5"):
        call("delete_transaction", transaction_id=5)
    t = call("add_transaction", date="2026-09-01", kind="credit", amount=10, description="Refund")
    with pytest.raises(ToolError, match="No fields"):
        call("update_transaction", transaction_id=t["id"])


# Balance

def test_balance_without_snapshot_is_net_of_transactions(call, add):
    call("add_transaction", date="2026-09-01", kind="credit", amount=1000, description="Salary")
    add(date="2026-09-05", amount=100)
    balance = call("get_balance", as_of="2026-09-30")
    assert balance["balance"] == 900.0
    assert balance["snapshot_date"] is None
    assert call("get_balance", as_of="2026-09-02")["balance"] == 1000.0


def test_balance_counts_from_latest_snapshot(call, add):
    add(date="2026-09-05", amount=100)   # before the snapshot: already reflected in it
    add(date="2026-09-10", amount=60)    # same day as the snapshot: already reflected in it
    call("record_balance", date="2026-09-10", balance=5000)
    add(date="2026-09-11", amount=40.25)
    call("add_transaction", date="2026-09-12", kind="credit", amount=500, description="Refund")
    add(date="2026-10-01", amount=999)   # after as_of: excluded

    assert call("get_balance", as_of="2026-09-30") == {
        "as_of": "2026-09-30", "balance": 5459.75,
        "snapshot_date": "2026-09-10", "snapshot_balance": 5000.0,
        "credits_since_snapshot": 500.0, "debits_since_snapshot": 40.25,
    }
    # Before the first snapshot there is no anchor, so it is the net of transactions.
    assert call("get_balance", as_of="2026-09-09")["balance"] == -100.0


def test_get_balance_defaults_to_today(call):
    assert call("get_balance")["as_of"] == date.today().isoformat()


def test_record_balance_reports_difference(call, add):
    first = call("record_balance", date="2026-09-01", balance=5000)
    assert first["expected_balance"] is None and first["difference"] is None

    add(date="2026-09-03", amount=200)
    second = call("record_balance", date="2026-09-05", balance=4700, note="from Axis app")
    assert second == {"status": "ok", "date": "2026-09-05", "balance": 4700.0,
                      "expected_balance": 4800.0, "difference": -100.0}


def test_record_balance_replaces_same_date(call):
    call("record_balance", date="2026-09-01", balance=5000)
    call("record_balance", date="2026-09-05", balance=4000)
    again = call("record_balance", date="2026-09-05", balance=4100)
    # Expected comes from the 09-01 snapshot, not the one being replaced.
    assert again["expected_balance"] == 5000.0
    assert [(s["date"], s["balance"]) for s in call("list_balance_snapshots")] == [
        ("2026-09-01", 5000.0), ("2026-09-05", 4100.0),
    ]


def test_record_balance_allows_negative_but_not_infinite(call):
    assert call("record_balance", date="2026-09-01", balance=-250)["balance"] == -250.0
    with pytest.raises(ToolError):
        call("record_balance", date="2026-09-02", balance="inf")


def test_list_and_delete_snapshots(call):
    for day, bal in [("2026-08-31", 1), ("2026-09-15", 2), ("2026-09-30", 3)]:
        call("record_balance", date=day, balance=bal)
    assert [s["date"] for s in call("list_balance_snapshots", start_date="2026-09-01")] == ["2026-09-15", "2026-09-30"]
    assert call("delete_balance_snapshot", date="2026-09-15")["snapshot"]["balance"] == 2.0
    assert [s["date"] for s in call("list_balance_snapshots")] == ["2026-08-31", "2026-09-30"]
    with pytest.raises(ToolError, match="No balance snapshot"):
        call("delete_balance_snapshot", date="2026-09-15")
