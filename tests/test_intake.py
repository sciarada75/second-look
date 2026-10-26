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
from secondlook import cases as cases_mod, sort as sort_mod, team as team_mod, web  # noqa: E402
# Tests never run local whisper: a call's words are the transcript shipped beside it (26/10).
web.TRANSCRIBE = lambda wav: None
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
        for body, why in [([], "one JSON object"), ({**email("x", "a@b.c"), "channel": "call"}, "call box"),
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


def test_an_unknown_sender_waits_unsorted_until_a_person_picks_the_order():
    with morning():
        code, out = web.receive("demo", email("My tablecloth still isn't here.", "s.durand@work.example"))
        assert code == 201 and out["sorted"]["by"] is None
        page = web.case_file_page(out["case_id"], me="marta")
        assert "Which order is it about?" in page and "a person picks the order" in page
        assert web.pick_order(out["case_id"], "LP-90001", None)[0] == 400          # nobody named
        assert web.pick_order(out["case_id"], "LP-99999", "marta")[0] == 400       # no such order
        assert web.pick_order(out["case_id"], "LP-90001", "marta") == (200, "DEMO-C001")   # joins Sophie's case
        assert len(web.case_store("demo").get("DEMO-C001")["timeline"]) == 4     # her call, her email, this, the note


def test_the_case_page_shows_every_channel_every_role_and_the_cost_so_far():
    with morning():
        pablo = web.case_file_page("DEMO-C003", me="marta")
        assert "PayPal dispute" in pablo and "Pablo Martin, <i>customer</i>" in pablo
        assert "Marta, <i>Customer care assistant</i>, has this case." in pablo        # DEMO-034 is Marta's
        assert "Everything said, every channel" in pablo and "✉️" in pablo and "PayPal dispute opened" in pablo
        assert "Cost so far" in pablo and "estimated" in pablo and "2 (1 by email, 1 by PayPal)" in pablo
        assert 'href="/d/DEMO-034"' in pablo and "Pass to Giulia" in pablo          # the dispute's own buttons, here
        sophie = web.case_file_page("DEMO-C001", me="marta")
        assert "Shop inquiry" in sophie and "Order LP-90001: Linen tablecloth × 1, 64.00 EUR, paid by card." in sophie
        assert "Nobody has this case yet." in sophie and "Sorted by Second Look&#x27;s rules" in sophie
        assert "shipped with the demo" in sophie and "Approve: reply only" in sophie   # the review that ships with it
        kept, web.SHIPPED = web.SHIPPED, web.ROOT / "no-shipped-reviews"
        try:                                   # no review and no AI key: the rules baseline, labelled
            bare = web.case_file_page("DEMO-C001", me="marta")
        finally:
            web.SHIPPED = kept
        assert "Take a second look (rules baseline)" in bare and "the courier's status" in bare
        assert "No case with that id" in web.case_file_page("DEMO-C999")
        assert "/c/DEMO-C003" in web.case_page("DEMO-034", me="marta")             # the dispute names its case


def test_the_api_gives_a_case_as_its_page_shows_it():
    with morning():
        c = web.api_case_of("DEMO-C003")
        assert c["customer"] == {"name": "Pablo Martin", "email": "pablo.m576@example.com", "role": "customer"}
        assert c["channels"] == ["email", "paypal"] and c["dispute_id"] == "DEMO-034" and c["stage"] == "paypal_dispute"
        assert c["assigned_to"] == {"id": "marta", "name": "Marta", "role": "Customer care assistant"}
        assert c["at_stake"] == {"value": 89.0, "currency_code": "EUR"} and c["costs_so_far"]["estimated"] is True
        assert [x["channel"] for x in c["timeline"]] == ["email", "paypal", "paypal"]
        assert web.api_case_of("DEMO-C999") is None


def test_the_list_shows_the_requests_under_the_disputes_by_whose_they_are():
    with morning():
        everyone = web.inbox_page("demo", "marta", "all")
        assert "Requests by email and web form" in everyone and "/c/DEMO-C001" in everyone and "/c/DEMO-C002" in everyone
        assert "/c/DEMO-C003" not in everyone          # Pablo's is a PayPal dispute: it is in the list above
        assert "/c/DEMO-C001" not in web.inbox_page("demo", "marta", "mine")


def test_the_shop_s_rules_say_how_staff_time_is_estimated():
    page = web.rules_page()
    assert "staff time is estimated at 25 EUR an hour; each written answer counts 6 minutes" in page


def test_http_requests_come_as_json_from_your_own_systems():
    with morning():
        srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]

        def ask(method, path, body=None, headers=None):
            con = HTTPConnection("127.0.0.1", port, timeout=10)
            con.request(method, path, body=body, headers=headers or {})
            r = con.getresponse()
            return r.status, r.read().decode()
        try:
            good = json.dumps(email("Order LP-90002: still too small.", "lena.vogel@example.com", source_id="tb:9"))
            assert ask("POST", "/api/requests", good, {"Content-Type": "text/plain"})[0] == 415
            assert ask("POST", "/api/requests", good, {"Content-Type": "application/json",
                                                       "Origin": "http://evil.example"})[0] == 403
            assert ask("POST", "/api/requests", "{not json", {"Content-Type": "application/json"})[0] == 400
            code, text = ask("POST", "/api/requests", good, {"Content-Type": "application/json",
                                                             "Origin": f"http://127.0.0.1:{port}"})
            assert code == 201 and json.loads(text)["case_id"] == "DEMO-C002"     # joins Lena's case
            assert ask("POST", "/api/requests", good, {"Content-Type": "application/json"})[0] == 200
            assert ask("GET", "/api/cases/DEMO-C002")[0] == 200 and ask("GET", "/api/cases/DEMO-C999")[0] == 404
            code, html_ = ask("GET", "/c/DEMO-C002?as=marta")
            assert code == 200 and "Lena Vogel" in html_
        finally:
            srv.shutdown()

