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
    pp._call = lambda method, path, payload=None, headers=None: seen.append((method, path, payload)) or {"id": "R1", "status": "COMPLETED"}
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


def test_a_refund_through_paypal_is_never_cancelled_and_one_marked_paid_keeps_the_hold():
    with morning():
        cid = _refunded_paypal_order("b2:1")
        assert web.reconcile(cid, 0, "paid", None, "marta")[0] == 400           # paid how?
        assert web.reconcile(cid, 5, "paid", "card", "marta")[0] == 400         # no such refund
        assert web.reconcile(cid, 0, "lost", "card", "marta")[0] == 400
        assert web.reconcile(cid, 0, "cancelled", None, None)[0] == 400         # nobody named
        code, text = web.reconcile(cid, 0, "cancelled", None, "giulia")
        assert code == 409 and "went through PayPal" in text                      # PayPal made it: never "cancelled"
        assert web.reconcile(cid, 0, "paid", "paypal", "marta")[0] == 200
        assert web.reconcile(cid, 0, "paid", "paypal", "marta")[0] == 409       # once: the books were told
        c = web.case_store("demo").get(cid)
        assert c["money"][0]["status"] == "paid" and c["timeline"][-1]["text"].startswith("Refund of 20.00 marked paid")
        _ask("sami.l918@example.com", "Still no refund?", "b2:2")
        assert "already_refunded" in web.run_review(cid).stops                    # it went back: never a second one
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


# ---------- quality review 9 (26/10): the money path ----------

def _card_refund(amount="40.00 EUR"):
    """Sophie paid by card (LP-90001, 64 EUR): a partial refund, approved by Giulia, logged for the payment provider."""
    web.has_ai_key = lambda: True
    judge.INQUIRY_BACKENDS["claude"] = lambda case: Judgment("PARTIAL_REFUND", 0.9, "Faked.", draft_message="Part back.",
                                                            partial_amount=amount)
    web.run_review("DEMO-C001")
    code, text = web.approve("DEMO-C001", "PARTIAL_REFUND", "Part back.", by="giulia")
    assert code == 200, text
    return "DEMO-C001"


def test_a_card_refund_is_cancelled_only_by_someone_whose_limit_covers_it():
    with morning():
        cid = _card_refund("40.00 EUR")
        assert web.case_store("demo").get(cid)["money"][0]["via"] == "for your payment provider (not connected)"
        code, text = web.reconcile(cid, 0, "cancelled", None, "marta")       # 40 EUR, over Marta's 30
        assert code == 403 and "limit" in text
        assert web.reconcile(cid, 0, "cancelled", None, "giulia") == (
            200, "Marked cancelled: it no longer counts as money that went back.")
        assert web.case_view(cid)["costs"]["money_moved"] == 0                 # it counts nowhere: the hold lifts


def test_a_refund_through_paypal_carries_one_request_id_and_a_failure_records_nothing():
    calls_ = []

    class Flaky:
        def __init__(self, fail):
            self.fail = fail

        def get_capture(self, capture_id):
            return {"id": capture_id, "status": "COMPLETED", "amount": {"value": "20.00", "currency_code": "EUR"}}

        def refund_capture(self, capture_id, amount, currency, note, request_id=None):
            calls_.append((capture_id, amount, currency, request_id))
            if self.fail:
                raise RuntimeError("PayPal 500 on POST /v2/payments/captures/X/refund: timeout")
            return {"id": "R-OK", "status": "COMPLETED"}
    with morning():
        _, o = _ask("sami.l918@example.com", "Order DEMOTX00001: I returned it and still have no refund.", "b9:1")
        cid = o["case_id"]
        web.run_review(cid)
        real = web.paypal_for
        try:
            web.paypal_for = lambda src: Flaky(True)
            code, text = web.approve(cid, "REFUND", "Your refund is on its way.", by="giulia")
            assert code == 502 and text.startswith("PayPal didn't confirm the refund")
            c = web.case_store("demo").get(cid)
            assert c["money"] == [] and not any(x["direction"] == "out" for x in c["timeline"])
            assert web._saved(cid)[1] is None                                     # not marked sent
            web.paypal_for = lambda src: Flaky(False)
            assert web.approve(cid, "REFUND", "Your refund is on its way.", by="giulia")[0] == 200
        finally:
            web.paypal_for = real
    assert len(calls_) == 2 and calls_[0][3] and calls_[0][3] == calls_[1][3]       # the retry: the same request id
    seen = []
    pp = PayPalDisputes("id", "secret")
    pp._call = lambda method, path, payload=None, headers=None: seen.append(headers) or {"id": "R1"}
    pp.refund_capture("CAP1", "1.00", "EUR", "x", request_id="sl-abc")
    assert seen == [{"PayPal-Request-Id": "sl-abc"}]


