"""Earned autonomy: Second Look's AI answers a kind of case on its own once the shop's people approved its advice
unchanged on the last 10 of that kind, and the head of customer care switched it on. It approves through the one
approval path, within its own money limit, and steps back to a person whenever it should. No paid call, no PayPal.
Run: python3 tests/test_autopilot.py"""
import json
import sys
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from secondlook import autopilot, demo as demo_mod, judge, team as team_mod, web  # noqa: E402
from test_inquiry import morning  # noqa: E402  the demo's real data, its state in a temporary folder, no paid call

KIND = "inquiry · not_received · MESSAGE"
TEAM = {"roles": {"Head of customer care": {"refund_up_to": None}, "Customer care assistant": {"refund_up_to": 30.0}},
        "people": [{"id": "giulia", "name": "Giulia", "role": "Head of customer care"},
                   {"id": "marta", "name": "Marta", "role": "Customer care assistant"}],
        "autopilot": {"refund_up_to": 0, "window": 10, "min_confidence": 0.90, "per_day": 20}}
POLICY = json.loads((Path(__file__).resolve().parent.parent / "policy.json").read_text())


def record(seed=None, fp=None):
    return autopilot.Record(Path(tempfile.mkdtemp()) / "autopilot-demo.json", seed=seed,
                            fp=fp or autopilot.fingerprint(POLICY), today="2026-10-26")


def advised(n, by="Marta"):
    return {"case": f"C{n:03d}", "at": f"2026-10-{n:02d}T10:00", "by": by, "as_advised": True}


def test_a_kind_is_ready_after_ten_approvals_as_advised_in_a_row_and_one_change_restarts_it():
    r = record()
    for n in range(1, 10):
        r.decide(KIND, advised(n), 10)
    k = r.view()["kinds"][KIND]
    assert autopilot.streak(k) == 9 and not autopilot.ready(k, 10)
    r.decide(KIND, advised(10), 10)
    assert autopilot.ready(r.view()["kinds"][KIND], 10)
    r.decide(KIND, {"case": "C011", "at": "2026-10-11T10:00", "by": "Marta", "as_advised": False}, 10)
    assert autopilot.streak(r.view()["kinds"][KIND]) == 0          # an edited reply: the count starts again
    assert autopilot.same_words("Hello  Sophie,\n\nIt is there.", "Hello Sophie, It is there.")
    assert not autopilot.same_words("Hello Sophie.", "Hello, Sophie.")


def test_only_the_head_of_customer_care_switches_and_only_a_ready_kind_goes_on():
    t = team_mod.of(TEAM)
    assert autopilot.may_switch(t, "giulia") and not autopilot.may_switch(t, "marta")
    assert not autopilot.may_switch(t, autopilot.AI_ID) and not autopilot.may_switch(t, "nobody")
    assert [p["id"] for p in autopilot.heads(t)] == ["giulia"]
    r = record()
    for n in range(1, 10):
        r.decide(KIND, advised(n), 10)
    assert r.switch(KIND, True, "Giulia", "2026-10-15T09:00", 10) == (409, "Not ready: 9 of the last 10 approved as advised.")
    r.decide(KIND, advised(10), 10)
    assert r.switch(KIND, True, "Giulia", "2026-10-15T09:00", 10)[0] == 200
    assert r.kinds_on("inquiry", "not_received") == [KIND] and r.kinds_on("paypal", "not_received") == []
    assert autopilot.signature(r.view()["kinds"][KIND]) == "Second Look's AI, under Giulia's setting (since 15 Oct)"
    r.decide(KIND, {"case": "C012", "at": "2026-10-16T10:00", "by": "Luca", "as_advised": False}, 10)
    k = r.view()["kinds"][KIND]
    assert not k["on"] and k["off"]["why"] == "Luca changed its advice on C012: the count starts again."


