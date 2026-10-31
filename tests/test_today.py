"""The morning screen: I see (since yesterday, every channel), I manage (who has what), I know (this month).
Run: python3 tests/test_today.py"""
import json
import sys
import tempfile
import threading
from contextlib import contextmanager
from datetime import date
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secondlook import demo as demo_mod, judge, sort as sort_mod, team as team_mod, today, web  # noqa: E402
# Tests never run local whisper: a call's words are the transcript shipped beside it (26/10).
web.TRANSCRIBE = lambda wav: None
from secondlook.demo import DemoPayPal  # noqa: E402

TODAY = date(2026, 10, 20)
TEAM = {"roles": {"Head of customer care": {"refund_up_to": None}, "Customer care assistant": {"refund_up_to": 30.0}},
        "people": [{"id": "giulia", "name": "Giulia", "role": "Head of customer care"},
                   {"id": "marta", "name": "Marta", "role": "Customer care assistant"}]}


def dispute(did, opened, status="WAITING_FOR_SELLER_RESPONSE", amount="40.00", tx=None, stage="INQUIRY", outcome=None,
            refunded=None):
    d = {"dispute_id": did, "create_time": opened, "status": status, "dispute_life_cycle_stage": stage,
         "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "dispute_amount": {"value": amount, "currency_code": "EUR"},
         "seller_response_due_date": opened[:8] + str(int(opened[8:10]) + 10).zfill(2) + opened[10:],
         "disputed_transactions": [{"seller_transaction_id": tx or f"TX-{did}", "buyer": {"name": f"Buyer {did}"}}],
         "messages": [{"posted_by": "BUYER", "content": f"Where is it? ({did})"}]}
    if outcome:
        d["dispute_outcome"] = {"outcome_code": outcome[0], "outcome_reason": outcome[1]}
        if refunded:
            d["dispute_outcome"]["amount_refunded"] = {"currency_code": "EUR", "value": refunded}
    return d


def case(cid, *entries, status="open", dispute_id=None, order_no=None, money=(), closed_at=None, opened=None):
    tl = [{"at": at, "channel": ch, "direction": way, "text": "…", "by": "Ann" if way == "in" else "Marta", "ai": False}
          for at, ch, way in entries]
    return {"id": cid, "customer": {"name": f"Customer {cid}", "email": f"{cid.lower()}@example.com"},
            "order_no": order_no, "problem": {"kind": "not_received", "summary": f"Summary {cid}"}, "stage": "inquiry",
            "status": status, "outcome": "solved" if status != "open" else None, "dispute_id": dispute_id,
            "sorted": {"by": "rules", "how": ""}, "opened": opened or tl[0]["at"], "timeline": tl, "money": list(money),
            **({"closed_at": closed_at} if closed_at else {})}


def test_since_yesterday_and_this_month_start_at_midnight_and_have_no_end():
    assert today.since(TODAY) == "2026-10-19T00:00" and today.month_start(TODAY) == "2026-10-01T00:00"
    assert today.since(date(2026, 11, 1)) == "2026-10-31T00:00" and today.month_start(date(2026, 11, 1)) == "2026-11-01T00:00"


def test_i_see_one_row_per_problem_every_channel_nearest_paypal_deadline_first():
    cases = [case("C1", ("2026-10-19T08:52", "email", "in")),                        # new email, no dispute
             case("C2", ("2026-10-18T09:00", "email", "in"), dispute_id="D1"),       # old email, its dispute is new
             case("C3", ("2026-10-12T09:00", "form", "in"), ("2026-10-13T09:00", "form", "out"))]  # nothing new
    disputes = [dispute("D1", "2026-10-19T10:30:00Z"), dispute("D2", "2026-10-20T17:50:00Z"),
                dispute("D3", "2026-10-17T10:00:00Z")]
    orders = [{"date": "2026-10-19"}, {"date": "2026-10-20"}, {"date": "2026-10-18"}]
    s = today.came_in(cases, disputes, orders, TODAY, review_of=lambda did: {"by": "ai", "text": f"rec {did}"})
    assert s["counts"] == {"call": 0, "email": 1, "form": 0, "paypal": 2} and s["orders"] == 2
    assert [(r["link"], r["channels"], r["days_left"]) for r in s["rows"]] == [
        ("/c/C2", ["paypal"], 9), ("/d/D2", ["paypal"], 10), ("/c/C1", ["email"], None)]
    assert s["rows"][0]["review"] == {"by": "ai", "text": "rec D1"}          # a case with a dispute: the dispute's review
    assert s["rows"][2]["review"]["text"] == "rec C1"