def test_a_live_capture_is_read_first_its_currency_used_and_its_refund_capped():
    sent = []

    class Live:
        def __init__(self, status, value="15.00", cur="USD"):
            self.capture = {"id": "DEMOTX00001", "status": status, "amount": {"value": value, "currency_code": cur}}

        def get_capture(self, capture_id):
            return self.capture

        def refund_capture(self, capture_id, amount, currency, note, request_id=None):
            sent.append((amount, currency))
            return {"id": "R-LIVE"}
    for status, want in (("COMPLETED", 200), ("PENDING", 409)):
        with morning():
            _, o = _ask("sami.l918@example.com", "Order DEMOTX00001: I returned it and still have no refund.", f"b9:{status}")
            web.run_review(o["case_id"])
            real = web.paypal_for
            web.paypal_for = lambda src, s=status: Live(s)
            try:
                code, text = web.approve(o["case_id"], "REFUND", "Your refund is on its way.", by="giulia")
            finally:
                web.paypal_for = real
            assert code == want, (status, text)
            if want == 409:
                assert "PayPal shows this payment as PENDING" in text and web.case_store("demo").get(o["case_id"])["money"] == []
    assert sent == [("15.00", "USD")]                    # PayPal's own currency, and no more than the capture left


def test_a_paid_refund_is_proof_only_when_it_covers_the_dispute_and_marking_it_puts_the_review_out_of_date():
    with morning():
        cid = _card_refund("5.00 EUR")
        web.case_store("demo").update(cid, lambda c: c.update(order_no="DEMOTX00001"))   # as if Sophie had paid by PayPal
        big = {"dispute": {"dispute_id": "DEMO-990", "dispute_amount": {"value": "89.00", "currency_code": "EUR"},
                           "disputed_transactions": [{"seller_transaction_id": "DEMOTX00001"}]},
               "seller_records": {"sources": {}}}
        web.reconcile(cid, 0, "paid", "card", "giulia")
        assert not web._with_case_refund("DEMO-990", big)["seller_records"].get("refund_paid")   # 5 of 89: no proof
        small = {**big, "dispute": {**big["dispute"], "dispute_amount": {"value": "5.00", "currency_code": "EUR"}}}
        assert web._with_case_refund("DEMO-990", small)["seller_records"]["refund_paid"]
    with morning():
        cid = _card_refund("20.00 EUR")
        r = {"refund_logged_on_case": cid, "refunded_so_far": 20.0}
        before = web._seen({"dispute": {"messages": [], "dispute_amount": {"value": "20.00"}}, "seller_records": r})
        after = web._seen({"dispute": {"messages": [], "dispute_amount": {"value": "20.00"}},
                           "seller_records": {**r, "refund_paid": True}})
        assert before != after and before["case_refund_paid"] is False and after["case_refund_paid"] is True
        assert "case_refund_paid" not in web._seen({"dispute": {"messages": [], "dispute_amount": {"value": "1"}},
                                                    "seller_records": {}})     # no case money: what it saw, unchanged