# ---------- review (25/10): escaping, the AI's reading labelled, an order for a question ----------

def test_what_a_customer_or_the_ai_wrote_is_shown_as_text_never_run_as_code():
    bad, odd = "<script>alert(1)</script>", "<b onmouseover=x>"   # odd: an item name the message doesn't name
    shop = [{"transaction_id": "T1", "email": "ada@example.com", "name": "Ada " + bad, "time": "2026-09-01T10:00:00Z",
             "amount": 20.0, "items": [{"item_name": "Art print " + odd, "item_quantity": "1"}]},
            {"transaction_id": "T2", "email": "ada@example.com", "name": "Ada " + bad, "time": "2026-10-01T10:00:00Z",
             "amount": 36.0, "items": [{"item_name": "Linen napkins", "item_quantity": "1"}]}]
    fake = lambda r: {"order_no": "", "item": "art print", "problem_kind": "not_as_described", "summary": "Sum " + bad}  # noqa: E731
    with morning(ai_key=True, ai=fake):
        web.case_store("demo")                     # the demo morning, filed on the real orders first
        kept = web.shop_orders
        web.shop_orders = lambda src: shop
        try:
            _, by_ai = web.receive("demo", {**email("It came broken " + bad, "ada@example.com", subject="Subj " + bad),
                                            "from": {"name": "Name " + bad, "email": "ada@example.com"}})
            _, loose = web.receive("demo", {**email("Hello " + bad, "who@nowhere.example", subject="S " + bad),
                                            "from": {"name": "N " + bad, "email": "who@nowhere.example"}})
            pages = [web.case_file_page(by_ai["case_id"], me="marta"), web.case_file_page(loose["case_id"], me="marta"),
                     web.inbox_page("demo", "marta", "all")]
        finally:
            web.shop_orders = kept
    assert by_ai["sorted"]["by"] == "ai"
    for p in pages:
        assert "<script>alert" not in p and "&lt;script&gt;alert" in p          # (the list page has its own script)
    assert "<b onmouseover" not in pages[0] and "Art print &lt;b onmouseover=x&gt;" in pages[0]
    assert "Sum &lt;script&gt;" in pages[0] and "Subj &lt;script&gt;" in pages[0]
    assert "N &lt;script&gt;" in pages[1] and "Hello &lt;script&gt;" in pages[1]


