"""Ticketbook shows Second Look from its API and decides nothing itself. Run: python3 tests/test_helpdesk.py"""
import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from helpdesk.secondlook_client import SecondLook, Unavailable  # noqa: E402


def fake_secondlook(routes):
    """A tiny local server answering fixed JSON per (method, path): stands in for Second Look."""
    seen = []

    class H(BaseHTTPRequestHandler):
        def _answer(self, method):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"null") if n else None
            seen.append((method, self.path, body))
            code, data = routes.get((method, self.path.split("?")[0]), (404, {"error": "unknown"}))
            b = json.dumps(data).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

        def do_GET(self):
            self._answer("GET")

        def do_POST(self):
            self._answer("POST")

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}", seen


def test_the_client_reads_and_approves_through_the_api():
    srv, url, seen = fake_secondlook({
        ("GET", "/api/customers/dario.v@example.com"): (200, {"payer_id": "P1", "disputes": [{"dispute_id": "DEMO-031", "outcome": "Open"}]}),
        ("GET", "/api/disputes/DEMO-031"): (200, {"dispute_id": "DEMO-031", "review": {"mark": "abc"}}),
        ("POST", "/api/disputes/DEMO-031/approve"): (202, {"dispute_id": "DEMO-031", "result": "Passed to Giulia: ..."}),
    })
    try:
        sl = SecondLook(url)
        assert sl.customer("dario.v@example.com")["payer_id"] == "P1"
        assert sl.case("DEMO-031", as_person="marta")["review"]["mark"] == "abc"
        assert seen[-1][1] == "/api/disputes/DEMO-031?as=marta"
        code, text = sl.approve("DEMO-031", action="REFUND", message="Hello", by="marta", review="abc")
        assert code == 202 and text.startswith("Passed to Giulia")
        assert seen[-1][2] == {"action": "REFUND", "message": "Hello", "by": "marta", "review": "abc"}
        assert sl.customer("nobody@example.com") is None          # 404 = unknown customer, not an error
    finally:
        srv.shutdown()


def test_a_server_error_from_second_look_counts_as_not_answering():
    srv, url, _ = fake_secondlook({("GET", "/api/customers/x@example.com"): (500, {"error": "boom"})})
    try:
        SecondLook(url).customer("x@example.com")
        assert False, "expected Unavailable"
    except Unavailable:
        pass
    finally:
        srv.shutdown()


def test_second_look_down_is_reported_not_raised_as_a_crash():
    sl = SecondLook("http://127.0.0.1:9")                          # nothing listens there
    try:
        sl.customer("x@example.com")
        assert False, "expected Unavailable"
    except Unavailable:
        pass


from helpdesk import app  # noqa: E402

TICKETS = {"agents": [{"id": "marta", "name": "Marta"}, {"id": "giulia", "name": "Giulia"}],
           "tickets": [{"id": 2041, "from_name": "Dario Vitale", "from_email": "dario.v@example.com", "subject": "Where is my apron?",
                        "status": "open", "messages": [{"from": "customer", "at": "2026-10-18T20:44:00Z",
                                                        "text": "Refund me <script>alert(1)</script> or I go to PayPal."}]}]}
CASE = {"dispute_id": "DEMO-031", "status": "WAITING_FOR_SELLER_RESPONSE", "stage": "INQUIRY",
        "amount": {"value": "58.00", "currency_code": "EUR"}, "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
        "evidence": {}, "review": {"recommended": "DEFEND", "confidence": 0.85, "limits_notes": [], "checks": [],
                                   "draft_reply": "Hello Dario", "sent": None, "out_of_date": [], "mark": "m1"},
        "for_person": {"person": "Marta", "action": "DEFEND", "outcome": "send", "to": None, "why": None,
                       "amount": 0.0, "says": "Sends exactly this to PayPal.", "draft": "Hello Dario"}}
# The shape of DEMO-034 as Second Look's API gives it (the case in the screenshot): your call, over Marta's limit.
SHIRT = {**CASE, "dispute_id": "DEMO-034", "amount": {"value": "89.00", "currency_code": "EUR"}, "reason": "CREDIT_NOT_PROCESSED",
         "evidence": {"costs": {"currency": "EUR", "refund_now": {"out_of_pocket": 39.28}, "settled": {"dispute_fee": 0.0},
                                "claim_lost": {"dispute_fee": 14.0, "out_of_pocket": 53.28}}},
         "review": {**CASE["review"], "recommended": "ASK_SELLER", "ai_said": "REFUND", "confidence": 0.95,
                    "limits_notes": ["Refund of 89.00 EUR is above your auto-refund cap of 50.00; you decide."],
                    "checks": [{"id": "claim", "result": "FAIL", "group": "FAIL", "label": "What the buyer actually claims",
                                "finding": "He returned the shirt and has no refund. This is a missing-refund claim."},
                               {"id": "timeline", "result": "INCONSISTENT", "group": "INCONSISTENT",
                                "label": "Order, shipping, delivery and dispute dates make sense together",
                                "finding": "The return date is before the delivery date. Check the courier."},
                               {"id": "delivery_proof", "result": "PASS", "group": "PASS", "label": "Proof of delivery",
                                "finding": "Delivered."}]},
         "for_person": {"person": "Marta", "action": "REFUND", "outcome": "pass", "to": "Giulia", "why": None, "amount": 89.0,
                        "says": "Refund in full of 89.00 EUR is over your 30.00 EUR limit. Giulia decides; nothing is sent now.",
                        "draft": "Hello Pablo"}}