def test_a_card_order_s_refund_is_logged_for_the_payment_provider_and_never_sent_to_paypal():
    with morning() as tmp:
        web.has_ai_key = lambda: True
        judge.INQUIRY_BACKENDS["claude"] = lambda case: Judgment("REFUND", 0.95, "Faked.", draft_message="A full refund.")
        dec = web.run_review("DEMO-C001")                                     # 64 EUR: held for the cap only
        assert dec.stops == ["cap"]
        code, text = web.approve("DEMO-C001", "REFUND", "A full refund.", by="giulia")   # the head of customer care
        assert code == 200 and text.startswith("Refund of 64.00 EUR logged and reply sent by email.")
        [m] = web.case_store("demo").get("DEMO-C001")["money"]
        assert (m["kind"], m["amount"], m["via"]) == ("refund", 64.0, "for your payment provider (not connected)")
        assert "refund_id" not in m and "status" not in m
        log = tmp / "demo-paypal-actions.jsonl"
        assert not log.exists() or "capture-refund" not in log.read_text()   # nothing went to PayPal
        assert web.reconcile("DEMO-C001", 0, "cancelled", None, "marta")[0] == 403      # over Marta's 30 EUR
        assert web.reconcile("DEMO-C001", 0, "cancelled", None, "giulia")[0] == 200
        assert web.case_view("DEMO-C001")["costs"]["money_moved"] == 0      # cancelled: the hold lifts


# ---------- re-review (26/10): a refund PayPal didn't confirm is held until a person says what happened ----------

class _PayPal:
    """A fake live PayPal: one capture of 20 EUR, refunds that fail or go through, and what it says it refunded."""
    def __init__(self, fail=False, status="COMPLETED", total="20.00", refunded=None, order_refunds=None, cur="EUR"):
        self.fail, self.sent = fail, []
        self.capture = {"id": "DEMOTX00001", "status": status, "amount": {"value": total, "currency_code": cur},
                        "links": [{"rel": "up", "method": "GET", "href": "https://api.example/v2/checkout/orders/O1"}]}
        if refunded is not None:
            self.capture["seller_receivable_breakdown"] = {"total_refunded_amount": {"value": refunded, "currency_code": cur}}
        self.order = {"purchase_units": [{"payments": {"refunds": order_refunds or []}}]}

    def get_capture(self, capture_id):
        return self.capture

    def get_link(self, href):
        return self.order if href.endswith("/orders/O1") else {}

    def refund_capture(self, capture_id, amount, currency, note, request_id=None):
        self.sent.append((amount, currency, request_id))
        if self.fail:
            raise RuntimeError("PayPal 500: timeout")
        return {"id": f"R{len(self.sent)}", "status": "COMPLETED"}


def _sami_refund(sid):
    _, o = _ask("sami.l918@example.com", "Order DEMOTX00001: I returned it and still have no refund.", sid)
    web.run_review(o["case_id"])
    return o["case_id"]


def test_a_refund_paypal_didn_t_confirm_is_held_until_a_person_says_what_happened():
    with morning():
        cid = _sami_refund("u1:1")
        real = web.paypal_for
        pp = _PayPal(fail=True)
        web.paypal_for = lambda src: pp
        try:
            assert web.approve(cid, "REFUND", "Your refund is on its way.", by="giulia")[0] == 502
            [mark] = web.case_store("demo").get(cid)["unconfirmed"]
            assert (mark["amount"], mark["currency"], mark["by"], mark["request_id"]) == (20.0, "EUR", "Giulia", pp.sent[0][2])
            assert web.case_store("demo").get(cid)["money"] == []                       # not money moved
            page = web.case_file_page(cid, me="giulia")
            assert "A refund of 20.00 EUR wasn't confirmed by PayPal on " in page and "check the payment in PayPal" in page
            _ask("sami.l918@example.com", "Hello?", "u1:2")
            dec = web.run_review(cid)                                                    # a fresh look: held
            assert dec.action == "ASK_SELLER" and "refund_unconfirmed" in dec.stops
            assert web.approve(cid, "REFUND", "Refund.", by="giulia")[0] == 409
            web.case_store("demo").update(cid, lambda c: c["unconfirmed"][0].update(amount=40.0))
            assert web.resolve_unconfirmed(cid, mark["request_id"], True, "marta")[0] == 403   # 40 EUR: over Marta's limit
            web.case_store("demo").update(cid, lambda c: c["unconfirmed"][0].update(amount=20.0))
            assert web.resolve_unconfirmed(cid, mark["request_id"], True, "giulia") == (
                200, "Recorded: PayPal refunded 20.00 EUR.")
            c = web.case_store("demo").get(cid)
            assert c["unconfirmed"] == [] and [(m["status"], m["paid_with"], m["amount"]) for m in c["money"]] == [
                ("paid", "paypal", 20.0)]
            assert "already_refunded" in web.run_review(cid).stops                          # it went back, once
        finally:
            web.paypal_for = real
    with morning():
        cid = _sami_refund("u1:3")
        real = web.paypal_for
        web.paypal_for = lambda src: _PayPal(fail=True)
        try:
            web.approve(cid, "REFUND", "Your refund is on its way.", by="giulia")
            req = web.case_store("demo").get(cid)["unconfirmed"][0]["request_id"]
            assert web.resolve_unconfirmed(cid, req, False, "giulia") == (200, "Recorded: PayPal did not refund it.")
            assert web.case_store("demo").get(cid)["unconfirmed"] == []
        finally:
            web.paypal_for = real