def test_a_summary_written_by_the_ai_is_shown_as_its_reading_of_the_message():
    two = [{"transaction_id": "T1", "email": "ada@example.com", "name": "Ada", "time": "2026-09-01T10:00:00Z",
            "amount": 20.0, "items": [{"item_name": "Art print", "item_quantity": "1"}]},
           {"transaction_id": "T2", "email": "ada@example.com", "name": "Ada", "time": "2026-10-01T10:00:00Z",
            "amount": 36.0, "items": [{"item_name": "Linen napkins", "item_quantity": "1"}]}]
    fake = lambda r: {"order_no": "", "item": "napkins", "problem_kind": "not_as_described",  # noqa: E731
                      "summary": "The shop agreed to refund the napkins"}
    with morning(ai_key=True, ai=fake):
        web.case_store("demo")                     # the demo morning, filed on the real orders first
        kept = web.shop_orders
        web.shop_orders = lambda src: two
        try:
            _, out = web.receive("demo", email("Something arrived damaged.", "ada@example.com"))
            page = web.case_file_page(out["case_id"], me="marta")
            listed = web.inbox_page("demo", "marta", "all")
        finally:
            web.shop_orders = kept
        sophie = web.case_file_page("DEMO-C001", me="marta")
    said = "Second Look&#x27;s AI reads this as: The shop agreed to refund the napkins"
    assert said in page and said in listed
    assert "Second Look&#x27;s AI reads this as" not in sophie                   # rules: the customer's own words


def test_a_question_can_still_be_given_its_order_but_an_order_is_never_picked_twice():
    two = [{"transaction_id": "T1", "email": "ada@example.com", "name": "Ada", "time": "2026-09-01T10:00:00Z",
            "amount": 20.0, "items": [{"item_name": "Art print", "item_quantity": "1"}]},
           {"transaction_id": "T2", "email": "ada@example.com", "name": "Ada", "time": "2026-10-01T10:00:00Z",
            "amount": 36.0, "items": [{"item_name": "Linen shirt", "item_quantity": "1"}]}]
    with morning():
        web.case_store("demo")                     # the demo morning, filed on the real orders first
        kept = web.shop_orders
        web.shop_orders = lambda src: two
        try:
            _, out = web.receive("demo", email("Can I exchange it for a bigger size?", "ada@example.com"))
            cid = out["case_id"]
            assert out["sorted"]["by"] == "rules" and web.case_store("demo").get(cid)["order_no"] is None
            page = web.case_file_page(cid, me="marta")
            assert "Is it about an order?" in page and f'action="/c/{cid}/order"' in page
            assert web.pick_order(cid, "none", "marta")[0] == 409                 # already a question
            assert web.pick_order(cid, "T2", "marta") == (200, cid)
            c = web.case_store("demo").get(cid)
            assert c["order_no"] == "T2" and c["sorted"]["by"] == "person"
            assert web.pick_order(cid, "T1", "marta")[0] == 409                    # settled on an order: never again
            assert web.pick_order("DEMO-C001", "LP-90001", "marta")[0] == 409
        finally:
            web.shop_orders = kept



def test_an_order_number_typed_into_the_pick_form_comes_back_as_text():
    from urllib.parse import urlencode
    with morning():
        _, out = web.receive("demo", email("My tablecloth still isn't here.", "s.durand@work.example"))
        srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            con = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            con.request("POST", f"/c/{out['case_id']}/order", body=urlencode({"by": "marta", "order": "<script>x</script>"}),
                        headers={"Content-Type": "application/x-www-form-urlencoded"})
            r = con.getresponse()
            body = r.read().decode()
            assert r.status == 400 and "<script>x" not in body and "&lt;script&gt;x" in body, (r.status, body[:200])
        finally:
            srv.shutdown()
            srv.server_close()