class FakeSL:
    def __init__(self, case=CASE, customer=None, down=False, nobody=False):
        self.calls, self._case, self.down = [], case, down
        self._customer = None if nobody else customer if customer is not None else {
            "name": "Dario Vitale", "orders": 5, "disputes": [{"dispute_id": "DEMO-031", "outcome": "Open"}],
            "shop_dispute_rate": 0.02}

    def customer(self, email):
        if self.down:
            from helpdesk.secondlook_client import Unavailable
            raise Unavailable("down")
        return self._customer

    def case(self, did, as_person=None):
        self.calls.append(("case", did, as_person))
        return self._case

    def approve(self, did, action, message, by, review):
        self.calls.append(("approve", did, action, message, by, review))
        return 202, "Passed to Giulia: refund in full of 89.00 EUR is over your 30.00 EUR limit. Nothing was sent."


def bench(sl, tickets=None):
    tmp = Path(tempfile.mkdtemp())
    (tmp / "tickets.json").write_text(json.dumps(tickets or TICKETS))
    return app.Helpdesk(tmp / "tickets.json", tmp / "events.jsonl", sl)


def test_the_panel_shows_second_look_from_the_api_and_escapes_the_buyer():
    hd = bench(FakeSL())
    html = hd.ticket_page(2041, "marta")
    assert "Defend with evidence" in html and "Approve as Marta" in html and "Hello Dario" in html
    assert "Sends exactly this to PayPal." in html                     # Second Look's own sentence, verbatim
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert ("case", "DEMO-031", "marta") in hd.sl.calls


def test_second_look_shows_as_its_own_product_inside_ticketbook():
    html = bench(FakeSL()).ticket_page(2041, "marta")
    assert "Schibsted+Grotesk" in html and 'class="sl-mark"' in html and "Ticketbook" in html


def test_over_her_limit_the_button_passes_it_on_and_says_both_numbers():
    html = bench(FakeSL(case=SHIRT)).ticket_page(2041, "marta")
    assert "Pass to Giulia" in html and "Approve as Marta" not in html
    assert "Refund in full of 89.00 EUR is over your 30.00 EUR limit. Giulia decides; nothing is sent now." in html


def test_checks_are_grouped_as_second_look_groups_them_and_the_decision_comes_first():
    html = bench(FakeSL(case=SHIRT)).ticket_page(2041, "marta")
    incon, fail = html.index("Doesn&#x27;t add up: check these first"), html.index("Supports the buyer&#x27;s claim")
    assert html.index("The return date is before the delivery date.") > incon
    assert fail > html.index("The return date is before the delivery date.")    # its own heading, after
    assert html.index("He returned the shirt and has no refund.") > fail
    assert "What doesn" not in html and "Delivered." not in html                 # no single heading, no PASS rows
    assert "<details" in html and "This is a missing-refund claim." in html      # the rest of a finding, folded
    button = html.index("Pass to Giulia")
    assert button < incon and button < html.index("Refund now:")                  # the decision before checks and costs


def test_every_outcome_without_a_button_shows_second_looks_sentence():
    says = {"refused": "Held back: hidden instructions. Decide in PayPal.",
            "sent": "Evidence submitted. Sent by Marta, 09:14.",
            "out_of_date": "This answer is out of date: the buyer wrote again.",
            "nothing_to_send": "Kept for reference: nothing to send while PayPal waits for the buyer.",
            "waiting": "Waiting for Giulia: they decide this one. Nothing to send from here.",
            "not_reviewed": "Not reviewed yet."}
    for outcome, text in says.items():
        fp = {**CASE["for_person"], "outcome": outcome, "says": text, "why": text if outcome == "refused" else None}
        html = bench(FakeSL(case={**CASE, "for_person": fp})).ticket_page(2041, "marta")
        assert "Approve as" not in html and "Pass to" not in html, outcome
        assert html_escape(text) in html, outcome
    for patch in ({"review": {**CASE["review"], "sent": "Evidence submitted. Sent by Marta, 09:14."}},
                  {"review": {**CASE["review"], "out_of_date": ["the buyer wrote again"]}}):
        html = bench(FakeSL(case={**CASE, **patch})).ticket_page(2041, "marta")
        assert "Approve as" not in html and "Pass to" not in html, patch          # never a button on a sent or stale review