def test_a_retry_of_the_same_review_keeps_its_request_id_and_clears_the_mark():
    with morning():
        cid = _sami_refund("u1:4")
        real = web.paypal_for
        pp = _PayPal(fail=True)
        web.paypal_for = lambda src: pp
        try:
            assert web.approve(cid, "REFUND", "Your refund is on its way.", by="giulia")[0] == 502
            pp.fail = False
            assert web.approve(cid, "REFUND", "Your refund is on its way.", by="giulia")[0] == 200
        finally:
            web.paypal_for = real
        c = web.case_store("demo").get(cid)
        assert pp.sent[0][2] == pp.sent[1][2] and c["unconfirmed"] == [] and len(c["money"]) == 1


def test_a_paypal_dispute_on_the_order_is_held_while_a_refund_is_unconfirmed():
    clara = next(o for o in DemoPayPal().orders() if o["transaction_id"] == "DEMOTX01969")
    with morning():
        real_d, real_p = web.shop_disputes, web.paypal_for
        web.shop_disputes = lambda src: [d for d in real_d(src) if d["dispute_id"] != "DEMO-039"]
        web.has_ai_key = lambda: True
        judge.INQUIRY_BACKENDS["claude"] = lambda case: Judgment("REFUND", 0.95, "Faked.", draft_message="We refund you.")
        web.paypal_for = lambda src: _PayPal(fail=True, total="29.00")
        try:
            _, o = _ask(clara["email"], "My order DEMOTX01969 never arrived.", "u1:5")
            web.run_review(o["case_id"])
            assert web.approve(o["case_id"], "REFUND", "We refund you.", by="giulia")[0] == 502
        finally:
            web.shop_disputes, web.paypal_for = real_d, real_p
        rec = web._case("DEMO-039")["seller_records"]
        assert rec["refund_unconfirmed"].startswith("29.00 EUR")
        d = {"dispute_id": "DEMO-039", "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "dispute_life_cycle_stage": "INQUIRY",
             "dispute_amount": {"value": "29.00", "currency_code": "EUR"}, "messages": []}
        for action in ("DEFEND", "REFUND", "PARTIAL_REFUND", "REPLACE"):
            held = apply_policy(Judgment(action, 0.95, "x", partial_amount="5 EUR"), POLICY, d, rec)
            assert "refund_unconfirmed" in held.stops, action
        assert "wasn't confirmed by PayPal" in web.case_page("DEMO-039", me="giulia")


def test_paypal_s_refunded_total_is_read_or_the_refund_is_refused():
    def approve_with(pp, sid, money=None):
        with morning():
            _, o = _ask("sami.l918@example.com", "Order DEMOTX00001: I returned it and still have no refund.", sid)
            cid = o["case_id"]
            if money:                                   # an earlier PayPal refund Second Look recorded on the order
                web.case_store("demo").update(cid, lambda c: c["money"].append(money))
            web.run_review(cid)
            real = web.paypal_for
            web.paypal_for = lambda src: pp
            try:
                return web.approve(cid, "REFUND", "Your refund is on its way.", by="giulia")
            finally:
                web.paypal_for = real
    # PayPal refunded 5 that Second Look never recorded: nothing is sent
    pp = _PayPal(status="PARTIALLY_REFUNDED", refunded="5.00")
    code, text = approve_with(pp, "u2:1")
    assert code == 409 and "PayPal shows 5.00 EUR refunded that Second Look didn't record" in text and pp.sent == []
    # read through the capture's order (no total on the capture): 5 refunded, 5 recorded, 15 left
    ours = {"kind": "partial_refund", "amount": 5.0, "via": "PayPal refund API", "status": "sent to PayPal",
            "refund_id": "R0", "at": "2026-10-19T10:00", "by": "Giulia"}
    pp = _PayPal(status="PARTIALLY_REFUNDED", order_refunds=[
        {"id": "R0", "status": "COMPLETED", "amount": {"value": "5.00", "currency_code": "EUR"},
         "links": [{"rel": "up", "href": "https://api.example/v2/payments/captures/DEMOTX00001"}]},
        {"id": "RX", "status": "COMPLETED", "amount": {"value": "9.00", "currency_code": "EUR"},
         "links": [{"rel": "up", "href": "https://api.example/v2/payments/captures/ANOTHER"}]}])
    code, text = approve_with(pp, "u3:1", ours)
    assert code == 200 and [a for a, _, _ in pp.sent] == ["15.00"], text   # the other capture's refund isn't this one's
    # partly refunded, and nothing readable says how much: refused, never treated as 0
    pp = _PayPal(status="PARTIALLY_REFUNDED")
    code, text = approve_with(pp, "u3:2")
    assert code == 409 and "couldn't read what PayPal already refunded" in text and pp.sent == []


