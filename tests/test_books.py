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


def test_the_live_client_asks_paypal_to_refund_the_capture_and_can_read_it():
    seen = []
    pp = PayPalDisputes("id", "secret")
    pp._call = lambda method, path, payload=None: seen.append((method, path, payload)) or {"id": "R1", "status": "COMPLETED"}
    assert pp.refund_capture("2BU27307GH548541C", "20.00", "EUR", "Sorry: your refund.")["id"] == "R1"
    assert seen[0] == ("POST", "/v2/payments/captures/2BU27307GH548541C/refund",
                       {"amount": {"value": "20.00", "currency_code": "EUR"}, "note_to_payer": "Sorry: your refund."})
    pp.get_capture("2BU27307GH548541C")
    assert seen[1] == ("GET", "/v2/payments/captures/2BU27307GH548541C", None)


@contextmanager
def morning():
    """The demo shop's real data; its case file, assignments, reviews and logs in a temporary folder; no AI key;
    notifications dropped. The real Claude judge and the real AI sort fail the test if they are called."""
    tmp = Path(tempfile.mkdtemp())
    kept = (web.CASE_FILES, web.OUTBOX_LOGS, web.REVIEWS, web.SUGGESTED, web.assignments_for, web.has_ai_key, web.notify,
            sort_mod.read_with_ai, judge.INQUIRY_BACKENDS["claude"], judge.BACKENDS["claude"], demo_mod.ACTION_LOG)
    store = team_mod.Assignments(tmp / "assignments.json", seed=DemoPayPal().raw.get("assignments"))

    def no_paid_call(*a):
        raise AssertionError("no paid AI call may run in this test")
    try:
        web.CASE_FILES = {"demo": tmp / "cases-demo.json", "live": tmp / "cases-live.json"}
        web.OUTBOX_LOGS = {"demo": tmp / "actions-demo.jsonl", "live": tmp / "actions-live.jsonl"}
        web.REVIEWS, web.SUGGESTED = tmp / "reviews", tmp / "suggested.json"
        demo_mod.ACTION_LOG = tmp / "demo-paypal-actions.jsonl"
        web.assignments_for = lambda did: store
        web.has_ai_key = lambda: False
        web.notify = lambda event, payload: None
        sort_mod.read_with_ai = judge.INQUIRY_BACKENDS["claude"] = judge.BACKENDS["claude"] = no_paid_call
        yield tmp
    finally:
        (web.CASE_FILES, web.OUTBOX_LOGS, web.REVIEWS, web.SUGGESTED, web.assignments_for, web.has_ai_key, web.notify,
         sort_mod.read_with_ai, judge.INQUIRY_BACKENDS["claude"], judge.BACKENDS["claude"], demo_mod.ACTION_LOG) = kept


def _ask(email, text, sid):
    return web.receive("demo", {"channel": "email", "from": {"name": "", "email": email}, "text": text, "source_id": sid})


def _refunded_paypal_order(sid="b1:1"):
    """Sami returned an Art print bought through PayPal (DEMOTX00001, 20 EUR): the rules refund it, Giulia approves."""
    _, o = _ask("sami.l918@example.com", "Order DEMOTX00001: I returned it and still have no refund.", sid)
    web.run_review(o["case_id"])
    code, text = web.approve(o["case_id"], "REFUND", "Your refund is on its way.", by="giulia")
    assert code == 200, text
    return o["case_id"]


def test_a_paypal_paid_order_is_refunded_through_paypal_s_refund_api_and_a_card_order_is_only_logged():
    with morning() as tmp:
        cid = _refunded_paypal_order()
        [m] = web.case_store("demo").get(cid)["money"]
        assert (m["via"], m["status"], m["refund_id"]) == ("PayPal refund API", "sent to PayPal", "MOCK-REFUND-DEMOTX00001")
        log = [json.loads(x) for x in (tmp / "demo-paypal-actions.jsonl").read_text().splitlines()]
        assert [(x["action"], x["payload"]["capture_id"], x["payload"]["amount"], x["payload"]["currency"]) for x in log] == [
            ("capture-refund", "DEMOTX00001", "20.00", "EUR")]               # the demo's PayPal logs it, never sends it
        web.run_review("DEMO-C001")
        web.approve("DEMO-C001", "MESSAGE", "Left with your neighbour.", by="marta")
        assert len((tmp / "demo-paypal-actions.jsonl").read_text().splitlines()) == 1   # a reply moves no money


