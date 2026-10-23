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
        "for_person": {"person": "Marta", "action": "DEFEND", "outcome": "send", "to": None, "why": None}}


class FakeSL:
    def __init__(self, case=CASE, customer=None, down=False):
        self.calls, self._case, self.down = [], case, down
        self._customer = customer or {"name": "Dario Vitale", "orders": 5, "disputes": [{"dispute_id": "DEMO-031", "outcome": "Open"}],
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


def bench(sl):
    tmp = Path(tempfile.mkdtemp())
    (tmp / "tickets.json").write_text(json.dumps(TICKETS))
    return app.Helpdesk(tmp / "tickets.json", tmp / "events.jsonl", sl)


def test_the_panel_shows_second_look_from_the_api_and_escapes_the_buyer():
    hd = bench(FakeSL())
    html = hd.ticket_page(2041, "marta")
    assert "Defend with evidence" in html and "Approve as Marta" in html and "Hello Dario" in html
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert ("case", "DEMO-031", "marta") in hd.sl.calls


def test_over_her_limit_the_button_passes_it_on():
    case = {**CASE, "for_person": {"person": "Marta", "action": "REFUND", "outcome": "pass", "to": "Giulia", "why": None}}
    html = bench(FakeSL(case=case)).ticket_page(2041, "marta")
    assert "Pass to Giulia" in html and "Approve as Marta" not in html


def test_refused_sent_or_out_of_date_offer_no_button():
    for patch in ({"for_person": {**CASE["for_person"], "outcome": "refused", "why": "Held back: hidden instructions"}},
                  {"review": {**CASE["review"], "sent": "Evidence submitted. Sent by Marta, 09:14."}},
                  {"review": {**CASE["review"], "out_of_date": ["the buyer wrote again"]}}):
        html = bench(FakeSL(case={**CASE, **patch})).ticket_page(2041, "marta")
        assert "Approve as" not in html and "Pass to" not in html, patch


def test_approving_sends_the_agent_and_the_review_seen_and_shows_second_looks_answer():
    hd = bench(FakeSL())
    code, text = hd.approve(2041, "marta", {"dispute_id": "DEMO-031", "action": "DEFEND", "message": "Hello Dario", "review": "m1"})
    assert hd.sl.calls[-1] == ("approve", "DEMO-031", "DEFEND", "Hello Dario", "marta", "m1")
    assert code == 202 and text.startswith("Passed to Giulia")


def test_second_look_down_the_ticket_still_opens():
    html = bench(FakeSL(down=True)).ticket_page(2041, "marta")
    assert "Where is my apron?" in html and "Second Look isn't answering" in html


def test_a_second_look_notification_lands_on_the_ticket():
    hd = bench(FakeSL())
    hd.add_event({"event": "answer.sent", "dispute_id": "DEMO-031", "action": "DEFEND", "by": "Marta",
                  "what_happened": "Evidence submitted and reply sent. Sent by Marta, 09:14."})
    hd.add_event({"event": "answer.sent", "dispute_id": "DEMO-999", "by": "Luca", "what_happened": "elsewhere"})
    html = hd.ticket_page(2041, "marta")
    assert "answer sent to PayPal by Marta" in html and "elsewhere" not in html


def test_once_passed_on_the_page_says_who_decides_and_the_colleague_gets_the_edited_reply():
    hand = {"from": "marta", "from_name": "Marta", "action": "REFUND", "amount": 89.0, "message": "Marta's words"}
    passed = {**CASE, "assigned_to": "giulia", "handoff": hand,
              "for_person": {"person": "Marta", "action": "REFUND", "outcome": "pass", "to": "Giulia", "why": None}}
    html = bench(FakeSL(case=passed)).ticket_page(2041, "marta")
    assert "Waiting for Giulia" in html and "Pass to Giulia" not in html
    mine = {**passed, "for_person": {"person": "Giulia", "action": "REFUND", "outcome": "send", "to": None, "why": None}}
    html = bench(FakeSL(case=mine)).ticket_page(2041, "giulia")
    assert "Approve as Giulia" in html and "Passed to you by Marta" in html and "Marta&#x27;s words" in html


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