def test_the_answer_about_an_unconfirmed_refund_comes_only_from_the_shop_s_own_page():
    from urllib.parse import urlencode
    with morning():
        cid = _sami_refund("u1:9")
        real = web.paypal_for
        web.paypal_for = lambda src: _PayPal(fail=True)
        try:
            web.approve(cid, "REFUND", "Your refund is on its way.", by="giulia")
        finally:
            web.paypal_for = real
        req = web.case_store("demo").get(cid)["unconfirmed"][0]["request_id"]
        srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            def post(**headers):
                con = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
                con.request("POST", f"/c/{cid}/unconfirmed", body=urlencode({"by": "giulia", "request_id": req, "refunded": "no"}),
                            headers={"Content-Type": "application/x-www-form-urlencoded", **headers})
                r = con.getresponse()
                r.read()
                return r.status
            assert post(Origin="http://evil.example") == 403 and web.case_store("demo").get(cid)["unconfirmed"]
            assert post(Origin=f"http://127.0.0.1:{srv.server_address[1]}") == 303
            assert web.case_store("demo").get(cid)["unconfirmed"] == []
        finally:
            srv.shutdown()
            srv.server_close()


def test_the_case_page_shows_its_money_and_the_reconcile_form():
    with morning():
        cid = _refunded_paypal_order("b4:1")
        page = web.case_file_page(cid, me="giulia")
        assert "Money on this case" in page and "Refund 20.00 EUR" in page and "sent to PayPal" in page
        assert f'action="/c/{cid}/money"' in page and "Mark paid" in page
        assert "It never went out: cancel" not in page          # through PayPal: only paid (review 26/10)
        web.reconcile(cid, 0, "paid", "paypal", "giulia")
        page = web.case_file_page(cid, me="giulia")
        assert "paid through PayPal" in page and "Mark paid" not in page
    with morning():
        cid = _card_refund("20.00 EUR")                         # a card refund: paid, or it never went out
        assert "It never went out: cancel" in web.case_file_page(cid, me="giulia")


def test_a_refund_is_marked_only_from_the_shop_s_own_page_by_a_named_person():
    from urllib.parse import urlencode
    with morning():
        cid = _refunded_paypal_order("b4:2")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            def post(body, **headers):
                con = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
                con.request("POST", f"/c/{cid}/money", body=urlencode(body),
                            headers={"Content-Type": "application/x-www-form-urlencoded", **headers})
                r = con.getresponse()
                return r.status, r.read().decode()
            here = f"http://127.0.0.1:{srv.server_address[1]}"
            mark = {"by": "marta", "i": "0", "outcome": "paid", "paid_with": "paypal"}
            assert post(mark, Origin="http://evil.example")[0] == 403
            assert post({**mark, "by": "nobody"}, Origin=here)[0] == 400
            code, text = post({**mark, "outcome": "cancelled"}, Origin=here)
            assert code == 409 and "went through PayPal" in text                    # B1, through the form too
            assert post(mark, Origin=here)[0] == 303
            assert web.case_store("demo").get(cid)["money"][0]["status"] == "paid"
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
