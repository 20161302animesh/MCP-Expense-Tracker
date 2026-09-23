from datetime import date

import pytest
from fastmcp.exceptions import ToolError


def balances(result):
    return {b["account"]: b["balance"] for b in result["accounts"]}


def test_no_entries_means_zero_balances(call):
    result = call("get_balance", as_of="2026-09-30")
    assert balances(result) == {"bank": 0.0, "cash": 0.0}
    assert result["total"] == 0.0


def test_get_balance_defaults_to_today(call):
    assert call("get_balance")["as_of"] == date.today().isoformat()


def test_expenses_income_and_transfers_move_the_right_accounts(call, add):
    call("add_income", date="2026-09-01", amount=1000, description="Salary", category="Salary")
    add(date="2026-09-02", amount=100, account="bank")
    call("transfer", date="2026-09-03", amount=300, from_account="bank", to_account="cash")
    add(date="2026-09-04", amount=60, account="cash")
    result = call("get_balance", as_of="2026-09-30")
    assert balances(result) == {"bank": 600.0, "cash": 240.0}
    # A transfer moves money between accounts without changing the total.
    assert result["total"] == 840.0


def test_balance_counts_from_latest_snapshot_per_account(call, add):
    add(date="2026-09-29", amount=100, account="bank")   # before the snapshot: already in it
    add(date="2026-09-30", amount=60, account="bank")    # same day as the snapshot: already in it
    call("record_balance", account="bank", date="2026-09-30", balance=5000)
    call("record_balance", account="cash", date="2026-09-30", balance=800)
    add(date="2026-10-01", amount=40.25, account="bank")
    call("transfer", date="2026-10-02", amount=500, from_account="bank", to_account="cash",
         description="ATM withdrawal")
    add(date="2026-10-03", amount=120, account="cash")
    call("add_income", date="2026-10-04", amount=250, description="Refund", category="Refund")
    add(date="2026-11-01", amount=999, account="cash")   # after as_of: excluded

    result = call("get_balance", as_of="2026-10-31")
    assert result == {
        "as_of": "2026-10-31",
        "accounts": [
            {"account": "bank", "balance": 4709.75, "snapshot_date": "2026-09-30", "snapshot_balance": 5000.0,
             "money_in_since_snapshot": 250.0, "money_out_since_snapshot": 540.25},
            {"account": "cash", "balance": 1180.0, "snapshot_date": "2026-09-30", "snapshot_balance": 800.0,
             "money_in_since_snapshot": 500.0, "money_out_since_snapshot": 120.0},
        ],
        "total": 5889.75,
    }
    # Before the first snapshot there is no anchor, so it is the net of entries from 0.
    assert balances(call("get_balance", as_of="2026-09-29")) == {"bank": -100.0, "cash": 0.0}


def test_get_balance_for_one_account(call, add):
    add(amount=25, account="cash")
    result = call("get_balance", as_of="2026-09-30", account="cash")
    assert [b["account"] for b in result["accounts"]] == ["cash"]
    assert result["total"] == -25.0


def test_record_balance_reports_difference(call, add):
    first = call("record_balance", account="cash", date="2026-09-30", balance=1000)
    assert first["expected_balance"] is None and first["difference"] is None

    add(date="2026-10-01", amount=200, account="cash")
    second = call("record_balance", account="cash", date="2026-10-05", balance=700, note="counted")
    assert second == {"status": "ok", "account": "cash", "date": "2026-10-05", "balance": 700.0,
                      "expected_balance": 800.0, "difference": -100.0}


def test_snapshots_are_independent_per_account(call):
    call("record_balance", account="bank", date="2026-09-30", balance=5000)
    # A bank snapshot doesn't anchor cash.
    assert call("record_balance", account="cash", date="2026-10-01", balance=300)["expected_balance"] is None
    call("record_balance", account="cash", date="2026-09-30", balance=250)
    assert [(s["account"], s["date"]) for s in call("list_balance_snapshots")] == [
        ("bank", "2026-09-30"), ("cash", "2026-09-30"), ("cash", "2026-10-01"),
    ]


def test_record_balance_replaces_same_account_and_date(call):
    call("record_balance", account="bank", date="2026-09-01", balance=5000)
    call("record_balance", account="bank", date="2026-09-05", balance=4000)
    again = call("record_balance", account="bank", date="2026-09-05", balance=4100)
    # Expected comes from the 09-01 snapshot, not the one being replaced.
    assert again["expected_balance"] == 5000.0
    assert [(s["date"], s["balance"]) for s in call("list_balance_snapshots", account="bank")] == [
        ("2026-09-01", 5000.0), ("2026-09-05", 4100.0),
    ]


def test_record_balance_validation(call):
    assert call("record_balance", account="bank", date="2026-09-01", balance=-250)["balance"] == -250.0
    with pytest.raises(ToolError):
        call("record_balance", account="bank", date="2026-09-02", balance="inf")
    with pytest.raises(ToolError):
        call("record_balance", account="wallet", date="2026-09-02", balance=1)
    with pytest.raises(ToolError):
        call("record_balance", date="2026-09-02", balance=1)   # account is required


def test_list_and_delete_snapshots(call):
    for account, day, bal in [("bank", "2026-08-31", 1), ("bank", "2026-09-15", 2),
                              ("cash", "2026-09-15", 3), ("bank", "2026-09-30", 4)]:
        call("record_balance", account=account, date=day, balance=bal)
    assert [s["balance"] for s in call("list_balance_snapshots", start_date="2026-09-01")] == [2.0, 3.0, 4.0]
    assert [s["balance"] for s in call("list_balance_snapshots", account="cash")] == [3.0]

    deleted = call("delete_balance_snapshot", account="bank", date="2026-09-15")
    assert deleted["snapshot"]["balance"] == 2.0
    assert [s["balance"] for s in call("list_balance_snapshots")] == [1.0, 3.0, 4.0]
    with pytest.raises(ToolError, match="No bank balance snapshot"):
        call("delete_balance_snapshot", account="bank", date="2026-09-15")
