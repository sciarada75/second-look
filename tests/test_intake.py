"""Every request reaches one case: intake, sorting, the case page and its API. Run: python3 tests/test_intake.py"""
import json
import sys
import tempfile
import threading
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secondlook import sort as sort_mod, team as team_mod, web  # noqa: E402
from secondlook.demo import DemoPayPal  # noqa: E402


@contextmanager
def morning(ai_key=False, ai=None):
    """The demo shop's real data, with its case file and assignments in a temporary folder (nothing on this
    machine changes), and Second Look's AI either absent or faked. The real AI fails the test if it is asked."""
    tmp = Path(tempfile.mkdtemp())
    kept = web.CASE_FILES, web.assignments_for, web.has_ai_key, sort_mod.read_with_ai, web.SUGGESTED
    store = team_mod.Assignments(tmp / "assignments.json", seed=DemoPayPal().raw.get("assignments"))

    def no_paid_call(request):
        raise AssertionError("Second Look's AI must not be asked in this test")
    try:
        web.CASE_FILES = {"demo": tmp / "cases-demo.json", "live": tmp / "cases-live.json"}
        web.assignments_for = lambda did: store
        web.has_ai_key = lambda: ai_key
        sort_mod.read_with_ai = ai or no_paid_call
        web.SUGGESTED = tmp / "suggested.json"
        yield tmp
    finally:
        web.CASE_FILES, web.assignments_for, web.has_ai_key, sort_mod.read_with_ai, web.SUGGESTED = kept


def email(text, address, source_id=None, subject="", channel="email", time="2026-10-20T08:15:00Z"):
    return {"channel": channel, "from": {"name": "", "email": address}, "text": text, "subject": subject,
            "source_id": source_id, "time": time}


def test_a_request_is_checked_before_anything_is_filed():
    with morning() as tmp:
        for body, why in [([], "one JSON object"), ({**email("x", "a@b.c"), "channel": "call"}, "later step"),
                          ({**email("x", "a@b.c"), "channel": "paypal"}, "read from PayPal"),
                          ({**email("x", "a@b.c"), "from": {"email": "nobody"}}, "from.email"),
                          (email("   ", "a@b.c"), "text"), ({**email("x", "a@b.c"), "subject": 7}, "subject")]:
            code, out = web.receive("demo", body)
            assert code == 400 and why in out["error"], (body, out)
        assert not (tmp / "cases-demo.json").exists()      # nothing checked, nothing written


def test_the_demo_morning_starts_with_its_requests_on_their_cases():
    with morning():
        cs = {c["id"]: c for c in web.case_store("demo").all()}
        assert sorted(cs) == ["DEMO-C001", "DEMO-C002", "DEMO-C003"]
        sophie, lena, pablo = cs["DEMO-C001"], cs["DEMO-C002"], cs["DEMO-C003"]
        assert (sophie["customer"]["name"], sophie["order_no"], sophie["stage"]) == ("Sophie Durand", "LP-90001", "inquiry")
        assert (lena["order_no"], lena["problem"]["kind"], lena["timeline"][0]["channel"]) == ("LP-90002", "wrong_size", "form")
        assert (pablo["dispute_id"], pablo["stage"], pablo["order_no"]) == ("DEMO-034", "paypal_dispute", "DEMOTX01828")
        assert all(c["sorted"]["by"] == "rules" for c in cs.values())


def test_a_helpdesk_email_is_filed_once_and_joins_the_dispute_on_its_order():
    with morning():
        code, out = web.receive("demo", email("Hello, my apron never came. Refund me or I go to PayPal. Dario",
                                              "dario.v@example.com", source_id="ticketbook:2001", subject="Where is my apron?"))
        assert code == 201 and out["filed"] == "opened" and out["dispute_id"] == "DEMO-031" and out["stage"] == "paypal_dispute"
        again = web.receive("demo", email("Hello, my apron never came.", "dario.v@example.com", source_id="ticketbook:2001"))
        assert again == (200, {**out, "filed": "already_received"})
        code, more = web.receive("demo", email("Any news on my apron?", "dario.v@example.com", time="2026-10-20T09:00:00Z"))
        assert code == 201 and more["filed"] == "joined" and more["case_id"] == out["case_id"]


def test_the_ai_is_asked_only_what_the_rules_cannot_settle():
    asked = []

    def fake(request):
        asked.append(request["text"])
        return {"order_no": "", "item": "napkins", "problem_kind": "not_as_described", "summary": "Stained napkins"}
    with morning(ai_key=True, ai=fake):
        web.receive("demo", email("Order LP-90001 hasn't arrived.", "sophie.durand@example.com"))
        assert asked == []                                          # the rules settled it
        kept = web.shop_orders
        two = [{"transaction_id": "T1", "email": "ada@example.com", "name": "Ada", "time": "2026-09-01T10:00:00Z",
                "amount": 20.0, "items": [{"item_name": "Art print", "item_quantity": "1"}]},
               {"transaction_id": "T2", "email": "ada@example.com", "name": "Ada", "time": "2026-10-01T10:00:00Z",
                "amount": 36.0, "items": [{"item_name": "Linen napkins", "item_quantity": "1"}]}]
        web.shop_orders = lambda src: two
        try:
            code, out = web.receive("demo", email("Something arrived damaged.", "ada@example.com"))
        finally:
            web.shop_orders = kept
        assert asked == ["Something arrived damaged."] and out["sorted"]["by"] == "ai"


def test_a_malformed_request_is_a_plain_400_never_a_server_error():
    """Whatever another system sends, the answer says what is wrong (review, 25/10): no 500, nothing filed."""
    good = email("Where is my parcel?", "a@b.c")
    bodies = [None, "text", 7, {}, {k: v for k, v in good.items() if k != "channel"}, {**good, "channel": None},
              {**good, "channel": ["email"]}, {k: v for k, v in good.items() if k != "text"}, {**good, "text": 5},
              {**good, "text": None}, {**good, "text": ["x"]}, {**good, "text": "x" * 10001}, {**good, "from": "a@b.c"},
              {**good, "from": None}, {**good, "from": {"email": 5}}, {**good, "from": {"name": 5, "email": "nobody"}},
              {**good, "time": 5}, {**good, "source_id": {"x": 1}}, {**good, "order": 12345}]
    with morning() as tmp:
        for body in bodies:
            code, out = web.receive("demo", body)
            assert code == 400 and isinstance(out.get("error"), str) and out["error"], (body, out)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            for body in bodies + [b"not json at all"]:
                con = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                con.request("POST", "/api/requests?shop=demo", body=raw, headers={"Content-Type": "application/json"})
                r = con.getresponse()
                assert r.status == 400 and json.loads(r.read())["error"], (body, r.status)
                con.close()
        finally:
            srv.shutdown()
            srv.server_close()
        assert not (tmp / "cases-demo.json").exists()


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