def test_a_refund_marked_cancelled_lifts_the_hold_and_one_marked_paid_keeps_it():
    with morning():
        cid = _refunded_paypal_order("b2:1")
        assert web.reconcile(cid, 0, "paid", None, "marta")[0] == 400           # paid how?
        assert web.reconcile(cid, 5, "paid", "card", "marta")[0] == 400         # no such refund
        assert web.reconcile(cid, 0, "lost", "card", "marta")[0] == 400
        assert web.reconcile(cid, 0, "cancelled", None, None)[0] == 400         # nobody named
        assert web.reconcile(cid, 0, "cancelled", None, "marta") == (
            200, "Marked cancelled: it no longer counts as money that went back.")
        assert web.reconcile(cid, 0, "paid", "paypal", "marta")[0] == 409       # once: the books were told
        c = web.case_store("demo").get(cid)
        assert c["money"][0]["status"] == "cancelled" and c["timeline"][-1]["text"].startswith("Refund of 20.00 marked cancelled")
        _ask("sami.l918@example.com", "Still no refund?", "b2:2")
        assert "already_refunded" not in web.run_review(cid).stops                # the cancelled refund counts nowhere
        assert web.case_view(cid)["costs"]["money_moved"] == 0
    with morning():
        cid = _refunded_paypal_order("b3:1")
        assert web.reconcile(cid, 0, "paid", "paypal", "giulia")[0] == 200
        _ask("sami.l918@example.com", "Did it go out?", "b3:2")
        assert "already_refunded" in web.run_review(cid).stops                    # paid: it went back, once
        assert web.case_view(cid)["costs"]["money_moved"] == 20.0


def test_a_paid_refund_lets_a_later_paypal_dispute_be_defended_with_it_as_proof():
    with morning():
        cid = _refunded_paypal_order("b7:1")
        later = {"dispute": {"dispute_id": "DEMO-990", "dispute_amount": {"value": "20.00", "currency_code": "EUR"},
                             "disputed_transactions": [{"seller_transaction_id": "DEMOTX00001"}]},
                 "seller_records": {"sources": {}}}                      # Sami opens a PayPal dispute on that order
        r = web._with_case_refund("DEMO-990", later)["seller_records"]
        assert r["refund_logged_on_case"] == cid and not r.get("refund_paid")      # logged: not proof yet
        web.reconcile(cid, 0, "paid", "paypal", "giulia")
        r = web._with_case_refund("DEMO-990", later)["seller_records"]
        assert r["refund_paid"] and r["sources"]["refund_paid"] == "Your case record"
    refunded = {"refund_logged_on_case": "C1", "already_refunded": "20.00 EUR", "refunded_so_far": 20.0}
    d = {"dispute_id": "D1", "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "dispute_life_cycle_stage": "INQUIRY",
         "dispute_amount": {"value": "20.00", "currency_code": "EUR"}, "messages": []}
    held = apply_policy(Judgment("DEFEND", 0.9, "x"), POLICY, d, refunded)
    assert held.action == "ASK_SELLER" and "refund_logged_on_case" in held.stops            # only logged: a person checks
    paid = {**refunded, "refund_paid": True}
    assert apply_policy(Judgment("DEFEND", 0.9, "x"), POLICY, d, paid).stops == []          # paid: the refund is the proof
    assert "refund_logged_on_case" in apply_policy(Judgment("REFUND", 0.9, "x"), POLICY, d, paid).stops   # never twice
    import secondlook.__main__ as cli
    from secondlook.guard import Decision
    log = Path(tempfile.mkdtemp()) / "a.jsonl"
    pp = MockPayPal(Path(tempfile.mkdtemp()), log)
    cli.execute(pp, Decision("DEFEND", [], Judgment("DEFEND", 0.9, "We refunded you on 19 Oct."), False, []),
                {**d, "status": "WAITING_FOR_SELLER_RESPONSE"}, paid)
    assert json.loads(log.read_text().splitlines()[0])["payload"]["evidence_type"] == "PROOF_OF_REFUND"


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