def test_ticketbook_files_its_tickets_through_the_real_api():
    from helpdesk.secondlook_client import SecondLook
    root = Path(__file__).resolve().parent.parent
    tickets = {t["id"]: t for t in json.loads((root / "helpdesk" / "tickets.json").read_text())["tickets"]}
    with morning():
        srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            sl = SecondLook(f"http://127.0.0.1:{srv.server_address[1]}")
            assert sl.file_request(tickets[2004])["filed"] == "already_received"     # Pablo's: in the morning's cases
            assert sl.file_request(tickets[2102])["case_id"] == "DEMO-C002"          # Lena's web form
            dario = sl.file_request(tickets[2001])
            assert dario["filed"] == "opened" and dario["dispute_id"] == "DEMO-031"
            assert sl.case_of(dario["case_id"])["channels"] == ["email", "paypal"]
        finally:
            srv.shutdown()


# ---------- spec review (25/10): roles, the title, PayPal's name, posts from elsewhere, a bad length ----------

def test_every_name_on_the_timeline_carries_its_role():
    with morning():
        web.receive("demo", {**email("Any news on the shirt?", "lena.vogel@example.com", channel="form"),
                             "from": {"name": "", "email": "lena.vogel@example.com"}})
        web.receive("demo", {**email("Any news on my tablecloth?", "sophie.durand@example.com"),
                             "from": {"name": "Sophie", "email": "sophie.durand@example.com"}})
        _, other = web.receive("demo", {**email("The tablecloth: still nothing.", "s.durand@work.example",
                                               time="2026-10-20T10:00:00Z"),
                                        "from": {"name": "S. Durand", "email": "s.durand@work.example"}})
        assert web.pick_order(other["case_id"], "LP-90001", "marta") == (200, "DEMO-C001")
        store = web.case_store("demo")
        store.add("DEMO-C001", cases_mod.entry("2026-10-20T11:00", "email", "out", "It was left with Bianchi.", "Marta"))
        store.add("DEMO-C001", cases_mod.entry("2026-10-20T11:30", "email", "out", "Drafted for you.", "", ai=True))
        lena, sophie = web.case_file_page("DEMO-C002", me="marta"), web.case_file_page("DEMO-C001", me="marta")
    assert "lena.vogel@example.com, <i>customer</i>" in lena                  # no name: the address, still the customer
    assert "Sophie, <i>customer</i>" in sophie                                # another spelling of her name
    assert "S. Durand, <i>customer</i>" in sophie                             # another address, joined by a person
    assert "Marta, <i>Customer care assistant</i>" in sophie
    assert "Second Look&#x27;s AI, <i>Second Look&#x27;s AI</i>" not in sophie
    assert "· Second Look&#x27;s AI ·" in sophie                              # nobody named: the AI says it wrote it


def test_the_api_timeline_gives_each_name_its_role():
    with morning():
        web.receive("demo", {**email("Any news on the shirt?", "lena.vogel@example.com", channel="form"),
                             "from": {"name": "", "email": "lena.vogel@example.com"}})
        tl = web.api_case_of("DEMO-C002")["timeline"]
    assert [x["role"] for x in tl] == ["customer", "customer"]


def test_a_title_never_shows_the_ai_s_words_as_the_shop_s():
    two = [{"transaction_id": "T1", "email": "ada@example.com", "name": "Ada", "time": "2026-09-01T10:00:00Z",
            "amount": 20.0, "items": [{"item_name": "Art print", "item_quantity": "1"}]},
           {"transaction_id": "T2", "email": "ada@example.com", "name": "Ada", "time": "2026-10-01T10:00:00Z",
            "amount": 36.0, "items": [{"item_name": "Linen napkins", "item_quantity": "1"}]}]
    fake = lambda r: {"order_no": "", "item": "napkins", "problem_kind": "not_as_described",  # noqa: E731
                      "summary": "Refund agreed"}
    with morning(ai_key=True, ai=fake):
        web.case_store("demo")
        kept = web.shop_orders
        web.shop_orders = lambda src: two
        try:
            _, out = web.receive("demo", email("Something arrived damaged.", "ada@example.com"))
            page = web.case_file_page(out["case_id"], me="marta")
        finally:
            web.shop_orders = kept
        sophie = web.case_file_page("DEMO-C001", me="marta")
    assert f"<title>Case {out['case_id']} | Second Look</title>" in page and "<title>Refund" not in page
    # her case began with her call: its line is what the call is about, never presented as her words
    assert "<title>Phone call: says it never arrived | Second Look</title>" in sophie


