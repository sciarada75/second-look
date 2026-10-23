"""The seller never approves an answer to a situation that no longer exists. Run: python3 tests/test_web.py"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secondlook import web  # noqa: E402


def case(buyer_messages=1, tracking=None):
    return {"dispute": {"messages": [{"posted_by": "BUYER"}] * buyer_messages, "dispute_life_cycle_stage": "INQUIRY",
                        "dispute_amount": {"value": "42.00"}},
            "seller_records": {"tracking": tracking, "ship_to": "Napoli"}}


def saved_review(c):
    web.REVIEWS = Path(tempfile.mkdtemp())
    (web.REVIEWS / "X.json").write_text(json.dumps({"seen": web._seen(c)}))


def test_unchanged_case_keeps_its_review():
    saved_review(case())
    assert web._changes("X", case()) == []


def test_buyer_reply_or_new_tracking_makes_the_review_out_of_date():
    saved_review(case())
    assert web._changes("X", case(buyer_messages=2)) == ["the buyer wrote again"]
    assert web._changes("X", case(tracking={"tracking_number": "T1"})) == ["tracking was added or changed"]


def test_review_without_a_record_of_what_it_saw_is_out_of_date():
    web.REVIEWS = Path(tempfile.mkdtemp())
    (web.REVIEWS / "X.json").write_text("{}")
    assert web._changes("X", case())


def test_rules_are_added_once_and_removed_by_position():
    web.POLICY = Path(tempfile.mkdtemp()) / "policy.json"
    web.POLICY.write_text(json.dumps({"max_auto_refund": 50, "seller_preferences": ["A"]}))
    assert web.add_rule("  Never   promise a date. ") and not web.add_rule("Never promise a date.")
    assert not web.add_rule("   ")
    assert web._policy()["seller_preferences"] == ["A", "Never promise a date."]
    web.remove_rule(0)
    assert web._policy() == {"max_auto_refund": 50, "seller_preferences": ["Never promise a date."]}


def test_a_rule_suggested_from_a_case_changes_nothing_until_accepted():
    tmp = Path(tempfile.mkdtemp())
    web.POLICY, web.SUGGESTED = tmp / "policy.json", tmp / "suggested.json"
    web.POLICY.write_text(json.dumps({"seller_preferences": ["A"]}))
    assert web.suggest_rule("Never promise a date.", "PP-1") and not web.suggest_rule("Never promise a date.")
    assert web._policy()["seller_preferences"] == ["A"]                       # nothing applied yet
    web.settle_suggestion(0, "Never promise a delivery date.")                # accepted, reworded
    assert web._policy()["seller_preferences"] == ["A", "Never promise a delivery date."] and web.suggestions() == []
    web.suggest_rule("Refund everyone.", "PP-2")
    web.settle_suggestion(0, None)                                            # discarded
    assert web._policy()["seller_preferences"] == ["A", "Never promise a delivery date."] and web.suggestions() == []


def test_a_notification_that_fails_never_stops_the_answer():
    import os
    os.environ["SECONDLOOK_NOTIFY_URL"] = "http://127.0.0.1:9/nowhere"   # nothing listens there
    root, web.ROOT = web.ROOT, Path(tempfile.mkdtemp())
    try:
        web.notify("answer.sent", {"dispute_id": "X"})                     # must not raise
        assert "answer.sent X" in (web.ROOT / ".tmp" / "notify.log").read_text()
    finally:
        web.ROOT = root
        del os.environ["SECONDLOOK_NOTIFY_URL"]


# ---------- who approves (teams) ----------

import threading  # noqa: E402
import time  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import secondlook.__main__ as cli  # noqa: E402
from secondlook import team as team_mod  # noqa: E402
from secondlook.demo import DemoPayPal  # noqa: E402
from secondlook.guard import Decision, Judgment  # noqa: E402

TEAM = {"roles": {"Customer care manager": {"refund_up_to": None}, "Customer care agent": {"refund_up_to": 30.0}},
        "people": [{"id": "giulia", "name": "Giulia", "role": "Customer care manager"},
                   {"id": "marta", "name": "Marta", "role": "Customer care agent"}]}


@contextmanager
def approval_bench(action="REFUND", ai="REFUND", stops=(), amount="45.00", the_team=TEAM, partial=None,
                   execute_wait=0.0):
    """A saved review for case X, a fake PayPal that records what it was asked to do, and a team.
    Everything it replaces in `web` (and `secondlook.__main__.execute`) is put back afterwards."""
    patched = {(web, n): getattr(web, n) for n in
               ("REVIEWS", "SUGGESTED", "_case", "_client", "team_for", "assignments_for", "notify")}
    patched[(cli, "execute")] = cli.execute
    tmp = Path(tempfile.mkdtemp())
    c = {"dispute": {"dispute_id": "X", "messages": [{"posted_by": "BUYER"}], "dispute_life_cycle_stage": "INQUIRY",
                     "status": "WAITING_FOR_SELLER_RESPONSE",
                     "dispute_amount": {"value": amount, "currency_code": "EUR"}},
         "seller_records": {"tracking": None, "ship_to": "Napoli"}}
    b = SimpleNamespace(sent=[], drafts=[], events=[], case=c, store=team_mod.Assignments(tmp / "assignments.json"))

    def execute(pp, d, dispute, records):
        time.sleep(execute_wait)
        b.sent.append(d.action)
        b.drafts.append(d.judgment.draft_message)
        return {}
    try:
        web.REVIEWS, web.SUGGESTED = tmp / "reviews", tmp / "suggested.json"
        web._case = lambda did: c
        web._client = lambda did=None: web.MockPayPal(tmp, tmp / "actions.jsonl")
        web.team_for = lambda did: team_mod.of(the_team)
        web.assignments_for = lambda did: b.store
        cli.execute = execute
        web.notify = lambda event, payload: b.events.append((event, payload))
        j = Judgment(ai, 0.9, "why", draft_message="Hello", partial_amount=partial)
        web._save("X", Decision(action, [], j, action != ai, list(stops)), seen=web._seen(c))
        yield b
    finally:
        for (mod, name), value in patched.items():
            setattr(mod, name, value)


def test_over_their_limit_an_agent_hands_off_and_nothing_reaches_paypal():
    with approval_bench() as b:
        code, text = web.approve("X", "REFUND", "Hello", by="marta")
        assert code == 202 and b.sent == [] and "Giulia" in text
        assert b.store.get("X")["to"] == "giulia" and b.store.get("X")["handoff"]["from"] == "marta"
        assert b.events[-1][0] == "case.handed_off"


def test_the_manager_sends_it_and_the_answer_is_signed():
    with approval_bench() as b:
        web.approve("X", "REFUND", "Hello", by="marta")
        code, text = web.approve("X", "REFUND", "Hello", by="giulia")
        assert code == 200 and b.sent == ["REFUND"] and "Giulia" in text
        assert b.events[-1][0] == "answer.sent" and b.events[-1][1]["by"] == "Giulia"
        assert web.api_case("X")["review"]["by"] == "Giulia"
        assert b.store.get("X") == {"to": "giulia", "handoff": None}          # sent: the handoff is done


def test_a_refund_held_back_only_for_its_size_reaches_the_manager_then_paypal():
    with approval_bench(action="ASK_SELLER", ai="REFUND", stops=["cap"], amount="89.00") as b:
        assert web.approve("X", "REFUND", "Hello", by="marta")[0] == 202 and b.sent == []
        assert web.approve("X", "REFUND", "Hello", by="giulia")[0] == 200 and b.sent == ["REFUND"]


def test_held_back_for_trust_nobody_sends_it_from_here():
    with approval_bench(action="ASK_SELLER", ai="REFUND", stops=["cap", "injection"], amount="89.00") as b:
        code, text = web.approve("X", "REFUND", "Hello", by="giulia")
        assert code == 409 and b.sent == []
        assert "held back: hidden instructions in the buyer's message" in text and "cap" not in text
        # Asking for something the AI never said gets the plain answer, not the AI's reasons.
        code, text = web.approve("X", "DEFEND", "Hello", by="giulia")
        assert code == 409 and b.sent == [] and "held back" not in text and "changed since you saw it" in text


def test_in_a_team_an_approval_without_a_name_is_refused():
    with approval_bench(amount="20.00") as b:
        code, _ = web.approve("X", "REFUND", "Hello", by=None)
        assert code == 400 and b.sent == []
        assert web.approve("X", "REFUND", "Hello", by="someone-else")[0] == 400 and b.sent == []


def test_a_solo_seller_needs_no_name():
    with approval_bench(amount="45.00", the_team=None) as b:
        code, text = web.approve("X", "REFUND", "Hello")
        assert code == 200 and b.sent == ["REFUND"] and "by You" not in text   # solo: no signature line


def test_a_big_case_needs_someone_who_covers_the_whole_amount_even_to_defend():
    # "always_ask": the shop wants a person who covers the whole dispute, though a defence moves no money.
    with approval_bench(action="ASK_SELLER", ai="DEFEND", stops=["always_ask"], amount="240.00") as b:
        code, text = web.approve("X", "DEFEND", "Hello", by="marta")
        assert code == 202 and b.sent == [] and "Giulia" in text
        assert b.store.get("X")["to"] == "giulia" and b.store.get("X")["handoff"]["amount"] == 240.0
        assert web.approve("X", "DEFEND", "Hello", by="giulia")[0] == 200 and b.sent == ["DEFEND"]


def test_how_much_a_person_must_cover():
    def dec(ai, stops=(), partial=None):
        return Decision("ASK_SELLER", [], Judgment(ai, 0.9, "why", partial_amount=partial), True, list(stops))
    dispute = {"dispute_amount": {"value": "240.00", "currency_code": "EUR"}}
    assert web.required("DEFEND", dec("DEFEND"), dispute) == 0.0
    assert web.required("PARTIAL_REFUND", dec("PARTIAL_REFUND", partial="20 EUR"), dispute) == 20.0
    assert web.required("REFUND", dec("REFUND", ["cap"]), dispute) == 240.0
    # A big case is the manager's whatever the answer: even a question on it.
    assert web.required("MESSAGE", dec("MESSAGE", ["always_ask"]), dispute) == 240.0
    assert web.required("PARTIAL_REFUND", dec("PARTIAL_REFUND", ["always_ask"], "20 EUR"), dispute) == 240.0


def test_no_drafted_question_when_paypal_does_not_allow_it():
    with approval_bench(action="ASK_SELLER", ai="MESSAGE", stops=["paypal_allowed"]) as b:
        code, text = web.approve("X", "MESSAGE", "Hello", by="marta")
        assert code == 409 and b.sent == [] and "held back: PayPal doesn't allow it at this stage" in text


def test_taking_a_case_keeps_the_colleague_s_handoff():
    with approval_bench() as b:
        web.approve("X", "REFUND", "Hello", by="marta")                    # passed to Giulia, with a note
        assert web.take("X", "giulia") == (200, "Giulia took this case.")
        assert b.store.get("X")["to"] == "giulia" and b.store.get("X")["handoff"]["from"] == "marta"
        assert web.take("X", None)[0] == 400


def test_two_approvals_at_once_send_once():
    with approval_bench(execute_wait=0.2) as b:
        results = []
        threads = [threading.Thread(target=lambda: results.append(web.approve("X", "REFUND", "Hello", by="giulia")))
                   for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert b.sent == ["REFUND"] and [code for code, _ in results] == [200, 200]


def test_the_manager_sends_the_colleague_s_edited_message_when_the_api_sends_none():
    with approval_bench() as b:
        web.approve("X", "REFUND", "Hello, Marta's edit", by="marta")
        assert web.approve("X", "REFUND", None, by="giulia")[0] == 200
        assert b.sent == ["REFUND"] and b.drafts == ["Hello, Marta's edit"]


def test_a_case_that_changed_is_refused_and_not_handed_off():
    with approval_bench() as b:
        b.case["dispute"]["messages"].append({"posted_by": "BUYER"})      # the buyer wrote again
        code, _ = web.approve("X", "REFUND", "Hello", by="marta")
        assert code == 409 and b.sent == [] and b.events == []
        assert b.store.get("X") == {"to": None, "handoff": None}


def test_in_a_team_a_second_approval_after_sending_sends_nothing():
    with approval_bench() as b:
        first = web.approve("X", "REFUND", "Hello", by="giulia")
        assert web.approve("X", "REFUND", "Hello", by="giulia") == first and b.sent == ["REFUND"]


def test_when_nobody_in_the_team_may_approve_it_stays_in_paypal():
    capped = {"roles": {"Customer care manager": {"refund_up_to": 40.0}, "Customer care agent": {"refund_up_to": 30.0}},
              "people": TEAM["people"]}
    with approval_bench(the_team=capped) as b:
        code, text = web.approve("X", "REFUND", "Hello", by="marta")
        assert code == 409 and "Nobody in the team" in text and b.sent == []
        assert b.store.get("X") == {"to": None, "handoff": None}


def test_a_partial_refund_within_the_agent_s_limit_is_sent_by_the_agent():
    with approval_bench(action="PARTIAL_REFUND", ai="PARTIAL_REFUND", partial="20.00 EUR") as b:
        code, text = web.approve("X", "PARTIAL_REFUND", "Hello", by="marta")
        assert code == 200 and b.sent == ["PARTIAL_REFUND"] and "Sent by Marta" in text


def test_the_demo_shop_is_read_once_per_version_of_its_file():
    tmp = Path(tempfile.mkdtemp())
    data = tmp / "shop.json"
    data.write_text(json.dumps({"today": "2026-10-01", "shop": {"name": "A"}}))
    first = DemoPayPal(data, tmp / "log.jsonl")
    assert DemoPayPal(data, tmp / "log.jsonl").raw is first.raw              # not parsed again
    data.write_text(json.dumps({"today": "2026-10-01", "shop": {"name": "Shop B"}}))
    assert DemoPayPal(data, tmp / "log.jsonl").shop["name"] == "Shop B"       # a new file is read again


def test_the_person_picker_shows_only_in_a_team():
    assert web.person_badge(team_mod.of(None), None) == ""
    html = web.person_badge(team_mod.of(TEAM), "marta")
    assert "You are" in html and "Marta" in html and "?as=giulia" in html and "?as=marta" not in html


def test_a_case_page_and_its_posts_take_the_people_of_the_case_s_own_shop():
    assert web.src_of_case("DEMO-001", "live") == "demo"
    assert web.src_of_case("PP-D-1", "demo") == "live"
    practice = next((web.ROOT / "cases").glob("*.json")).stem
    assert web.src_of_case(practice, "demo") == "practice"


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