def test_second_look_s_ai_is_never_one_of_the_people_and_approves_within_its_own_limit():
    t = team_mod.of(TEAM)
    assert autopilot.AI_ID not in [p["id"] for p in team_mod.people(t)]
    t2, who = autopilot.as_ai(t, "Second Look's AI, under Giulia's setting (since 15 Oct)")
    assert who == {"id": "second-look-ai", "name": "Second Look's AI, under Giulia's setting (since 15 Oct)",
                   "role": "Second Look's AI"}
    assert team_mod.limit(t2, "second-look-ai") == 0.0 and not team_mod.covers(t2, "second-look-ai", 0.01)
    assert team_mod.handoff_to(t2, 36.0, exclude="second-look-ai")["id"] == "giulia"
    assert team_mod.handoff_to(t2, 10.0, exclude="giulia")["id"] == "marta"       # never a colleague of anyone
    raised, _ = autopilot.as_ai(team_mod.of({**TEAM, "autopilot": {**TEAM["autopilot"], "refund_up_to": 30}}), "x")
    assert team_mod.covers(raised, "second-look-ai", 30.0) and not team_mod.covers(raised, "second-look-ai", 30.01)
    assert team_mod.people(t) == TEAM["people"]                                     # the shop's own team, unchanged
    assert autopilot.settings({"autopilot": {"window": "10", "per_day": True, "min_confidence": 0.95}}) == {
        "refund_up_to": 0.0, "window": 10, "min_confidence": 0.95, "per_day": 20}


def test_a_new_setup_empties_the_record_and_switches_every_kind_off_with_the_reason():
    fp = autopilot.fingerprint(POLICY)
    assert set(fp) == {"instructions", "rules"}
    seed = {"fingerprint": fp, "kinds": {KIND: {"decisions": [advised(n) for n in range(1, 11)], "on": True,
                                                "switched": {"by": "Giulia", "at": "2026-10-15T09:00"}}}}
    r = record(seed)
    assert r.kinds_on("inquiry", "not_received") == [KIND] and r.view()["restarted"] is None
    ruled = autopilot.fingerprint({**POLICY, "seller_preferences": POLICY["seller_preferences"] + ["Be brief."]})
    assert ruled["instructions"] == fp["instructions"] and ruled["rules"] != fp["rules"]
    again = autopilot.Record(r.path, seed=seed, fp=ruled, today="2026-10-22")
    assert again.view()["kinds"] == {} and again.kinds_on("inquiry", "not_received") == []
    assert again.view()["restarted"]["why"] == "Your rules changed on 22 Oct: the record starts again."
    # the guard's own rules are the shop's rules too: defending a parcel delivered to PayPal's address, the markers
    for rule, to in (("defend_if_delivered_to_paypal_address", not POLICY["defend_if_delivered_to_paypal_address"]),
                     ("injection_markers", POLICY["injection_markers"] + ["pay me now"])):
        guarded = autopilot.fingerprint({**POLICY, rule: to})
        assert guarded["instructions"] == fp["instructions"] and guarded["rules"] != fp["rules"], rule
        anew = autopilot.Record(record(seed).path, seed=seed, fp=guarded, today="2026-10-22")
        assert anew.view()["kinds"] == {} and anew.kinds_on("inquiry", "not_received") == [], rule
        assert anew.view()["restarted"]["why"] == "Your rules changed on 22 Oct: the record starts again.", rule
    kept, earned = judge.SYSTEM_INQUIRY, record(seed).path
    try:
        judge.SYSTEM_INQUIRY = kept + "\nBe brief."
        told = autopilot.Record(earned, fp=autopilot.fingerprint(POLICY), today="2026-10-22")
        assert told.view()["restarted"]["why"] == "Second Look's AI's instructions changed on 22 Oct: the record starts again."
    finally:
        judge.SYSTEM_INQUIRY = kept
    assert autopilot.fingerprint({**POLICY, "staff_time": {"hourly_cost": 99}}) == fp   # not a rule the AI follows


def no_record(kinds=None):
    """This bench's record of Second Look's AI in place of the demo's: the morning filed with nothing on (so nothing
    of it is answered), then an empty record, or these kinds."""
    path = web.CASE_FILES["demo"].with_name("autopilot-demo.json")
    for k in ({}, kinds or {}):
        path.write_text(json.dumps({"fingerprint": autopilot.fingerprint(web._policy()), "kinds": k}))
        web.case_store("demo")
    return path


def decisions(kind):
    return [(x["case"], x["by"], x["as_advised"], x.get("why")) for x in
            web.autopilot_store("demo").view()["kinds"].get(kind, {}).get("decisions", [])]