def test_paypal_keeps_its_name_and_is_never_said_twice():
    with morning():
        pablo = web.case_file_page("DEMO-C003", me="marta")
    assert "Paypal" not in pablo and "PayPal PayPal" not in pablo
    assert "Came in by: ✉️ email · PayPal</p>" in pablo
    assert '<span class="chan" title="PayPal">PayPal</span> in ·' in pablo
    assert '<span class="chan" title="email">✉️</span> Email in ·' in pablo


def _server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_a_post_from_another_site_is_refused_and_your_own_pages_and_ticketbook_still_work():
    from urllib.parse import urlencode
    from helpdesk.secondlook_client import SecondLook
    done = []
    names = ("approve", "take", "run_review", "add_rule", "settle_suggestion", "remove_rule")
    kept = {n: getattr(web, n) for n in names}
    for n in names:   # nothing real can happen in this test, whatever the check does
        setattr(web, n, lambda *a, _n=n, **k: (done.append(_n), (200, "ok"))[1])
    try:
        with morning():
            _, out = web.receive("demo", email("My tablecloth still isn't here.", "s.durand@work.example"))
            cid = out["case_id"]
            srv = _server()
            port = srv.server_address[1]

            def post(path, body, kind, **headers):
                con = HTTPConnection("127.0.0.1", port, timeout=10)
                con.request("POST", path, body=body, headers={"Content-Type": kind, **headers})
                r = con.getresponse()
                r.read()
                return r.status
            form, js = "application/x-www-form-urlencoded", "application/json"
            posts = [(f"/c/{cid}/order", urlencode({"by": "marta", "order": "LP-90001"}), form),
                     ("/d/DEMO-034/approve", urlencode({"by": "marta", "action": "ASK_SELLER"}), form),
                     ("/d/DEMO-034/take", urlencode({"by": "marta"}), form), ("/d/DEMO-034/review", "", form),
                     ("/rules/add", urlencode({"rule": "x"}), form), ("/rules/accept", "i=0", form),
                     ("/rules/discard", "i=0", form), ("/rules/remove", "i=0", form),
                     ("/api/disputes/DEMO-034/approve", json.dumps({"action": "ASK_SELLER", "by": "marta"}), js),
                     ("/api/disputes/DEMO-034/review", "{}", js), ("/api/requests", json.dumps(email("x", "a@b.c")), js)]
            try:
                for path, body, kind in posts:
                    assert post(path, body, kind, Origin="http://evil.example") == 403, path
                    assert post(path, body, kind, Referer="http://evil.example/page") == 403, path
                    assert post(path, body, kind, Origin="null") == 403, path
                assert done == [] and web.case_store("demo").get(cid)["sorted"]["by"] is None
                here = f"http://127.0.0.1:{port}"
                assert post(f"/c/{cid}/order", urlencode({"by": "marta", "order": "LP-90001"}), form,
                            Origin=here, Referer=f"{here}/c/{cid}") == 303          # your own page: it works
                assert web.case_store("demo").get(cid) is None                       # joined Sophie's case
                assert SecondLook(here).approve("DEMO-034", "ASK_SELLER", None, "marta", None)[0] == 200
                assert done == ["approve"]                                           # Ticketbook: no Origin, it works
            finally:
                srv.shutdown()
                srv.server_close()
    finally:
        for n, f in kept.items():
            setattr(web, n, f)


