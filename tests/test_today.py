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
        assert s["since"] == "2026-10-19T00:00" and s["counts"] == {"call": 0, "email": 2, "form": 1, "paypal": 3}
        assert s["orders"] == 141                                # 68 orders on 19 Oct, 73 on 20 Oct: made-up, ~2,000 a month
        assert [r["link"] for r in s["rows"]] == ["/c/DEMO-C003", "/d/DEMO-039", "/d/DEMO-036", "/c/DEMO-C001", "/c/DEMO-C002"]
        pablo = s["rows"][0]
        assert pablo["channels"] == ["email", "paypal"] and pablo["decision_id"] == "DEMO-034" and pablo["days_left"] == 19
        assert pablo["review"] == {"by": "ai", "text": "Your call (your limits held back: refund in full)"}
        assert s["rows"][3]["review"] == {"by": None, "text": "Not reviewed yet"}
        people = {p["name"]: (p["role"], len(p["items"])) for p in v["manage"]["people"]}
        assert people == {"Giulia": ("Head of customer care", 0), "Marta": ("Customer care assistant", 3),
                          "Luca": ("Customer care assistant", 2), "Sara": ("Customer care assistant", 0)}
        assert len(v["manage"]["unassigned"]) == 9 and v["manage"]["handoffs"] == []
        k = v["know"]
        assert (k["from"], k["orders"], k["requests"], k["solved_before_dispute"]) == ("2026-10-01T00:00", 1329, 64, 31)
        assert (k["answers"], k["staff_cost"], k["back_cases"], k["back_paypal"], k["fees"]) == (23, 57.5, 160.0, 154.7, 14.0)
        assert k["could_still_cost"] == 1073.0


def test_what_the_team_does_this_morning_shows_at_once():
    with morning() as store:
        web.run_review("DEMO-C001")                             # the rules baseline: no key here
        row = next(r for r in web.today_view("demo")["see"]["rows"] if r["case_id"] == "DEMO-C001")
        assert row["review"] == {"by": "rules", "text": "Reply only"}
        assert web.approve("DEMO-C001", "MESSAGE", "It was left with your neighbour.", by="marta")[0] == 200
        assert web.close_case("DEMO-C001", "solved", "marta")[0] == 200
        assert web.case_store("demo").get("DEMO-C001")["closed_at"]          # when it closed, for "this month"
        v = web.today_view("demo")
        row = next(r for r in v["see"]["rows"] if r["case_id"] == "DEMO-C001")
        assert row["review"]["text"] == "Answered: Reply sent by email" and row["status"] == "closed"
        assert (v["know"]["answers"], v["know"]["solved_before_dispute"]) == (24, 32)
        code, _ = web.approve("DEMO-034", "REFUND", "You're right: here is your refund.", by="marta")
        assert code == 202                                       # over Marta's 30 EUR: passed to Giulia, nothing sent
        hand = web.today_view("demo")["manage"]["handoffs"]
        assert [(h["id"], h["from_name"], h["from_role"], h["to_name"], h["to_role"]) for h in hand] == [
            ("DEMO-034", "Marta", "Customer care assistant", "Giulia", "Head of customer care")]


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