def test_i_manage_who_has_what_with_roles_and_what_waits_after_a_handoff():
    items = [{"id": "D1", "link": "/d/D1", "who": "Pablo", "summary": "s", "amount": 89.0},
             {"id": "C1", "link": "/c/C1", "who": "Sophie", "summary": "s", "amount": 64.0},
             {"id": "D2", "link": "/d/D2", "who": "Dario", "summary": "s", "amount": 58.0}]
    assigned = {"D1": {"to": "giulia", "handoff": {"from": "marta", "from_name": "Marta", "action": "REFUND"}},
                "D2": {"to": "marta", "handoff": None}}
    mg = today.who_has(items, assigned, team_mod.of(TEAM))
    giulia, marta = mg["people"]
    assert (giulia["name"], giulia["role"], len(giulia["items"]), len(giulia["waiting"])) == ("Giulia", "Head of customer care", 1, 1)
    assert (marta["role"], len(marta["items"]), marta["passed_on"]) == ("Customer care assistant", 1, 1)
    assert [i["id"] for i in mg["unassigned"]] == ["C1"]
    assert mg["handoffs"][0]["from_role"] == "Customer care assistant" and mg["handoffs"][0]["to_name"] == "Giulia"
    solo = today.who_has(items, {}, team_mod.of(None))
    assert solo["solo"] and solo["total"] == 3


def test_i_know_this_month_every_channel_in_money_and_hours():
    cases = [case("C1", ("2026-10-02T09:00", "email", "in"), ("2026-10-02T11:00", "email", "out"), status="closed",
                  order_no="O1", money=[{"kind": "refund", "amount": 30.0, "at": "2026-10-02T11:00"}],
                  closed_at="2026-10-03T09:00"),
             case("C2", ("2026-09-20T09:00", "form", "in"), ("2026-09-21T09:00", "form", "out"), status="closed",
                  closed_at="2026-09-22T09:00"),                                   # last month: not counted
             case("C3", ("2026-10-19T08:52", "email", "in"), order_no="O3"),       # open, nothing out yet
             case("C4", ("2026-10-05T08:00", "email", "in"), dispute_id="D1", order_no="TX-D1")]
    disputes = [dispute("D1", "2026-10-05T10:00:00Z"),
                dispute("D2", "2026-10-06T10:00:00Z", status="RESOLVED", stage="CHARGEBACK",
                        outcome=("RESOLVED_BUYER_FAVOUR", "ITEM_NOT_RECEIVED"), refunded="20.00")]
    orders = [{"date": "2026-10-01", "order_no": "O1", "amount": 30.0}, {"date": "2026-10-10", "order_no": "O3", "amount": 64.0},
              {"date": "2026-09-30", "transaction_id": "TX-D1", "amount": 40.0}]
    k = today.month(cases, disputes, orders, TODAY, {"staff_time": {"hourly_cost": 30, "reply_minutes": 10}},
                    answers=["2026-10-07T10:00", "2026-09-30T10:00"])
    # requests: C1, C3, C4 (its dispute D1 is one request with it) and D2, a PayPal dispute with no case
    assert (k["orders"], k["requests"], k["solved_before_dispute"]) == (2, 4, 1)
    assert k["requests_by_channel"] == {"call": 0, "email": 3, "form": 0, "paypal": 1}
    assert (k["answers"], k["minutes"], k["staff_cost"]) == (2, 20.0, 10.0)        # C1's answer + one PayPal answer
    assert (k["back_cases"], k["back_paypal"], k["back"]) == (30.0, 20.0, 50.0)
    assert k["fees"] == 14.0                                                          # a lost claim's standard fee
    assert k["open_inquiries_most"] == 64.0 and k["open_disputes_most"] == 54.0      # 40 + a 14 EUR fee
    assert k["could_still_cost"] == 118.0