def test_people_s_approvals_of_its_advice_are_its_record_and_nothing_else_is():
    with morning():
        no_record()
        # Sophie's: the review Second Look's AI made (shipped with the demo), approved as it is
        assert web.approve("DEMO-C001", "MESSAGE", None, by="marta", review=web.review_mark("DEMO-C001"))[0] == 200
        assert decisions(KIND) == [("DEMO-C001", "Marta", True, None)]
        # Lena's exchange, its reply edited: a decision on its kind, not as advised
        lena = web._saved("DEMO-C002")[0].judgment.draft_message
        assert web.approve("DEMO-C002", "REPLACE", lena + " Thanks!", by="marta")[0] == 200
        assert decisions("inquiry · wrong_size · REPLACE") == [("DEMO-C002", "Marta", False, "the reply was edited")]
        # a PayPal dispute: its stage and PayPal's reason
        assert web.approve("DEMO-031", "DEFEND", None, by="marta")[0] == 200
        assert decisions("paypal · MERCHANDISE_OR_SERVICE_NOT_RECEIVED · DEFEND") == [("DEMO-031", "Marta", True, None)]


def test_the_rules_baseline_s_reviews_never_count():
    with morning():
        no_record()
        web.run_review("DEMO-C001")                      # no key here: the rules baseline
        assert web.judge_of("DEMO-C001") == "rules"
        assert web.approve("DEMO-C001", "MESSAGE", None, by="marta")[0] == 200
        assert web.autopilot_store("demo").view()["kinds"] == {}


SIGNED = "Second Look's AI, under Giulia's setting (since 15 Oct)"


def test_it_approves_through_the_one_path_signed_never_as_a_person_and_never_given_the_case():
    with morning() as b:
        no_record()
        assert web.approve("DEMO-C001", "MESSAGE", None, by="second-look-ai")[0] == 400       # nobody in the team
        code, text = web.approve("DEMO-C001", "MESSAGE", None, review=web.review_mark("DEMO-C001"), ai_signed=SIGNED)
        assert code == 200 and text.startswith(f"Reply sent by email. Sent by {SIGNED}, ")
        out = web.case_store("demo").get("DEMO-C001")["timeline"][-1]
        assert (out["direction"], out["by"], out["ai"], out["autopilot"]) == ("out", SIGNED, True, True)
        log = [json.loads(x) for x in (b.tmp / "actions-demo.jsonl").read_text().splitlines()]
        assert log[-1]["by"] == SIGNED
        assert [p for ev, p in b.events if ev == "answer.sent"][-1]["by"] == SIGNED
        assert web.assignments_for("DEMO-C001").get("DEMO-C001")["to"] is None                 # still nobody's
        assert web.autopilot_store("demo").view()["kinds"] == {}                               # it can't grade itself


def karim(b, text="I sent the art print back last week and I still have no refund. Order DEMOTX02072."):
    """A request by email from a customer of the demo shop, about a 20 EUR order paid through PayPal."""
    code, out = web.receive("demo", {"channel": "email", "from": {"name": "Karim Ferrari", "email": "karim.f646@example.com"},
                                     "text": text, "source_id": f"test:{len(text)}"})
    assert code == 201 and out["sorted"]["by"] == "rules", out
    return out["case_id"]


def refunds(case):
    return judge.Judgment("REFUND", 0.95, "The return reached the shop.", [], "Your refund is on its way.")


def test_money_over_its_own_limit_passes_to_a_person_and_within_it_goes():
    with morning(ai_key=True, claude=refunds) as b:
        no_record()
        cid = karim(b)
        assert web.run_review(cid).action == "REFUND"
        code, text = web.approve(cid, "REFUND", None, review=web.review_mark(cid), ai_signed=SIGNED)
        assert (code, text) == (202, "Passed to Giulia: refund in full of 20.00 EUR is over your 0.00 EUR limit. Nothing was sent.")
        assert web.case_store("demo").get(cid)["money"] == []
        hand = web.assignments_for(cid).get(cid)
        assert hand["to"] == "giulia" and hand["handoff"]["from"] == "second-look-ai"
    kept = web.team_for
    with morning(ai_key=True, claude=refunds) as b:
        no_record()
        web.team_for = lambda did: team_mod.of({**kept(did), "autopilot": {"refund_up_to": 30}})
        try:
            cid = karim(b)
            web.run_review(cid)
            code, text = web.approve(cid, "REFUND", None, review=web.review_mark(cid), ai_signed=SIGNED)
            assert code == 200 and text.startswith("Refund of 20.00 EUR logged for PayPal's refund API (demo: nothing sent)")
            [m] = web.case_store("demo").get(cid)["money"]
            assert (m["kind"], m["amount"], m["by"]) == ("refund", 20.0, SIGNED)
            assert [r["approved_by"] for r in web.books_rows("demo") if r["case_id"] == cid] == [SIGNED]
        finally:
            web.team_for = kept


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
