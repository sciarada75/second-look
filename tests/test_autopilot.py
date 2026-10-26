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


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