def html_escape(text):
    import html
    return html.escape(text)


def test_approving_sends_the_agent_and_the_review_seen_and_shows_second_looks_answer():
    hd = bench(FakeSL())
    code, text = hd.approve(2041, "marta", {"dispute_id": "DEMO-031", "action": "DEFEND", "message": "Hello Dario", "review": "m1"})
    assert hd.sl.calls[-1] == ("approve", "DEMO-031", "DEFEND", "Hello Dario", "marta", "m1")
    assert code == 202 and text.startswith("Passed to Giulia")


def test_approving_only_for_an_open_dispute_of_this_customer():
    hd = bench(FakeSL())
    code, _ = hd.approve(2041, "marta", {"dispute_id": "DEMO-099", "action": "REFUND", "message": "x", "review": "m1"})
    assert code == 400 and not [c for c in hd.sl.calls if c[0] == "approve"]


def test_second_look_down_the_ticket_still_opens():
    html = bench(FakeSL(down=True)).ticket_page(2041, "marta")
    assert "Where is my apron?" in html and "Second Look isn't answering" in html


def test_an_answer_ticketbook_cant_read_never_takes_the_ticket_down():
    for sl in (FakeSL(customer=[1, 2]), FakeSL(case={**CASE, "review": "a string"}), FakeSL(case={**CASE, "for_person": [1]})):
        html = bench(sl).ticket_page(2041, "marta")
        assert "Where is my apron?" in html and "Second Look answered something Ticketbook couldn&#x27;t read" in html


def test_the_customer_line_counts_in_words():
    one = {"name": "Ann", "orders": 1, "disputes": [{"dispute_id": "DEMO-031", "outcome": "Open"}], "shop_dispute_rate": 0.02}
    html = bench(FakeSL(customer=one)).ticket_page(2041, "marta")
    assert "1 order, 1 PayPal dispute" in html
    html = bench(FakeSL(nobody=True)).ticket_page(2041, "marta")
    assert "No orders or PayPal disputes for this email in Second Look." in html


def test_a_rules_baseline_review_is_never_shown_as_the_ai():
    html = bench(FakeSL(case={**SHIRT, "review": {**SHIRT["review"], "judge": "rules"}})).ticket_page(2041, "marta")
    assert "Rules baseline, not the AI" in html and "The AI&#x27;s own answer" not in html and "Confidence" not in html
    assert "Confidence" in bench(FakeSL(case=SHIRT)).ticket_page(2041, "marta")


def test_limits_notes_that_are_not_a_list_are_ignored():
    html = bench(FakeSL(case={**CASE, "review": {**CASE["review"], "limits_notes": "abc"}})).ticket_page(2041, "marta")
    assert "<li>a</li>" not in html


def test_a_second_look_notification_lands_on_the_ticket():
    hd = bench(FakeSL())
    hd.add_event({"event": "answer.sent", "dispute_id": "DEMO-031", "action": "DEFEND", "by": "Marta",
                  "what_happened": "Evidence submitted and reply sent. Sent by Marta, 09:14."})
    hd.add_event({"event": "answer.sent", "dispute_id": "DEMO-999", "by": "Luca", "what_happened": "elsewhere"})
    assert not hd.add_event([1, 2]) and not hd.add_event({"event": 1, "dispute_id": "DEMO-031"})
    html = hd.ticket_page(2041, "marta")
    assert "answer sent to PayPal by Marta" in html and "elsewhere" not in html


def test_the_history_is_in_time_order_across_the_customers_disputes():
    two = {"name": "Dario", "orders": 5, "shop_dispute_rate": 0.02,
           "disputes": [{"dispute_id": "DEMO-031", "outcome": "Open"}, {"dispute_id": "DEMO-032", "outcome": "Open"}]}
    hd = bench(FakeSL(customer=two))
    hd.add_event({"event": "case.handed_off", "dispute_id": "DEMO-032", "from": "Marta", "to": "Giulia"})
    hd.add_event({"event": "answer.sent", "dispute_id": "DEMO-031", "by": "Luca"})
    html = hd.ticket_page(2041, "marta")
    assert html.index("passed to Giulia by Marta") < html.index("answer sent to PayPal by Luca")


