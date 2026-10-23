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
    web.ROOT = Path(tempfile.mkdtemp())
    web.notify("answer.sent", {"dispute_id": "X"})                         # must not raise
    assert "answer.sent X" in (web.ROOT / ".tmp" / "notify.log").read_text()
    del os.environ["SECONDLOOK_NOTIFY_URL"]


# ---------- who approves (teams) ----------
# The helper below replaces module attributes of `web` (and `secondlook.__main__.execute`) for good:
# keep these tests after the ones above, which must run against the real functions.

from secondlook import team as team_mod  # noqa: E402
from secondlook.guard import Decision, Judgment  # noqa: E402

TEAM = {"roles": {"Customer care manager": {"refund_up_to": None}, "Customer care agent": {"refund_up_to": 30.0}},
        "people": [{"id": "giulia", "name": "Giulia", "role": "Customer care manager"},
                   {"id": "marta", "name": "Marta", "role": "Customer care agent"}]}


def approval_bench(action="REFUND", ai="REFUND", stops=(), amount="45.00", the_team=TEAM):
    """A saved review for case X, a fake PayPal that records what it was asked to do, and a team."""
    import secondlook.__main__ as cli
    tmp = Path(tempfile.mkdtemp())
    c = {"dispute": {"dispute_id": "X", "messages": [{"posted_by": "BUYER"}], "dispute_life_cycle_stage": "INQUIRY",
                     "status": "WAITING_FOR_SELLER_RESPONSE",
                     "dispute_amount": {"value": amount, "currency_code": "EUR"}},
         "seller_records": {"tracking": None, "ship_to": "Napoli"}}
    web.REVIEWS, web.SUGGESTED = tmp / "reviews", tmp / "suggested.json"
    web._case = lambda did: c
    web._client = lambda did=None: web.MockPayPal(tmp, tmp / "actions.jsonl")
    web.team_for = lambda did: team_mod.of(the_team)
    store = team_mod.Assignments(tmp / "assignments.json")
    web.assignments_for = lambda did: store
    sent, events = [], []
    cli.execute = lambda pp, d, dispute, records: sent.append(d.action) or {}
    web.notify = lambda event, payload: events.append((event, payload))
    web._save("X", Decision(action, [], Judgment(ai, 0.9, "why", draft_message="Hello"), action != ai, list(stops)),
              seen=web._seen(c))
    return sent, events, store


def test_over_their_limit_an_agent_hands_off_and_nothing_reaches_paypal():
    sent, events, store = approval_bench()
    code, text = web.approve("X", "REFUND", "Hello", by="marta")
    assert code == 202 and sent == [] and "Giulia" in text
    assert store.get("X")["to"] == "giulia" and store.get("X")["handoff"]["from"] == "marta"
    assert events[-1][0] == "case.handed_off"


def test_the_manager_sends_it_and_the_answer_is_signed():
    sent, events, store = approval_bench()
    web.approve("X", "REFUND", "Hello", by="marta")
    code, text = web.approve("X", "REFUND", "Hello", by="giulia")
    assert code == 200 and sent == ["REFUND"] and "Giulia" in text
    assert events[-1][0] == "answer.sent" and events[-1][1]["by"] == "Giulia"
    assert web.api_case("X")["review"]["by"] == "Giulia"
    assert store.get("X") == {"to": "giulia", "handoff": None}          # sent: the handoff is done


def test_a_refund_held_back_only_for_its_size_reaches_the_manager_then_paypal():
    sent, _, store = approval_bench(action="ASK_SELLER", ai="REFUND", stops=["cap"], amount="89.00")
    assert web.approve("X", "REFUND", "Hello", by="marta")[0] == 202 and sent == []
    assert web.approve("X", "REFUND", "Hello", by="giulia")[0] == 200 and sent == ["REFUND"]


def test_held_back_for_trust_nobody_sends_it_from_here():
    sent, _, _ = approval_bench(action="ASK_SELLER", ai="REFUND", stops=["cap", "injection"], amount="89.00")
    code, text = web.approve("X", "REFUND", "Hello", by="giulia")
    assert code == 409 and sent == []
    assert "held back for trust: hidden instructions in the buyer's message" in text and "cap" not in text


def test_in_a_team_an_approval_without_a_name_is_refused():
    sent, _, _ = approval_bench(amount="20.00")
    code, _ = web.approve("X", "REFUND", "Hello", by=None)
    assert code == 400 and sent == []
    assert web.approve("X", "REFUND", "Hello", by="someone-else")[0] == 400 and sent == []


def test_a_solo_seller_needs_no_name():
    sent, _, _ = approval_bench(amount="45.00", the_team=None)
    code, text = web.approve("X", "REFUND", "Hello")
    assert code == 200 and sent == ["REFUND"] and "by You" not in text   # solo: no signature line


def test_a_big_case_needs_someone_who_covers_the_whole_amount_even_to_defend():
    # "always_ask": the shop wants a person who covers the whole dispute, though a defence moves no money.
    sent, _, store = approval_bench(action="ASK_SELLER", ai="DEFEND", stops=["always_ask"], amount="240.00")
    code, text = web.approve("X", "DEFEND", "Hello", by="marta")
    assert code == 202 and sent == [] and "Giulia" in text
    assert store.get("X")["to"] == "giulia" and store.get("X")["handoff"]["amount"] == 240.0
    assert web.approve("X", "DEFEND", "Hello", by="giulia")[0] == 200 and sent == ["DEFEND"]


def test_no_drafted_question_when_paypal_does_not_allow_it():
    sent, _, _ = approval_bench(action="ASK_SELLER", ai="MESSAGE", stops=["paypal_allowed"])
    code, text = web.approve("X", "MESSAGE", "Hello", by="marta")
    assert code == 409 and sent == [] and "PayPal doesn't allow it at this stage" in text


def test_taking_a_case_keeps_the_colleague_s_handoff():
    _, _, store = approval_bench()
    web.approve("X", "REFUND", "Hello", by="marta")                    # passed to Giulia, with a note
    assert web.take("X", "giulia") == (200, "Giulia took this case.")
    assert store.get("X")["to"] == "giulia" and store.get("X")["handoff"]["from"] == "marta"
    assert web.take("X", None)[0] == 400


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
