"""The books: every money event, live to the shop's bookkeeping and as a monthly CSV; a refund marked paid or
cancelled; a PayPal-paid order refunded through PayPal's refund API (logged in the demo, never sent).
Run: python3 tests/test_books.py"""
import csv
import io
import json
import os
import sys
import tempfile
import threading
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secondlook import books, demo as demo_mod, judge, sort as sort_mod, team as team_mod, web  # noqa: E402
from secondlook.demo import DemoPayPal  # noqa: E402
from secondlook.guard import Judgment, apply_policy  # noqa: E402
from secondlook.paypal import MockPayPal, PayPalDisputes  # noqa: E402
# Tests never run local whisper: a call's words are the transcript shipped beside it (26/10).
web.TRANSCRIBE = lambda wav: None

POLICY = json.loads((Path(__file__).resolve().parent.parent / "policy.json").read_text())


def test_where_the_item_is_and_what_the_books_say_about_one_case():
    assert books.item_state("not_received", {"tracking": {"status": "IN_TRANSIT"}}) == books.LOST
    assert books.item_state("not_received", {"tracking": {"status": "DELIVERED"}}) == books.KEPT
    assert books.item_state("wrong_size", {"return": {"status": "DELIVERED", "delivered_to": "the shop"}}) == books.BACK
    assert books.item_state("refund_missing", None) == books.BACK and books.item_state("question", None) == books.UNKNOWN
    c = {"id": "C1", "order_no": "LP-1", "dispute_id": None, "problem": {"kind": "not_received"},
         "timeline": [{"at": "2026-10-19T08:52", "channel": "form", "direction": "in"},
                      {"at": "2026-10-19T09:30", "channel": "form", "direction": "out", "action": "refund"}],
         "money": [{"kind": "refund", "amount": 64.0, "at": "2026-10-19T09:30", "by": "Giulia"},
                   {"kind": "note"}]}
    [row] = books.case_events(c, {"currency": "EUR", "tracking": None}, "LP-INV-1")
    assert row == {"date": "2026-10-19T09:30", "kind": "refund", "order_no": "LP-1", "invoice_no": "LP-INV-1",
                   "amount": 64.0, "currency": "EUR", "fees": 0.0, "item": books.LOST, "approved_by": "Giulia",
                   "channel": "form", "case_id": "C1", "dispute_id": "", "status": "logged"}
    text = books.csv_text(books.for_month([row, {**row, "date": "2026-09-30T10:00"}], "2026-10"))
    assert text.splitlines()[0] == ",".join(books.COLUMNS) and text.count("\n") == 2 and ",64.00,EUR,0.00," in text


def test_a_resolved_paypal_dispute_books_its_refund_and_its_fee():
    d = {"dispute_id": "D1", "status": "RESOLVED", "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
         "dispute_life_cycle_stage": "CHARGEBACK", "create_time": "2026-10-06T10:00:00Z",
         "dispute_amount": {"value": "40.00", "currency_code": "EUR"},
         "dispute_outcome": {"outcome_code": "RESOLVED_BUYER_FAVOUR", "outcome_reason": "ITEM_NOT_RECEIVED",
                             "amount_refunded": {"value": "40.00", "currency_code": "EUR"}},
         "disputed_transactions": [{"seller_transaction_id": "TX1"}]}
    [row] = books.dispute_events(d, None, "Luca", high_volume=False)
    assert (row["kind"], row["amount"], row["fees"], row["item"], row["approved_by"], row["channel"], row["status"]) == (
        "PayPal refund", 40.0, 14.0, books.LOST, "Luca", "paypal", "Lost at claim")
    assert books.dispute_events({**d, "status": "WAITING_FOR_SELLER_RESPONSE"}, None, None, False) == []


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