def test_once_passed_on_the_page_says_who_decides_and_the_colleague_gets_the_edited_reply():
    hand = {"from": "marta", "from_name": "Marta", "action": "REFUND", "amount": 89.0, "message": "Marta's words"}
    waiting = {**SHIRT, "assigned_to": "giulia", "handoff": hand,
               "for_person": {**SHIRT["for_person"], "outcome": "waiting", "to": "Giulia",
                              "says": "Waiting for Giulia: they decide this one. Nothing to send from here."}}
    html = bench(FakeSL(case=waiting)).ticket_page(2041, "marta")
    assert "Waiting for Giulia" in html and "Pass to Giulia" not in html
    mine = {**waiting, "for_person": {"person": "Giulia", "action": "REFUND", "outcome": "send", "to": None, "why": None,
                                      "amount": 89.0, "says": "Your limits held this back for its size only. You decide: this sends it.",
                                      "draft": "Marta's words"}}
    html = bench(FakeSL(case=mine)).ticket_page(2041, "giulia")
    assert "Approve as Giulia: refund in full (89.00 EUR)" in html and "Passed to you by Marta" in html
    assert "Marta&#x27;s words" in html


# ---------- the HTTP layer ----------

import http.client  # noqa: E402
import os  # noqa: E402
from urllib.parse import urlencode  # noqa: E402


class served:
    """Ticketbook's own server on a free port, around a Helpdesk bench."""

    def __init__(self, hd):
        self.hd = hd

    def __enter__(self):
        handler = type("H", (app.Handler,), {"hd": self.hd})
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]
        return self

    def __exit__(self, *a):
        self.srv.shutdown()

    def ask(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        out = (r.status, dict(r.getheaders()), r.read().decode())
        c.close()
        return out


FORM = {"Content-Type": "application/x-www-form-urlencoded"}


def test_http_the_agent_cookie_is_set_only_for_a_known_agent():
    with served(bench(FakeSL())) as s:
        assert "tb_agent=marta" in s.ask("GET", "/?as=marta")[1].get("Set-Cookie", "")
        assert "Set-Cookie" not in s.ask("GET", "/?as=evil")[1]


def test_http_approve_needs_a_known_agent_and_this_helpdesk_as_origin():
    with served(bench(FakeSL())) as s:
        form = {"dispute_id": "DEMO-031", "action": "DEFEND", "message": "Hello", "review": "m1"}
        assert s.ask("POST", "/t/2041/approve", urlencode({**form, "by": "nobody"}), FORM)[0] == 400
        evil = {**FORM, "Origin": "http://evil.example"}
        assert s.ask("POST", "/t/2041/approve", urlencode({**form, "by": "marta"}), evil)[0] == 403
        assert not [c for c in s.hd.sl.calls if c[0] == "approve"]
        ok = {**FORM, "Origin": f"http://127.0.0.1:{s.port}"}
        code, headers, _ = s.ask("POST", "/t/2041/approve", urlencode({**form, "by": "marta"}), ok)
        assert code == 303 and "Passed" not in headers["Location"]          # the answer is not in the URL


def test_http_the_flash_shows_once():
    with served(bench(FakeSL())) as s:
        form = urlencode({"dispute_id": "DEMO-031", "action": "DEFEND", "message": "Hello", "review": "m1", "by": "marta"})
        where = s.ask("POST", "/t/2041/approve", form, FORM)[1]["Location"]
        assert "Passed to Giulia" in s.ask("GET", where)[2]
        assert "Passed to Giulia" not in s.ask("GET", where)[2]


def test_http_the_hook_takes_json_only_and_the_key_when_one_is_set():
    with served(bench(FakeSL())) as s:
        ev = json.dumps({"event": "answer.sent", "dispute_id": "DEMO-031", "by": "Marta"})
        js = {"Content-Type": "application/json"}
        assert s.ask("POST", "/hooks/secondlook", ev, js)[0] == 204
        assert s.ask("POST", "/hooks/secondlook", "not json", js)[0] == 400
        assert s.ask("POST", "/hooks/secondlook", ev, {"Content-Type": "text/plain"})[0] == 415
        os.environ["TICKETBOOK_HOOK_KEY"] = "s3cret"
        try:
            assert s.ask("POST", "/hooks/secondlook", ev, js)[0] == 403
            assert s.ask("POST", "/hooks/secondlook?key=wrong", ev, js)[0] == 403
            assert s.ask("POST", "/hooks/secondlook?key=s3cret", ev, js)[0] == 204
        finally:
            del os.environ["TICKETBOOK_HOOK_KEY"]
        assert len(s.hd.events_for("DEMO-031")) == 2


def test_http_the_injection_ticket_renders_as_text():
    real = json.loads((Path(__file__).resolve().parent.parent / "helpdesk" / "tickets.json").read_text())
    t = next(t for t in real["tickets"] if "SYSTEM:" in t["messages"][0]["text"])
    with served(bench(FakeSL(nobody=True), tickets=real)) as s:
        page = s.ask("GET", f"/t/{t['id']}?as=marta")[2]
        assert f"<p>{html_escape(t['messages'][0]['text'])}</p>" in page
        inbox = s.ask("GET", "/?as=marta")[2]
        assert html_escape(t["messages"][0]["text"]) in inbox and "Approve as" not in page


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