@contextmanager
def morning():
    """The demo shop's real data, its case file, assignments, reviews and logs in a temporary folder, no AI key,
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
        yield store
    finally:
        (web.CASE_FILES, web.OUTBOX_LOGS, web.REVIEWS, web.SUGGESTED, web.assignments_for, web.has_ai_key, web.notify,
         sort_mod.read_with_ai, judge.INQUIRY_BACKENDS["claude"], judge.BACKENDS["claude"], demo_mod.ACTION_LOG) = kept


def test_the_demo_morning_reads_every_channel_against_its_orders():
    with morning():
        v = web.today_view("demo")
        s = v["see"]
        # 3 emails: Sophie's, Pablo's and Margot's (26/10: where is my order, answered by Second Look's AI on its own)
        assert s["since"] == "2026-10-19T00:00" and s["counts"] == {"call": 1, "email": 3, "form": 1, "paypal": 3}
        assert s["orders"] == 141                                # 68 orders on 19 Oct, 73 on 20 Oct: made-up, ~2,000 a month
        assert [r["link"] for r in s["rows"]] == ["/c/DEMO-C003", "/d/DEMO-039", "/d/DEMO-036", "/c/DEMO-C001",
                                                  "/c/DEMO-C002", "/c/DEMO-C004"]
        pablo = s["rows"][0]
        assert pablo["channels"] == ["email", "paypal"] and pablo["decision_id"] == "DEMO-034" and pablo["days_left"] == 19
        assert pablo["review"] == {"by": "ai", "text": "Your call (your limits held back: refund in full)"}
        # Sophie's and Lena's: the reviews Second Look's AI made of them, shipped with the demo (26/10). Sophie's case
        # is Marta's, so Second Look's AI stepped back from it; Margot's it answered on its own.
        assert s["rows"][3]["review"] == {"by": "ai", "text": "Reply only · Second Look's AI stepped back: Marta has this case"}
        assert s["rows"][4]["review"] == {"by": "ai", "text": "Exchange or replace"}
        assert s["rows"][5]["review"] == {"by": None, "text": "Handled by Second Look's AI · reply sent by email"}
        people = {p["name"]: (p["role"], len(p["items"])) for p in v["manage"]["people"]}
        assert people == {"Giulia": ("Head of customer care", 0), "Marta": ("Customer care assistant", 4),
                          "Luca": ("Customer care assistant", 2), "Sara": ("Customer care assistant", 0)}
        # unassigned still 9: Sophie's left it (Marta's), Margot's open case joined it (a person checks it)
        assert len(v["manage"]["unassigned"]) == 9 and v["manage"]["handoffs"] == []
        assert [h["id"] for h in v["autopilot"]["handled"]] == ["DEMO-C004"]
        k = web.numbers_view("demo")["month"]
        # Margot's order (15 Oct) and her request count this month; her answer is nobody's staff time (Second Look's AI)
        assert (k["from"], k["orders"], k["requests"], k["solved_before_dispute"]) == ("2026-10-01T00:00", 1330, 65, 31)
        assert (k["answers"], k["staff_cost"], k["back_cases"], k["back_paypal"], k["fees"]) == (23, 57.74, 160.0, 154.7, 14.0)
        assert k["could_still_cost"] == 1109.0                 # + Margot's open inquiry, 36.00 EUR, refunded in full


def test_what_the_team_does_this_morning_shows_at_once():
    with morning() as store:
        web.run_review("DEMO-C001")                             # the rules baseline: no key here
        row = next(r for r in web.today_view("demo")["see"]["rows"] if r["case_id"] == "DEMO-C001")
        assert row["review"] == {"by": "rules", "text": "Reply only · Second Look's AI stepped back: Marta has this case"}
        assert web.approve("DEMO-C001", "MESSAGE", "It was left with your neighbour.", by="marta")[0] == 200
        assert web.close_case("DEMO-C001", "solved", "marta")[0] == 200
        assert web.case_store("demo").get("DEMO-C001")["closed_at"]          # when it closed, for "this month"
        v = web.today_view("demo")
        row = next(r for r in v["see"]["rows"] if r["case_id"] == "DEMO-C001")
        assert row["review"]["text"] == "Answered: Reply sent by email" and row["status"] == "closed"
        k = web.numbers_view("demo")["month"]
        assert (k["answers"], k["solved_before_dispute"]) == (24, 32)
        code, _ = web.approve("DEMO-034", "REFUND", "You're right: here is your refund.", by="marta")
        assert code == 202                                       # over Marta's 30 EUR: passed to Giulia, nothing sent
        hand = web.today_view("demo")["manage"]["handoffs"]
        assert [(h["id"], h["from_name"], h["from_role"], h["to_name"], h["to_role"]) for h in hand] == [
            ("DEMO-034", "Marta", "Customer care assistant", "Giulia", "Head of customer care")]


def test_a_buyer_s_new_message_on_an_older_dispute_came_in_too():
    old = dispute("D4", "2026-10-10T09:00:00Z")
    old["messages"].append({"posted_by": "BUYER", "content": "Still nothing.", "time_posted": "2026-10-19T12:00:00Z"})
    held = dispute("D5", "2026-10-11T09:00:00Z")
    held["messages"] += [{"posted_by": "BUYER", "content": "Hello?", "time_posted": "2026-10-20T08:00:00Z"},
                         {"posted_by": "SELLER", "content": "We're on it.", "time_posted": "2026-10-20T09:00:00Z"}]
    quiet = dispute("D6", "2026-10-12T09:00:00Z")
    quiet["messages"].append({"posted_by": "SELLER", "content": "Tracking attached.", "time_posted": "2026-10-19T09:00:00Z"})
    cases = [case("C5", ("2026-10-11T08:00", "email", "in"), dispute_id="D5")]
    s = today.came_in(cases, [old, held, quiet], [], TODAY)
    assert s["counts"]["paypal"] == 2                                     # one new buyer message on each
    assert sorted(r["link"] for r in s["rows"]) == ["/c/C5", "/d/D4"]      # a seller's message is not "came in"
    c5 = next(r for r in s["rows"] if r["link"] == "/c/C5")
    assert c5["channels"] == ["paypal"] and c5["first"] == "2026-10-20T08:00"


def test_the_morning_screen_answers_what_needs_me():
    with morning():
        v = web.today_view("demo", "giulia")
        html_ = web.today_page("demo", "giulia")
        free = len(v["manage"]["unassigned"])
        for words in ("Good morning, Giulia.", "Tue 20 Oct · 6 new since yesterday · 141 new orders", "Needs you · 1",
                      "Second Look's AI answered 1 on its own: check it",
                      "Answered · closes on 23 Oct if Margot doesn&#x27;t write", "Looks right",
                      "I&#x27;d have done it differently", "New since yesterday · 6", "✉️ 3 emails", "📝 1 web form",
                      "📞 1 call", "<b>Pablo Martin</b>, <i>customer</i>", "Margot Lefèvre</b>, <i>customer</i>",
                      "19 days left", "no PayPal deadline", "Marta has it", "Your team is on it",
                      "<b>Marta</b>, <i>Customer care assistant</i> · 4", f"not taken yet {free}"):
            assert words in html_, words
        for gone in ("I know", "I manage", "This month (October 2026)", "Export for accounting", "PayPal's high-volume line"):
            assert gone not in html_, gone                                   # the figures live on Numbers now
        nav = html_.split("<nav>")[1].split("</nav>")[0]
        assert '<a href="/today?shop=demo" aria-current="page">Today</a>' in nav and '<a href="/numbers?shop=demo">Numbers</a>' in nav
        marta = web.today_page("demo", "marta")
        assert "Needs you · 4" in marta and f"Not taken yet · {free}" in marta
        assert "Second Look's AI answered" not in marta and "Your team is on it" not in marta
        assert "Nothing needs you" in web.today_page("demo", "sara")
        assert web.approve("DEMO-034", "REFUND", "You're right: here is your refund.", by="marta")[0] == 202
        giulia = web.today_page("demo", "giulia")
        assert "Needs you · 2" in giulia and "passed to you by Marta, <i>Customer care assistant</i>" in giulia


def test_the_morning_screen_over_http_and_as_data():
    with morning():
        srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            con = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            con.request("GET", "/today?shop=demo&as=marta")
            r = con.getresponse()
            assert r.status == 200 and "Good morning, Marta." in r.read().decode()
            con.request("GET", "/api/today?shop=demo")
            r = con.getresponse()
            data = json.loads(r.read())
            assert data["today"] == "2026-10-20" and data["see"]["counts"]["form"] == 1
            assert [h["id"] for h in data["autopilot"]["handled"]] == ["DEMO-C004"]
            con.request("GET", "/api/today?shop=demo&as=giulia")                # what needs this person, as data
            data = json.loads(con.getresponse().read())
            assert [(x["kind"], x.get("id")) for x in data["needs"]] == [("ai", "DEMO-C004")]
            con.request("GET", "/api/numbers?shop=demo")                        # the month's figures moved to Numbers
            assert json.loads(con.getresponse().read())["month"]["requests"] == 65
            con.request("GET", "/today?practice=1")
            r = con.getresponse()
            r.read()
            assert r.status == 303 and r.getheader("Location") == "/?practice=1"
        finally:
            srv.shutdown()


def test_what_a_customer_or_the_ai_wrote_shows_as_text_and_says_whose_words_it_is():
    import copy
    bad = "<script>alert(1)</script>"
    with morning():
        _, o = web.receive("demo", {"channel": "email", "from": {"name": "N " + bad, "email": "who@nowhere.example"},
                                    "subject": "S " + bad, "text": "Hello " + bad})
        _, ai = web.receive("demo", {"channel": "email", "from": {"name": "Ann", "email": "ann@nowhere.example"},
                                     "subject": "Sum " + bad, "text": "Hi"})
        web.case_store("demo").update(ai["case_id"], lambda c: c["sorted"].update(by="ai"))   # as if the AI sorted it
        real = web.shop_disputes

        def with_text(src):
            out = copy.deepcopy(real(src))
            for d in out:
                if d["dispute_id"] == "DEMO-036":
                    d["messages"][0]["content"] = "B " + bad
            return out
        web.shop_disputes = with_text
        try:
            html_ = web.today_page("demo", "giulia")
        finally:
            web.shop_disputes = real
    assert "<script>alert" not in html_.replace("<script>document", "")
    assert "<b>N &lt;script&gt;alert(1)&lt;/script&gt;</b>" in html_
    assert "they wrote: “B &lt;script&gt;alert(1)&lt;/script&gt;”" in html_          # a dispute row: the buyer's words
    assert "they wrote: “S &lt;script&gt;" in html_
    assert "Second Look's AI reads this as: Sum &lt;script&gt;" in html_                 # never as the customer's words


# ---------- review (26/10): one problem once, per-order totals, both sides, currencies, UTC, the PayPal chip ----------

def test_an_inquiry_and_the_dispute_on_its_order_are_one_problem_before_anything_links_them():
    orders = [{"date": "2026-10-10", "transaction_id": "TX7", "amount": 40.0},
              {"date": "2026-10-10", "order_no": "LP-1", "amount": 30.0, "paid_with": "card"}]
    cases = [case("C7", ("2026-10-19T09:00", "email", "in"), order_no="TX7"),
             case("C8", ("2026-10-19T09:30", "email", "in"), order_no="LP-1")]
    disputes = [dispute("D7", "2026-10-19T10:00:00Z", tx="TX7"), dispute("D8", "2026-10-19T11:00:00Z", tx="LP-1")]
    s = today.came_in(cases, disputes, orders, TODAY)
    assert sorted(r["link"] for r in s["rows"]) == ["/c/C7", "/c/C8", "/d/D8"]   # C7 and D7: one row
    c7 = next(r for r in s["rows"] if r["link"] == "/c/C7")
    assert (c7["decision_id"], c7["dispute_id"], c7["channels"]) == ("D7", "D7", ["email", "paypal"])
    assert sorted(i["id"] for i in today.open_items(cases, disputes, orders)) == ["C8", "D7", "D8"]
    k = today.month(cases, disputes, orders, TODAY, None)
    assert k["requests"] == 3 and k["open_inquiries_most"] == 30.0       # C7 is a PayPal dispute now: counted once


def test_what_an_open_inquiry_could_still_cost_is_what_is_left_of_its_order():
    cases = [case("C1", ("2026-10-02T09:00", "email", "in"), status="closed", order_no="O1", closed_at="2026-10-03T09:00",
                  money=[{"kind": "refund", "amount": 20.0, "at": "2026-10-02T10:00"}]),
             case("C2", ("2026-10-19T09:00", "email", "in"), order_no="O1")]
    k = today.month(cases, [], [{"date": "2026-10-01", "order_no": "O1", "amount": 64.0}], TODAY, None)
    assert k["open_inquiries_most"] == 44.0                              # 64, less the 20 the closed case gave back


def test_an_order_given_back_on_both_sides_is_flagged_not_silently_added():
    cases = [case("C1", ("2026-10-02T09:00", "email", "in"), status="closed", order_no="TX9", closed_at="2026-10-03T09:00",
                  money=[{"kind": "refund", "amount": 40.0, "at": "2026-10-02T10:00"}])]
    disputes = [dispute("D9", "2026-10-04T10:00:00Z", status="RESOLVED", tx="TX9",
                        outcome=("RESOLVED_BUYER_FAVOUR", "ITEM_NOT_RECEIVED"), refunded="40.00")]
    k = today.month(cases, disputes, [{"date": "2026-10-01", "transaction_id": "TX9", "amount": 40.0}], TODAY, None)
    assert k["back"] == 80.0 and k["both_sides"] == ["TX9"]
    assert "1 order counted on both sides: check it was paid once" in web.both_sides_note(k)
    k = today.month(cases, [], [{"date": "2026-10-01", "transaction_id": "TX9", "amount": 40.0}], TODAY, None)
    assert k["both_sides"] == [] and "both sides" not in web.both_sides_note(k)
    cases[0]["money"][0]["status"] = "cancelled"                         # a refund a person cancelled never went out
    k = today.month(cases, disputes, [{"date": "2026-10-01", "transaction_id": "TX9", "amount": 40.0}], TODAY, None)
    assert k["both_sides"] == [] and k["back"] == 40.0


def test_rows_carry_their_own_currency():
    orders = [{"date": "2026-10-10", "order_no": "UK-1", "amount": 30.0, "currency": "GBP"}]
    cases = [case("C9", ("2026-10-19T09:00", "email", "in"), order_no="UK-1")]
    s = today.came_in(cases, [dispute("D1", "2026-10-19T10:00:00Z")], orders, TODAY)
    assert {r["link"]: r["currency"] for r in s["rows"]} == {"/c/C9": "GBP", "/d/D1": "EUR"}
    html_ = web.see_block(s, "")
    assert "30.00 GBP" in html_ and "40.00 EUR" in html_
    items = today.open_items(cases, [], orders)
    assert items[0]["currency"] == "GBP"


def test_an_answer_sent_just_after_local_midnight_on_the_1st_is_last_month_in_utc():
    import os
    import time
    kept_tz = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Rome"
    time.tzset()
    try:
        with morning():
            web.REVIEWS.mkdir(parents=True, exist_ok=True)
            (web.REVIEWS / "DEMO-035.json").write_text(json.dumps({"sent": "Sent.", "at": "2026-10-01T01:00"}))
            assert web.sent_answers("demo") == ["2026-09-30T23:00"]           # Rome is UTC+2 in October
    finally:
        if kept_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = kept_tz
        time.tzset()


def test_the_paypal_chip_says_when_it_counts_new_messages_too():
    old = dispute("D4", "2026-10-10T09:00:00Z")
    old["messages"].append({"posted_by": "BUYER", "content": "Still nothing.", "time_posted": "2026-10-19T12:00:00Z"})
    s = today.came_in([], [old, dispute("D2", "2026-10-20T17:50:00Z")], [], TODAY)
    assert s["counts"]["paypal"] == 2 and s["paypal_messages"] == 1
    assert "2 PayPal disputes or new PayPal messages" in web.see_block(s, "")
    s = today.came_in([], [dispute("D2", "2026-10-20T17:50:00Z")], [], TODAY)
    assert s["paypal_messages"] == 0 and "1 PayPal dispute<" in web.see_block(s, "")


def test_like_for_like_windows_and_the_last_eight_weeks():
    assert today.windows(date(2026, 10, 20)) == ((date(2026, 10, 1), date(2026, 10, 20)), (date(2026, 9, 1), date(2026, 9, 20)))
    assert today.windows(date(2026, 10, 31))[1] == (date(2026, 9, 1), date(2026, 9, 30))       # cut at 30 Sep
    assert today.windows(date(2026, 3, 1))[1] == (date(2026, 2, 1), date(2026, 2, 1))
    assert today.windows(date(2026, 10, 20), "week") == ((date(2026, 10, 19), date(2026, 10, 20)),
                                                         (date(2026, 10, 12), date(2026, 10, 13)))
    assert today.windows(date(2026, 10, 19), "week") == ((date(2026, 10, 19), date(2026, 10, 19)),
                                                         (date(2026, 10, 12), date(2026, 10, 12)))
    w = today.weeks(date(2026, 10, 20))
    assert len(w) == 8 and w[0] == (date(2026, 8, 31), date(2026, 9, 6)) and w[-1] == (date(2026, 10, 19), date(2026, 10, 20))


def test_a_period_counts_only_its_own_days_and_this_month_is_the_morning_screen_s_month():
    cases = [case("C1", ("2026-09-05T09:00", "email", "in"), ("2026-09-05T10:00", "email", "out"), status="closed",
                  closed_at="2026-09-06T09:00"),
             case("C2", ("2026-10-02T09:00", "email", "in"), ("2026-10-02T10:00", "email", "out"))]
    cases[1]["timeline"].append({"at": "2026-10-02T11:00", "channel": "email", "direction": "out", "text": "…",
                                 "by": "Second Look's AI", "ai": True, "autopilot": True})
    orders = [{"date": "2026-09-05"}, {"date": "2026-09-25"}, {"date": "2026-10-02"}, {"date": "2026-10-03"}]
    sep = today.period(cases, [], orders, "2026-09-01T00:00", "2026-09-21T00:00", None)
    octo = today.period(cases, [], orders, "2026-10-01T00:00", None, None)
    assert (sep["requests"], sep["solved_before_dispute"], sep["answers"], sep["orders"], sep["ai_answered"]) == (1, 1, 1, 1, 0)
    assert (octo["requests"], octo["solved_before_dispute"], octo["answers"], octo["orders"], octo["ai_answered"]) == (1, 0, 1, 2, 1)
    assert (sep["from"], sep["to"], octo["to"]) == ("2026-09-01T00:00", "2026-09-21T00:00", None)
    m = today.month(cases, [], orders, TODAY, None)
    assert {k: m[k] for k in octo} == octo                     # the morning screen's month is this period, unchanged


def test_needs_you_is_what_is_yours_nearest_deadline_first_then_calls_then_the_head_s_checks():
    def it(i, left):
        return {"id": i, "link": f"/d/{i}", "who": f"W {i}", "summary": "s", "amount": 10.0, "currency": "EUR",
                "days_left": left}
    items = [it("D1", 9), it("C1", None), it("D2", 2), it("D3", 1)]
    assigned = {"D1": {"to": "marta"}, "C1": {"to": "marta"}, "D2": {"to": "marta", "handoff": {"from": "giulia"}},
                "D3": {"to": "giulia"}}
    ai = [{"id": "DEMO-C9", "kind": "inquiry · not_received · MESSAGE"}]
    n = today.needs_you("marta", False, items, assigned, TEAM, handled=ai, failed=["a.wav"])
    assert [(x["kind"], x.get("id")) for x in n] == [("case", "D2"), ("case", "D1"), ("case", "C1"), ("calls", None)]
    assert (n[0]["from_name"], n[0]["from_role"]) == ("Giulia", "Head of customer care") and n[1]["from_name"] is None
    near = {"counts": True, "high_volume": False, "claims_to_threshold": 2, "claims": 30, "sales": 2100, "ratio": 0.014}
    g = today.needs_you("giulia", True, items, assigned, TEAM, handled=ai, hv=near)
    assert [x["kind"] for x in g] == ["case", "ai", "line"] and g[1]["ai_kind"] == "inquiry · not_received · MESSAGE"
    far = {**near, "claims_to_threshold": 9}
    assert [x["kind"] for x in today.needs_you("giulia", True, items, assigned, TEAM, hv=far)] == ["case"]
    assert [x["id"] for x in today.needs_you(None, True, items, {}, {"solo": True})] == ["D3", "D2", "D1", "C1"]
    assert today.needs_you("sara", False, items, assigned, TEAM) == []


def test_the_demo_morning_needs_giulia_for_one_check_and_marta_for_her_four_cases():
    with morning():
        g = web.today_view("demo", "giulia")
        assert [(x["kind"], x.get("id")) for x in g["needs"]] == [("ai", "DEMO-C004")] and g["head"]
        assert g["needs"][0]["closes"] == "Answered · closes on 23 Oct if Margot doesn't write"
        m = web.today_view("demo", "marta")
        assert [x["kind"] for x in m["needs"]] == ["case"] * 4 and not m["head"]
        lefts = [x["days_left"] for x in m["needs"]]
        assert lefts == sorted(lefts, key=lambda d: (d is None, d or 0))
        assert next(r for r in g["see"]["rows"] if r["case_id"] == "DEMO-C001")["has"] == "Marta"
        assert next(r for r in g["see"]["rows"] if r["case_id"] == "DEMO-C004")["has"] is None
        assert "know" not in g


def test_an_answer_nobody_checked_stays_in_needs_you_until_someone_does():
    from test_closing import on_day
    with morning():
        web.case_store("demo")
        with on_day(date(2026, 10, 22)):                                      # two days on: no longer "since yesterday"
            g = web.today_view("demo", "giulia")
            assert ("ai", "DEMO-C004") in [(x["kind"], x.get("id")) for x in g["needs"]]
            assert g["autopilot"]["handled"] == []                            # the since-yesterday list keeps its window


def test_a_case_that_is_also_an_ai_check_shows_once_as_the_check():
    def it(i, left):
        return {"id": i, "link": f"/c/{i}", "who": f"W {i}", "summary": "s", "amount": 10.0, "currency": "EUR",
                "days_left": left}
    items = [it("C1", None), it("C2", None)]
    ai = [{"id": "C1", "kind": "inquiry · not_received · MESSAGE"}]
    g = today.needs_you("giulia", True, items, {"C1": {"to": "giulia"}, "C2": {"to": "giulia"}}, TEAM, handled=ai)
    assert [(x["kind"], x.get("id")) for x in g] == [("case", "C2"), ("ai", "C1")]
    solo = today.needs_you(None, True, items, {}, {"solo": True}, handled=ai)
    assert [(x["kind"], x.get("id")) for x in solo] == [("case", "C2"), ("ai", "C1")]


def test_a_seller_on_their_own_with_nothing_to_do_has_no_team_to_mention():
    html_ = web.needs_block([], "", None, "live", solo=True)
    assert "Nothing needs you" in html_ and "Your team has the rest" not in html_
    assert "Your team has the rest." in web.needs_block([], "", "giulia", "demo")


def test_a_row_second_look_s_ai_answered_on_its_own_raises_no_not_taken_yet_alarm():
    with morning():
        listing = web.today_page("demo", "giulia").split('<ol class="see">')[1].split("</ol>")[0]
        row = lambda cid: next(li for li in listing.split("<li>") if f'href="/c/{cid}' in li)  # noqa: E731
        assert "Handled by Second Look&#x27;s AI" in row("DEMO-C004") and 'class="has' not in row("DEMO-C004")
        assert "not taken yet" in row("DEMO-C002")                            # Lena's: nobody has it, nobody answered


def test_needs_you_holds_only_what_is_your_move_and_the_rest_waits_in_its_own_bucket():
    with morning():
        v = web.today_view("demo", "giulia")
        assert all(n["state"]["state"] == "your_move" for n in v["needs"] if n["kind"] == "case")
        assert [x["id"] for x in v["waiting"]["waiting_customer"]] == ["DEMO-C004"]    # Margot: the AI answered
        assert web.approve("DEMO-039", "REFUND", "Your refund is on its way.", by="giulia")[0] == 200
        v = web.today_view("demo", "giulia")
        assert [x["id"] for x in v["waiting"]["waiting_paypal"]] == ["DEMO-039"]
        assert "DEMO-039" not in [n.get("id") for n in v["needs"]]
        assert v["handled"]["cases"] == 1 and v["handled"]["minutes"] == 6


def test_a_case_closed_today_is_done_and_one_closed_before_is_not():
    cases = [case("C1", ("2026-10-19T08:00", "email", "in"), status="closed", closed_at="2026-10-20T09:00"),
             case("C2", ("2026-10-10T08:00", "email", "in"), status="closed", closed_at="2026-10-12T09:00")]
    done = today.closed_today(cases, [], TODAY, keep=lambda i: True)
    assert [x["id"] for x in done] == ["C1"] and done[0]["link"] == "/c/C1"
    assert today.closed_today(cases, [], TODAY, keep=lambda i: False) == []


def test_the_api_says_each_case_s_state():
    with morning():
        s = web.api_case_of("DEMO-C004")["state"]
        assert s["state"] == "waiting_customer" and s["until"] == "2026-10-23"
        assert web.api_case("DEMO-039")["state"]["state"] == "your_move"


def test_the_two_case_endpoints_agree_and_a_shop_inquiry_is_not_a_paypal_dispute():
    with morning():
        s = web.api_case("DEMO-C004")["state"]
        assert s == web.api_case_of("DEMO-C004")["state"]
        assert s["state"] == "waiting_customer" and s["until"] == "2026-10-23" and s["paypal"] is False
        assert web.approve("DEMO-039", "REFUND", "Your refund is on its way.", by="giulia")[0] == 200
        assert web.api_case("DEMO-034")["state"] == web.api_case_of("DEMO-C003")["state"]    # Pablo: one case, one dispute
        assert web.approve("DEMO-034", "REFUND", "Your refund is on its way.", by="giulia")[0] in (200, 202)
        assert web.api_case("DEMO-034")["state"] == web.api_case_of("DEMO-C003")["state"]


def test_handled_today_counts_the_person_s_own_sends_not_the_ai_s_nor_a_colleague_s():
    with morning():
        assert web.today_view("demo", "giulia")["handled"]["cases"] == 0       # Margot's answer is the AI's
        assert web.approve("DEMO-039", "REFUND", "Your refund is on its way.", by="marta")[0] == 200
        assert web.today_view("demo", "giulia")["handled"]["cases"] == 0
        assert web.today_view("demo", "marta")["handled"]["cases"] == 1


def test_a_view_of_today_does_not_look_for_a_case_file_per_dispute():
    with morning():
        kept = web.find_case_of_dispute
        def no_lookup(did):
            raise AssertionError("case file re-read for " + did)
        web.find_case_of_dispute = no_lookup
        try:
            web.today_view("demo", "giulia")
        finally:
            web.find_case_of_dispute = kept


def test_after_a_refund_today_says_so_and_the_demo_s_paypal_closes_it_labelled_simulated():
    with morning():
        web.approve("DEMO-039", "REFUND", "Your refund is on its way.", by="giulia")
        page = web.today_page("demo", "giulia", done="DEMO-039")
        assert "✓ Pablo García:" in page and "Now: Done" in page                          # the toast
        assert "Done · 1" in page and "demo: simulated" in page
        assert "Waiting for the customer · 1" in page and "closes itself on 23 Oct" in page   # Margot
        assert "Today you handled 1 case, about 6 min." in page
        assert web.today_page("demo", "sara").count('class="bucket') == 0                 # nothing of hers waits


def test_a_case_waiting_for_the_customer_raises_no_not_taken_yet_alarm():
    with morning():
        listing = web.today_page("demo", "giulia").split('<ol class="see">')[1].split("</ol>")[0]
        rows = [li for li in listing.split("<li>") if "DEMO-C004" in li]    # DEMO-041/042 are not in the see list; C004 waits for the customer
        assert rows and all("not taken yet" not in li for li in rows)


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
