"""One customer, one order, one problem: every channel joins the same case. Run: python3 tests/test_cases.py"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secondlook import cases  # noqa: E402


def store():
    return cases.CaseStore(Path(tempfile.mkdtemp()) / "cases.json", prefix="DEMO-")


def request(text="My tablecloth hasn't arrived.", channel="email", time="2026-10-19T08:52:00Z", source_id=None,
            email="sophie.durand@example.com"):
    return {"channel": channel, "from": {"name": "Sophie Durand", "email": email}, "time": time,
            "subject": "Tablecloth", "text": text, "source_id": source_id}


SORTED = {"settled": True, "by": "rules", "customer": {"name": "Sophie Durand", "email": "sophie.durand@example.com"},
          "order_no": "LP-90001", "kind": "not_received", "summary": "Tablecloth",
          "how": "Sorted by Second Look's rules: the message quotes order LP-90001."}
DISPUTE = {"dispute_id": "DEMO-034", "status": "WAITING_FOR_SELLER_RESPONSE", "dispute_life_cycle_stage": "INQUIRY",
           "reason": "CREDIT_NOT_PROCESSED", "create_time": "2026-10-19T10:30:00Z",
           "disputed_transactions": [{"seller_transaction_id": "DEMOTX01828"}],
           "messages": [{"posted_by": "BUYER", "content": "Still no refund.", "time_posted": "2026-10-19T10:30:00Z"}]}


def test_a_second_request_about_the_same_order_joins_the_open_case():
    s = store()
    first, how = s.file(request(), SORTED)
    assert how == "opened" and first["id"] == "DEMO-C001" and first["stage"] == "inquiry"
    again, how = s.file(request("Any news?", channel="form", time="2026-10-19T12:00:00Z"), SORTED)
    assert how == "joined" and again["id"] == "DEMO-C001"
    assert [x["channel"] for x in s.get("DEMO-C001")["timeline"]] == ["email", "form"]
    other, how = s.file(request("Another order", time="2026-10-19T13:00:00Z"), {**SORTED, "order_no": "LP-90009"})
    assert how == "opened" and other["id"] == "DEMO-C002"     # same customer, another order: another case


def test_the_same_request_sent_twice_is_filed_once():
    s = store()
    a, _ = s.file(request(source_id="ticketbook:2101"), SORTED)
    b, how = s.file(request(source_id="ticketbook:2101"), SORTED)
    assert how == "already_received" and b["id"] == a["id"] and len(s.get(a["id"])["timeline"]) == 1


def test_an_email_about_an_order_with_a_paypal_dispute_joins_the_dispute_s_case():
    s = store()
    pablo = {**SORTED, "customer": {"name": "Pablo Martin", "email": "pablo.m576@example.com"}, "order_no": "DEMOTX01828",
             "kind": "refund_missing"}
    c, how = s.file(request("I still have no refund.", email="pablo.m576@example.com"), pablo, dispute=DISPUTE)
    assert how == "opened" and c["dispute_id"] == "DEMO-034" and c["stage"] == "paypal_dispute"
    tl = cases.timeline(s.get(c["id"]), DISPUTE)
    assert [(x["channel"], x["direction"]) for x in tl] == [("email", "in"), ("paypal", "note"), ("paypal", "in")]
    assert cases.channels(s.get(c["id"]), DISPUTE) == ["email", "paypal"]
    assert s.by_dispute("DEMO-034")["id"] == c["id"]


def test_a_paypal_dispute_opened_later_on_the_order_joins_the_open_case():
    s = store()
    c, _ = s.file(request("I still have no refund.", email="pablo.m576@example.com"),
                  {**SORTED, "order_no": "DEMOTX01828", "customer": {"name": "Pablo", "email": "pablo.m576@example.com"}})
    orders = {"DEMOTX01828": {"order_no": "DEMOTX01828", "transaction_id": "DEMOTX01828"}}
    assert s.link_disputes([DISPUTE], orders) == 1 and s.get(c["id"])["stage"] == "paypal_dispute"
    claim = {**DISPUTE, "dispute_life_cycle_stage": "CHARGEBACK"}
    assert s.link_disputes([claim], orders) == 1 and s.get(c["id"])["stage"] == "paypal_claim"
    before = s.path.stat().st_mtime_ns
    assert s.link_disputes([claim], orders) == 0 and s.path.stat().st_mtime_ns == before   # nothing new: no write


def test_an_unsorted_request_never_joins_and_a_person_picks_its_order():
    s = store()
    known, _ = s.file(request(), SORTED)
    loose = {"settled": False, "by": None, "customer": None, "order_no": None, "kind": "not_received", "summary": "x",
             "how": "The sender's address is on none of the shop's orders: a person picks the order."}
    stray, how = s.file(request("From my work address: the tablecloth?", email="s.durand@work.example",
                                time="2026-10-19T09:30:00Z", source_id="ticketbook:2200"), loose)
    assert how == "opened" and stray["id"] != known["id"] and stray["sorted"]["by"] is None
    order = {"order_no": "LP-90001", "name": "Sophie Durand", "email": "sophie.durand@example.com"}
    into = s.pick_order(stray["id"], order, by="Marta")
    assert into == known["id"] and s.get(stray["id"]) is None
    assert len(s.get(known["id"])["timeline"]) == 3 and s.by_source("ticketbook:2200") == known["id"]
    q, _ = s.file(request("Do you ship to Norway?", email="nobody@example.com", time="2026-10-19T11:00:00Z"), loose)
    assert s.pick_order(q["id"], None, by="Marta") == q["id"] and s.get(q["id"])["problem"]["kind"] == "question"
    try:
        s.pick_order(q["id"], None, by="Marta")
        assert False, "a question is not marked a question again"
    except ValueError:
        pass
    assert s.pick_order(q["id"], order, by="Marta") == known["id"]   # it was about her order after all (review 25/10)
    try:
        s.pick_order(known["id"], order, by="Marta")
        assert False, "a case settled on an order is not picked again"
    except ValueError:
        pass


def test_cost_so_far_is_contacts_and_estimated_staff_time():
    s = store()
    c, _ = s.file(request(), SORTED)
    s.add(c["id"], cases.entry("2026-10-19T09:10", "email", "out", "It was left with your neighbour.", "Marta"))
    s.update(c["id"], lambda x: x["money"].append({"kind": "refund", "amount": 20.0}))
    k = cases.costs_so_far(s.get(c["id"]), None, {"staff_time": {"hourly_cost": 30, "reply_minutes": 10}})
    assert (k["contacts"], k["replies"], k["minutes"], k["staff_cost"], k["money_moved"], k["fees"]) == (2, 1, 10, 5.0, 20.0, 0)
    assert k["estimated"] is True
    d = cases.costs_so_far(s.get(c["id"]), None, {"staff_time": {"hourly_cost": "lots", "reply_minutes": -1}})
    assert (d["hourly_cost"], d["reply_minutes"], d["staff_cost"]) == (25.0, 6, 2.5)   # bad numbers: the defaults


def test_case_ids_are_told_apart_from_paypal_s():
    assert cases.is_case_id("DEMO-C001") and cases.is_case_id("C014")
    assert not cases.is_case_id("DEMO-034") and not cases.is_case_id("PP-D-001") and not cases.is_case_id(None)

# ---------- review fixes (25/10) ----------

def test_a_follow_up_joins_the_customer_s_one_unsorted_case():
    s = store()
    ada = {"name": "Ada Rossi", "email": "ada.r@example.com"}
    loose = {"settled": False, "by": None, "customer": ada, "order_no": None, "kind": "not_as_described",
             "summary": "x", "how": "Ada Rossi has 3 orders and the message doesn't say which one."}
    first, _ = s.file(request("Something arrived damaged.", email="ada.r@example.com"), loose)
    news = {"settled": True, "by": "rules", "customer": ada, "order_no": None, "kind": "question", "summary": "Any news?",
            "how": "Sorted by Second Look's rules: the sender's address is Ada Rossi's; a question, so no order is needed."}
    again, how = s.file(request("Any news?", email=" Ada.R@example.com", time="2026-10-19T12:00:00Z"), news)
    assert how == "joined" and again["id"] == first["id"] and len(s.all()) == 1
    assert s.get(first["id"])["sorted"]["by"] is None                        # still a person's call
    s.file(request("Another thing broke.", email="ada.r@example.com", time="2026-10-19T13:00:00Z"), loose)
    _, how = s.file(request("Any news?", email="ada.r@example.com", time="2026-10-19T14:00:00Z"), news)
    assert how == "opened"                                                    # two unsorted cases: which one is unclear


def test_a_dispute_already_on_a_case_is_never_linked_to_another_and_open_cases_come_first():
    s = store()
    pablo = {**SORTED, "order_no": "DEMOTX01828", "customer": {"name": "Pablo", "email": "pablo.m576@example.com"}}
    a, _ = s.file(request("No refund.", email="pablo.m576@example.com"), pablo, dispute=DISPUTE)
    b, _ = s.file(request("No refund, from my other address.", email="p.martin@example.com",
                          time="2026-10-19T09:00:00Z"),
                  {**pablo, "customer": {"name": "Pablo", "email": "p.martin@example.com"}})
    orders = {"DEMOTX01828": {"order_no": "DEMOTX01828", "transaction_id": "DEMOTX01828"}}
    assert s.link_disputes([DISPUTE], orders) == 0 and s.get(b["id"])["dispute_id"] is None
    s.update(a["id"], lambda c: c.update(status="closed"))
    s.update(b["id"], lambda c: c.update(dispute_id="DEMO-034", stage="paypal_dispute"))
    c, how = s.file(request("Still nothing.", email="pablo.m576@example.com", time="2026-10-19T15:00:00Z"), pablo,
                    dispute=DISPUTE)
    assert how == "joined" and c["id"] == b["id"]                            # the open case, not the closed one
    assert s.by_dispute("DEMO-034")["id"] == b["id"]


def test_a_request_about_an_order_whose_case_is_closed_opens_a_new_case_that_names_the_earlier_one():
    s = store()
    a, _ = s.file(request(), SORTED)
    s.update(a["id"], lambda c: c.update(status="closed", outcome="solved"))
    b, how = s.file(request("It's still not here.", time="2026-10-21T09:00:00Z"), SORTED)
    assert how == "opened" and b["id"] != a["id"] and b["earlier_case"] == a["id"]
    assert s.get(a["id"])["later_cases"] == [b["id"]] and len(s.get(a["id"])["timeline"]) == 1   # untouched
    c, how = s.file(request("And now?", time="2026-10-22T09:00:00Z"), SORTED)
    assert how == "joined" and c["id"] == b["id"]                              # the open one is joined, as ever
    # a closed case holding a PayPal dispute is never joined either: a new case, naming it
    d, _ = s.file(request("No refund.", email="pablo.m576@example.com"),
                  {**SORTED, "order_no": "DEMOTX01828", "customer": {"name": "Pablo", "email": "pablo.m576@example.com"}},
                  dispute=DISPUTE)
    s.update(d["id"], lambda x: x.update(status="closed", outcome="refunded"))
    e2, how = s.file(request("Again.", email="pablo.m576@example.com", time="2026-10-23T09:00:00Z"),
                     {**SORTED, "order_no": "DEMOTX01828", "customer": {"name": "Pablo", "email": "pablo.m576@example.com"}},
                     dispute=DISPUTE)
    assert how == "opened" and e2["id"] != d["id"] and e2["earlier_case"] == d["id"]


def test_a_case_closes_with_paypal_s_outcome_when_paypal_resolves_its_dispute():
    s = store()
    c, _ = s.file(request("No refund.", email="pablo.m576@example.com"),
                  {**SORTED, "order_no": "DEMOTX01828", "customer": {"name": "Pablo", "email": "pablo.m576@example.com"}},
                  dispute=DISPUTE)
    orders = {"DEMOTX01828": {"order_no": "DEMOTX01828", "transaction_id": "DEMOTX01828"}}
    for code, reason, key in (("RESOLVED_SELLER_FAVOUR", "", "won"), ("CANCELED_BY_BUYER", "", "withdrew"),
                              ("RESOLVED_BUYER_FAVOUR", "", "refunded")):
        t = store()
        x, _ = t.file(request("No refund.", email="pablo.m576@example.com"),
                      {**SORTED, "order_no": "DEMOTX01828", "customer": {"name": "Pablo", "email": "pablo.m576@example.com"}},
                      dispute=DISPUTE)
        done = {**DISPUTE, "status": "RESOLVED", "dispute_outcome": {"outcome_code": code, "outcome_reason": reason}}
        assert t.link_disputes([done], orders) == 1
        y = t.get(x["id"])
        assert (y["status"], y["outcome"], y["closed_by"]) == ("closed", key, "PayPal"), code
        note = y["timeline"][-1]
        assert (note["direction"], note["by"], note["channel"]) == ("note", "PayPal", "paypal")
        assert note["text"] == f"Closed: PayPal resolved DEMO-034: {cases.OUTCOME_SAYS[key]}."
        assert t.link_disputes([done], orders) == 0                                # once: no second note, no write
    assert s.link_disputes([DISPUTE], orders) == 0 and s.get(c["id"])["status"] == "open"   # still open: nothing


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