def test_a_body_length_that_is_not_a_number_is_a_400():
    import socket
    with morning():
        srv = _server()
        try:
            for length in ("abc", "-5", ""):
                sock = socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=10)
                sock.sendall(f"POST /api/requests HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                             f"Content-Length: {length}\r\n\r\n".encode())
                got = b""
                while b"bytes." not in got:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    got += chunk
                sock.close()
                assert b" 400 " in got.split(b"\r\n")[0] + b" " and b"Content-Length must be a number" in got, (length, got)
        finally:
            srv.shutdown()
            srv.server_close()


# ---------- quality review 3 (25/10) ----------

def test_the_api_names_each_channel_as_people_say_it():
    with morning():
        assert web.api_case_of("DEMO-C003")["channel_labels"] == ["email", "PayPal"]
        assert web.api_case_of("DEMO-C002")["channel_labels"] == ["web form"]


def test_a_post_is_checked_before_its_body_is_read_and_a_huge_body_is_refused():
    import socket
    assert web.Handler.timeout == 30                       # a client that stops sending frees its thread
    with morning():
        srv = _server()
        try:
            for headers, want in ((f"Content-Length: {50_000_000}\r\n", b" 413 "),
                                  (f"Content-Length: {500_000}\r\nOrigin: http://evil.example\r\n", b" 403 "),
                                  (f"Content-Length: {500_000}\r\nReferer: http://evil.example/x\r\n", b" 403 ")):
                for path in ("/api/requests", "/rules/add"):
                    sock = socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=5)
                    sock.sendall(f"POST {path} HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n{headers}\r\n".encode())
                    first = sock.recv(200).split(b"\r\n")[0]       # answered without waiting for a body never sent
                    sock.close()
                    assert want in first + b" ", (path, headers, first)
            con = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            con.request("POST", "/api/requests", body=json.dumps(email("x" * 2000, "a@b.c")),
                        headers={"Content-Type": "application/json"})
            assert con.getresponse().status == 201                 # an ordinary body still goes in
        finally:
            srv.shutdown()
            srv.server_close()


def test_an_order_picked_for_another_customer_is_flagged_never_blocked():
    with morning():
        _, out = web.receive("demo", {**email("The tablecloth: still nothing.", "s.durand@work.example"),
                                      "from": {"name": "S. Durand", "email": "s.durand@work.example"}})
        assert web.pick_order(out["case_id"], "LP-90001", "marta") == (200, "DEMO-C001")
        page = web.case_file_page("DEMO-C001", me="marta")
        note = web.case_store("demo").get("DEMO-C001")["timeline"][-1]["text"]
        lena = web.case_file_page("DEMO-C002", me="marta")
    assert "Sophie Durand, <i>customer</i> · sophie.durand@example.com" in page
    assert ("This order belongs to Sophie Durand, not to the sender s.durand@work.example: check before answering."
            in page)
    assert note.startswith("Order LP-90001 picked by Marta: it's Sophie Durand's order, not the sender's.")
    assert "check before answering" not in lena


def test_an_order_picked_for_the_sender_is_not_flagged():
    two = [{"transaction_id": "T1", "email": "ada@example.com", "name": "Ada", "time": "2026-09-01T10:00:00Z",
            "amount": 20.0, "items": [{"item_name": "Art print", "item_quantity": "1"}]},
           {"transaction_id": "T2", "email": "ada@example.com", "name": "Ada", "time": "2026-10-01T10:00:00Z",
            "amount": 36.0, "items": [{"item_name": "Linen shirt", "item_quantity": "1"}]}]
    with morning():
        web.case_store("demo")
        kept = web.shop_orders
        web.shop_orders = lambda src: two
        try:
            _, out = web.receive("demo", email("Can I exchange it for a bigger size?", "ada@example.com"))
            web.pick_order(out["case_id"], "T2", "marta")
            c = web.case_store("demo").get(out["case_id"])
            page = web.case_file_page(out["case_id"], me="marta")
        finally:
            web.shop_orders = kept
    assert c["sorted"]["how"] == "Order T2 picked by Marta." and "check before answering" not in page


def test_a_case_with_no_summary_still_has_a_title():
    with morning():
        web.case_store("demo").update("DEMO-C001", lambda c: c["problem"].update(summary=""))
        page = web.case_file_page("DEMO-C001", me="marta")
    assert "<title>Says it never arrived | Second Look</title>" in page


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
