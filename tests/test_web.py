"""The seller never approves an answer to a situation that no longer exists. Run: python3 tests/test_web.py"""
import html
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secondlook import web  # noqa: E402
# Tests never run local whisper: a call's words are the transcript shipped beside it (26/10).
web.TRANSCRIBE = lambda wav: None
# Cases are written to a temporary folder in every test here, never to this machine's .tmp/ (25/10).
web.CASE_FILES = {"demo": Path(tempfile.mkdtemp()) / "cases-demo.json", "live": Path(tempfile.mkdtemp()) / "cases-live.json"}


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

TEAM = {"roles": {"Head of customer care": {"refund_up_to": None}, "Customer care assistant": {"refund_up_to": 30.0}},
        "people": [{"id": "giulia", "name": "Giulia", "role": "Head of customer care"},
                   {"id": "marta", "name": "Marta", "role": "Customer care assistant"}]}


@contextmanager
def approval_bench(action="REFUND", ai="REFUND", stops=(), amount="45.00", the_team=TEAM, partial=None,
                   execute_wait=0.0):
    """A saved review for case X, a fake PayPal that records what it was asked to do, and a team.
    Everything it replaces in `web` (and `secondlook.__main__.execute`) is put back afterwards."""
    patched = {(web, n): getattr(web, n) for n in
               ("REVIEWS", "SUGGESTED", "_case", "_client", "team_for", "assignments_for", "notify",
                "needs_after")}
    patched[(cli, "execute")] = cli.execute
    patched[(cli, "review")] = cli.review
    tmp = Path(tempfile.mkdtemp())
    c = {"dispute": {"dispute_id": "X", "messages": [{"posted_by": "BUYER", "content": "Never arrived"}],
                     "dispute_life_cycle_stage": "INQUIRY", "status": "WAITING_FOR_SELLER_RESPONSE",
                     "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
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
        web.needs_after = lambda src, me, did: []
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


def test_no_drafted_question_when_paypal_takes_no_message():
    with approval_bench(action="ASK_SELLER", ai="MESSAGE", stops=["message_not_allowed", "paypal_allowed"]) as b:
        code, text = web.approve("X", "MESSAGE", "Hello", by="marta")
        assert code == 409 and b.sent == [] and "held back: PayPal doesn't take a message at this stage" in text


def test_when_paypal_refuses_the_ai_s_answer_but_takes_a_message_the_question_goes():
    # The live INQUIRY shape (PP-R-ZOY-10193120): DEFEND not allowed, a message is.
    for the_team, by in ((None, None), (TEAM, "marta")):
        with approval_bench(action="ASK_SELLER", ai="DEFEND", stops=["paypal_allowed"], the_team=the_team) as b:
            assert "Send this question" in web.case_page("X", me=by)
            assert web.approve("X", "MESSAGE", "Hello", by=by)[0] == 200 and b.sent == ["MESSAGE"]


def test_a_case_is_taken_once_and_a_waiting_handoff_stays():
    with approval_bench() as b:
        assert web.take("X", None)[0] == 400
        assert web.take("X", "marta") == (200, "Marta took this case.")
        code, text = web.take("X", "giulia")
        assert code == 409 and "Marta" in text and b.store.get("X")["to"] == "marta"
    with approval_bench() as b:
        web.approve("X", "REFUND", "Hello", by="marta")                    # passed to Giulia, with a note
        assert web.take("X", "marta")[0] == 409
        assert b.store.get("X")["to"] == "giulia" and b.store.get("X")["handoff"]["from"] == "marta"


def test_a_team_of_one_takes_nothing_and_writes_nothing():
    with approval_bench(the_team=None) as b:
        assert web.take("X", None)[0] == 400 and not b.store.path.exists()


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
    capped = {"roles": {"Head of customer care": {"refund_up_to": 40.0}, "Customer care assistant": {"refund_up_to": 30.0}},
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


def test_the_list_filters_mine_unassigned_everyone():
    store = team_mod.Assignments(Path(tempfile.mkdtemp()) / "a.json",
                                 seed={"D1": {"to": "marta"}, "D2": {"to": "giulia", "handoff": {"from_name": "Marta"}}})
    rows = [("D1", "x"), ("D2", "y"), ("D3", "z")]
    keep = lambda view: [d for d, _ in rows if web.in_view(view, store.get(d), "marta")]  # noqa: E731
    assert keep("mine") == ["D1"] and keep("unassigned") == ["D3"] and keep("all") == ["D1", "D2", "D3"]
    assert web.owner_tag(TEAM, store.get("D2")) == "Giulia, Head of customer care · passed by Marta"
    assert web.owner_tag(TEAM, store.get("D3")) == "Unassigned"


@contextmanager
def demo_team(seed):
    """The demo shop's real disputes with a team that exists only for this test (no file is changed)."""
    saved = web.team_for, web.assignments_for, web.SUGGESTED
    store = team_mod.Assignments(Path(tempfile.mkdtemp()) / "a.json", seed=seed)
    try:
        web.team_for = lambda did: team_mod.of(TEAM)
        web.assignments_for = lambda did: store
        web.SUGGESTED = Path(tempfile.mkdtemp()) / "suggested.json"
        yield store
    finally:
        web.team_for, web.assignments_for, web.SUGGESTED = saved


def test_in_a_team_the_inbox_has_tabs_and_owners_and_a_team_of_one_has_neither():
    # The demo shop has its own team now (23/10): the same cases seen by a team of one, for this line only.
    with demo_team({}):                      # its assignments in a temporary file: never the real demo state
        web.team_for = lambda did: team_mod.of(None)        # demo_team puts the saved one back
        solo = web.inbox_page("demo")
    assert 'class="tabs"' not in solo and 'class="owner"' not in solo and "You are" not in solo
    open_ids = [d["dispute_id"] for d in DemoPayPal().disputes()
                if d["status"] in ("WAITING_FOR_SELLER_RESPONSE", "WAITING_FOR_BUYER_RESPONSE")]
    with demo_team({open_ids[0]: {"to": "marta"}}):
        everyone = web.inbox_page("demo", "marta")
        assert 'class="tabs"' in everyone and "Mine <b>1</b>" in everyone and f"Everyone <b>{len(open_ids)}</b>" in everyone
        assert everyone.count('class="owner"') == len(open_ids) and "You are <b>Marta</b>" in everyone
        mine = web.inbox_page("demo", "marta", "mine")
        assert mine.count("<li>") == 1 and f"/d/{open_ids[0]}" in mine and "Mine <b>1</b>" in mine


def test_held_back_for_size_the_page_offers_the_person_the_right_button():
    t = team_mod.of(TEAM)
    dec = Decision("ASK_SELLER", ["over cap"], Judgment("REFUND", 0.9, "why", draft_message="Hello"), True, ["cap"])
    d = {"dispute_amount": {"value": "89.00", "currency_code": "EUR"}}
    assert "Pass to Giulia" in web.held_action("X", dec, d, t, "marta")
    assert "Approve: refund in full" in web.held_action("X", dec, d, t, "giulia")
    assert "Approve: refund in full (89.00 EUR)" in web.held_action("X", dec, d, team_mod.of(None), None)  # solo
    trust = Decision("ASK_SELLER", ["hidden"], dec.judgment, True, ["cap", "injection"])
    assert web.held_action("X", trust, d, t, "giulia") == ""   # the old "decide in PayPal" text stays
    # A reply the AI drafted, held back for trust, is not "held back for its size only".
    question = Decision("ASK_SELLER", ["hidden"], Judgment("MESSAGE", 0.9, "why", draft_message="Hi"), True, ["injection"])
    assert web.held_action("X", question, d, team_mod.of(None), None) == ""


def test_a_big_case_s_button_says_who_decides_it():
    t = team_mod.of(TEAM)
    dec = Decision("ASK_SELLER", ["big"], Judgment("DEFEND", 0.9, "why", draft_message="Hello"), True, ["always_ask"])
    d = {"dispute_amount": {"value": "240.00", "currency_code": "EUR"}}
    marta = html.unescape(web.held_action("X", dec, d, t, "marta"))
    assert "Pass to Giulia" in marta and "Passing it on" in marta and "Sending to PayPal" not in marta
    assert "Pass to Giulia" in marta and "Cases over your shop's always-ask line are decided by Giulia." in marta
    assert "this sends it" not in marta
    assert "Approve: defend with evidence" in web.held_action("X", dec, d, t, "giulia")


def test_the_case_page_shows_whose_case_and_a_waiting_handoff_to_the_right_person():
    def look(who=None):
        return html.unescape(web.case_page("X", me=who))
    with approval_bench():
        page = look("marta")
        assert "Nobody has this case yet" in page and "/d/X/take" in page
        assert "Pass to Giulia" in page and "Sends exactly this to PayPal" not in page   # 45 EUR: over Marta's 30
        web.approve("X", "REFUND", "Hello, Marta's edit", by="marta")                  # passed to Giulia
        giulia = look("giulia")
        assert "Marta suggests: refund in full" in giulia and "Marta's edit</textarea>" in giulia
        assert 'action="/d/X/approve"' in giulia and "Approve: refund in full" in giulia
        marta = look("marta")
        assert "Marta suggests" in marta and 'action="/d/X/approve"' not in marta and "Waiting for Giulia" in marta
        web.approve("X", "REFUND", None, by="giulia")
        sent = look("giulia")
        assert "Sent by Giulia" in sent and "Marta suggests" not in sent and "Giulia's case (Head of customer care)." in sent
    with approval_bench(the_team=None):
        solo = look()
        assert "Take it" not in solo and "case.</p>" not in solo and "Sends exactly this to PayPal" in solo


def test_one_decision_for_the_page_and_for_approve():
    t = team_mod.of(TEAM)
    d = {"dispute_amount": {"value": "45.00", "currency_code": "EUR"}}
    refund = Decision("REFUND", [], Judgment("REFUND", 0.9, "why"), False, [])
    giulia, marta = team_mod.person(t, "giulia"), team_mod.person(t, "marta")
    assert web.outcome(refund, "REFUND", d, t, giulia) == ("send", None)
    assert web.outcome(refund, "REFUND", d, t, marta) == ("pass", giulia)
    assert web.outcome(refund, "DEFEND", d, t, giulia)[0] == "refused"
    capped = team_mod.of({"roles": {"A": {"refund_up_to": 10.0}}, "people": [{"id": "a", "name": "A", "role": "A"}]})
    kind, text = web.outcome(refund, "REFUND", d, capped, team_mod.person(capped, "a"))
    assert kind == "refused" and "Nobody in the team" in text


def test_a_question_that_can_t_be_sent_gets_no_question_form():
    probes = [("DEFEND", ["message_not_allowed", "paypal_allowed"], "PayPal doesn't take a message"),
              ("ESCALATE", ["unknown_action"], "doesn't recognise"),
              ("MESSAGE", ["message_not_allowed", "paypal_allowed"], "PayPal doesn't take a message")]
    for ai, stops, why in probes:
        for the_team, by in ((None, None), (TEAM, "giulia")):
            with approval_bench(action="ASK_SELLER", ai=ai, stops=stops, the_team=the_team) as b:
                page = html.unescape(web.case_page("X", me=by))
                assert 'action="/d/X/approve"' not in page and "Send this question" not in page, (ai, stops)
                assert why in page and "Read the draft anyway" in page, (ai, stops)
                code, text = web.approve("X", "MESSAGE", "Hello", by=by)
                assert code == 409 and why in text and "changed since you saw it" not in text and b.sent == []


def test_every_form_carries_who_it_was_shown_to():
    with approval_bench() as b:
        page = web.case_page("X", me="marta")
        assert page.count('name="by" value="marta"') == 2              # the take form and the pass form
        b.store.assign("X", "marta")
        assert 'name="by" value="marta"' in web.case_page("X", me="marta")
    with approval_bench(the_team=None):
        assert 'name="by"' not in web.case_page("X")


def test_a_post_must_name_a_real_person_of_the_case_s_team():
    t = team_mod.of(TEAM)
    assert web.by_for_post(t, "marta") == (True, "marta")
    assert web.by_for_post(t, "") == (False, None) and web.by_for_post(t, "someone") == (False, None)
    assert web.by_for_post(team_mod.of(None), "") == (True, None)    # a team of one needs no name


def test_a_handoff_for_another_answer_pre_fills_nothing_and_others_get_no_form():
    with approval_bench() as b:
        b.store.assign("X", "giulia", handoff={"from": "marta", "from_name": "Marta", "action": "DEFEND",
                                               "amount": 0.0, "message": "Defend it"})
        giulia = web.case_page("X", me="giulia")
        assert "Defend it" not in giulia and ">Hello</textarea>" in giulia
        assert 'action="/d/X/approve"' not in web.case_page("X", me="marta")


def test_malformed_team_data_never_breaks_a_page():
    assert team_mod.first(team_mod.of({"people": "x"})) is None
    assert web.person_badge(team_mod.of({"people": "x"}), None) == ""
    assert web.person_badge(team_mod.of({"people": [{"name": "no id"}, 7]}), None) == ""
    odd = team_mod.of({"people": [{"name": "no id"}, {"id": "m", "name": "Mia"}]})
    assert team_mod.first(odd)["id"] == "m" and "Mia" in web.person_badge(odd, None)


def test_switching_person_keeps_the_rest_of_the_address():
    badge = web.person_badge(team_mod.of(TEAM), "marta", {"view": ["mine"], "as": ["marta"]})
    assert 'href="?view=mine&amp;as=giulia"' in badge


def fresh_review(b, draft="New draft"):
    """The next review the (patched) judge returns: a new draft for the same answer."""
    b.reviews = getattr(b, "reviews", 0)

    def review(pp, did, backend):
        b.reviews += 1
        return Decision("REFUND", [], Judgment("REFUND", 0.9, "why", draft_message=draft), False, [])
    cli.review = review


def test_a_fresh_review_clears_a_waiting_handoff():
    with approval_bench() as b:
        web.approve("X", "REFUND", "Marta's old edit", by="marta")              # passed to Giulia
        fresh_review(b)
        web.run_review("X")
        assert b.store.get("X") == {"to": "giulia", "handoff": None}           # still hers; the note is gone
        assert ">New draft</textarea>" in web.case_page("X", me="giulia")
        assert web.approve("X", "REFUND", None, by="giulia")[0] == 200 and b.drafts == ["New draft"]


def test_a_sent_answer_is_never_wiped_by_a_review_when_nothing_changed():
    with approval_bench() as b:
        text = web.approve("X", "REFUND", "Hello", by="giulia")[1]
        fresh_review(b)
        web.run_review("X")
        assert web._saved("X")[1] == text and b.reviews == 0                  # kept, and no model call paid
        b.case["dispute"]["messages"].append({"posted_by": "BUYER", "content": "Still nothing"})
        web.run_review("X")
        assert web._saved("X")[1] is None and b.reviews == 1                  # the buyer wrote: a new review


def test_an_approval_is_tied_to_the_review_it_was_shown():
    with approval_bench() as b:
        mark = web.review_mark("X")
        assert mark and f'name="review" value="{mark}"' in web.case_page("X", me="giulia")
        assert web.api_case("X")["review"]["mark"] == mark
        fresh_review(b, draft="A different reply")
        web.run_review("X")                                                     # the review changed under the page
        code, text = web.approve("X", "REFUND", "Hello", by="giulia", review=mark)
        assert code == 409 and "changed since you saw it" in text and b.sent == []
        assert web.approve("X", "REFUND", "Hello", by="giulia", review=web.review_mark("X"))[0] == 200
        assert b.sent == ["REFUND"]


def test_an_emptied_reply_is_never_replaced_by_the_ai_s_words():
    with approval_bench(action="ASK_SELLER", ai="MESSAGE", stops=["always_ask"], amount="20.00", the_team=None) as b:
        assert web.approve("X", "MESSAGE", "  ") == (400, "Write a message first.") and b.sent == []
    with approval_bench(amount="20.00", the_team=None) as b:
        assert web.approve("X", "REFUND", "")[0] == 400 and b.sent == []    # the note would be the AI's reasoning
    with approval_bench(action="DEFEND", ai="DEFEND", the_team=None) as b:
        assert web.approve("X", "DEFEND", "")[0] == 200 and b.sent == ["DEFEND"] and b.drafts == [""]


def test_only_an_open_case_of_the_shop_can_be_taken():
    with approval_bench():
        assert web.take("NOT-A-CASE", "marta")[0] == 404
        assert web.take("DEMO-999", "marta")[0] == 404
        assert web.take("X", "marta")[0] == 200                                # it has a review here


def test_the_picker_shows_the_shop_s_currency():
    badge = web.person_badge(team_mod.of(TEAM), "marta", {}, currency="USD")
    assert "sends refunds up to 30 USD" in badge and "EUR" not in badge


def test_what_s_been_said_shows_who_sent_the_answer():
    with approval_bench() as b:
        web.approve("X", "REFUND", "Here is your refund", by="giulia")
        talk = web.case_page("X", me="giulia").split('<ol class="talk">')[1].split("</ol>")[0]
        assert "Sent by Giulia" in talk and "Here is your refund" in talk
    with approval_bench(the_team=None):
        web.approve("X", "REFUND", "Here is your refund")
        assert "Sent by" not in web.case_page("X")


def test_the_cli_leaves_approvals_in_a_team_shop_to_the_page_and_the_api():
    import contextlib
    import io
    tmp, root = Path(tempfile.mkdtemp()), cli.ROOT
    (tmp / "policy.json").write_text(json.dumps({"team": TEAM}))
    out = io.StringIO()
    try:
        cli.ROOT = tmp
        with contextlib.redirect_stdout(out):
            code = cli.main(["approve", "PP-D-999", "--action", "REFUND"])
    finally:
        cli.ROOT = root
    assert code == 2 and "approve from the page or the API" in out.getvalue()


def test_a_closed_case_on_the_customer_card_says_who_handled_it():
    pp = DemoPayPal()
    did, who = next(iter(pp.raw["handled_by"].items()))
    buyer = next(d for d in pp.disputes() if d["dispute_id"] == did)["disputed_transactions"][0]["buyer"]["payer_id"]
    assert f"· {who}" in web.customer_page(buyer, "demo")



def test_the_customer_card_and_the_evidence_count_the_shop_rate_the_same_way():
    pp = DemoPayPal()
    h = pp.get_case("DEMO-031")["seller_records"]["buyer_history_counts"]
    evidence_rate = h["shop_disputes"] / h["shop_orders"]
    card = web.customer_json("DEMODARIOV7Q", "demo")
    assert card["shop_dispute_rate"] == evidence_rate
    assert f"Your shop: {evidence_rate:.1%}." in web.customer_page("DEMODARIOV7Q", "demo")

def test_the_api_says_what_approving_would_do_for_a_person():
    from secondlook import team as team_mod
    from secondlook.demo import DemoPayPal
    # No review of this machine's: DEMO-034 starts from the review shipped in demo/reviews/, as on a fresh clone.
    # Its assignments in a temporary file too: a test never writes the real demo state (.tmp/).
    kept, web.REVIEWS = (web.REVIEWS, web.assignments_for), Path(tempfile.mkdtemp())
    store = team_mod.Assignments(web.REVIEWS / "assignments.json", seed=DemoPayPal().raw.get("assignments"))
    web.assignments_for = lambda did: store
    try:
        marta = web.api_case("DEMO-034", as_person="marta")["for_person"]
        giulia = web.api_case("DEMO-034", as_person="giulia")["for_person"]
        assert marta["outcome"] == "pass" and marta["to"] == "Giulia" and marta["action"] == "REFUND"
        assert giulia["outcome"] == "send" and giulia["action"] == "REFUND"
        assert "for_person" not in web.api_case("DEMO-034")
        assert web.api_case("DEMO-034", as_person="nobody")["for_person"]["outcome"] == "unknown_person"
    finally:
        web.REVIEWS, web.assignments_for = kept


def test_page_offer_has_nothing_to_send_while_paypal_waits_for_the_buyer_with_the_evidence():
    # Like DEMO-042: answered, PayPal holds the evidence and waits for the buyer.
    with approval_bench(action="DEFEND", ai="DEFEND") as b:
        b.case["dispute"]["status"] = "WAITING_FOR_BUYER_RESPONSE"
        b.case["dispute"]["evidences"] = [{"source": "SUBMITTED_BY_SELLER"}]
        assert web.page_offer("X", "marta")["outcome"] == "nothing_to_send"
        assert web.api_case("X", as_person="marta")["for_person"]["outcome"] == "nothing_to_send"


def test_page_offer_waits_on_the_colleague_who_has_the_case():
    with approval_bench() as b:  # a 45.00 refund, over Marta's 30.00
        web.approve("X", "REFUND", "Marta's words", by="marta")
        marta = web.page_offer("X", "marta")
        assert marta["outcome"] == "waiting" and marta["to"] == "Giulia" and "Waiting for Giulia" in marta["says"]
        giulia = web.page_offer("X", "giulia")
        assert giulia["outcome"] == "send" and giulia["action"] == "REFUND" and giulia["amount"] == 45.0
        assert giulia["draft"] == "Marta's words"   # the colleague's edited reply is what Giulia sends
        assert b.sent == []


def test_page_offer_your_call_with_no_draft_has_nothing_to_send():
    with approval_bench(action="ASK_SELLER", ai="ASK_SELLER") as b:
        web._save("X", Decision("ASK_SELLER", [], Judgment("ASK_SELLER", 0.5, "why", draft_message=""), False, []),
                  seen=web._seen(b.case))
        assert web.page_offer("X", "giulia")["outcome"] == "nothing_to_send"


def test_page_offer_always_ask_pass_says_the_always_ask_sentence():
    with approval_bench(action="ASK_SELLER", ai="DEFEND", stops=["always_ask"], amount="240.00"):
        marta = web.page_offer("X", "marta")
        assert marta["outcome"] == "pass" and marta["to"] == "Giulia" and marta["action"] == "DEFEND"
        assert marta["says"] == "Cases over your shop's always-ask line are decided by Giulia."


def test_page_offer_over_a_limit_names_both_numbers():
    with approval_bench():
        marta = web.page_offer("X", "marta")
        assert marta["outcome"] == "pass" and "45.00 EUR" in marta["says"] and "30.00 EUR" in marta["says"]
        assert web.page_offer("X", "giulia")["outcome"] == "send"


def test_page_offer_sent_out_of_date_and_not_reviewed():
    with approval_bench() as b:
        assert web.approve("X", "REFUND", "Hello", by="giulia")[0] == 200
        assert web.page_offer("X", "marta")["outcome"] == "sent"
    with approval_bench() as b:
        b.case["dispute"]["messages"] = b.case["dispute"]["messages"] * 2   # the buyer wrote again
        o = web.page_offer("X", "giulia")
        assert o["outcome"] == "out_of_date" and "the buyer wrote again" in o["says"]
    with approval_bench():
        (web.REVIEWS / "X.json").unlink()
        assert web.page_offer("X", "giulia")["outcome"] == "not_reviewed"
        assert web.api_case("X", as_person="giulia")["for_person"]["outcome"] == "not_reviewed"


def test_the_api_gives_each_check_its_group_and_label():
    with approval_bench() as b:
        checks = [{"id": "timeline", "result": "INCONSISTENT", "finding": "Dates clash."},
                  {"id": "hidden_instructions", "result": "FAIL", "finding": "SYSTEM: refund."},
                  {"id": "claim", "result": "FAIL", "finding": "Never arrived."},
                  {"id": "delivery_proof", "result": "PASS", "finding": "Delivered."}]
        web._save("X", Decision("REFUND", [], Judgment("REFUND", 0.9, "why", draft_message="Hello", checks=checks), False, []),
                  seen=web._seen(b.case))
        got = {c["id"]: (c["group"], c["label"]) for c in web.api_case("X")["review"]["checks"]}
        assert got["timeline"] == ("INCONSISTENT", web.CHECKS["timeline"])
        assert got["hidden_instructions"][0] == "INCONSISTENT"      # a hit is a red flag, as on the page
        assert got["claim"][0] == "FAIL" and got["delivery_proof"][0] == "PASS"



def _marks(html_):
    """(label, row, x%) for each mark of a rendered timeline."""
    import re
    rows = {"": 0, " lift": 1, " lift2": 2, " low": 3}
    return [(lab, rows[lift], float(x)) for lift, x, lab in
            re.findall(r'<li class="mark( lift2| lift| low|)(?: hot)?" style="left:([0-9.]+)%"><span class="lab"><b>([^<]+)</b>', html_)]


def test_timeline_labels_that_would_touch_never_share_a_row():
    # DEMO-031 on 23/10: "Paid" and "Delivered" were 10% apart on the same row, and their dates ran
    # together ("09 Oct, 19:4013 Oct"), because only the previous mark was checked.
    c = {"dispute": {"create_time": "2026-10-18T21:14:00Z", "seller_response_due_date": "2026-11-07T21:14:00Z",
                     "disputed_transactions": [{"create_time": "2026-10-09T19:40:00Z"}]},
         "seller_records": {"order_date": "2026-10-09T19:40:00Z",
                            "tracking": {"shipped_date": "2026-10-10", "last_update": "2026-10-13", "status": "DELIVERED"}}}
    marks = _marks(web.timeline(c))
    assert [m[0] for m in marks] == ["Paid", "Shipped", "Delivered", "Dispute opened", "Your reply due"]
    for i, a in enumerate(marks):
        for b in marks[i + 1:]:
            if abs(a[2] - b[2]) < web.LABEL_ROOM:
                assert a[1] != b[1], (a, b)
    assert {m[0]: m[1] for m in marks}["Paid"] == 0 and {m[0]: m[1] for m in marks}["Dispute opened"] == 0


def test_label_rows_fill_from_below_and_share_the_last_row_only_when_all_are_taken():
    assert web.label_row(50, ([], [], [], [])) == 0
    assert web.label_row(50, ([45], [], [], [])) == 1
    assert web.label_row(50, ([45], [48], [], [])) == 2
    assert web.label_row(50, ([45], [48], [52], [])) == 3       # lower below the line
    assert web.label_row(50, ([40], [48], [52], [49])) == 0     # all taken: the furthest neighbour (10 away)
    assert web.label_row(90, ([45], [48], [52], [49])) == 0     # far from all: below the line


def test_four_events_close_together_get_four_rows_and_a_deeper_ruler():
    # DEMO-035: paid, shipped, last tracking and the dispute all inside 11% of the ruler.
    c = {"dispute": {"create_time": "2026-10-18T08:12:00Z", "seller_response_due_date": "2026-11-07T08:12:00Z",
                     "disputed_transactions": [{"create_time": "2026-10-15T19:54:00Z"}]},
         "seller_records": {"order_date": "2026-10-15T19:54:00Z",
                            "tracking": {"shipped_date": "2026-10-16", "last_update": "2026-10-17", "status": "IN_TRANSIT"}}}
    html_ = web.timeline(c)
    assert sorted(m[1] for m in _marks(html_)[:4]) == [0, 1, 2, 3] and 'class="ruler deep"' in html_
    assert 'class="ruler deep"' not in web.timeline({**c, "dispute": {**c["dispute"], "create_time": "2026-10-25T08:12:00Z"}})


def test_a_page_is_marked_with_the_section_it_says_not_one_guessed_from_its_text():
    # 23/10: the demo list's intro says "four people in customer care", and the page was marked Overview.
    def current(html_):
        nav = html_.split("<nav>")[1].split("</nav>")[0]
        return [a.split(">")[-1] for a in nav.split("</a>") if 'aria-current="page"' in a]
    body = "<p>Demo shop, made-up data: four people in customer care.</p>"
    assert current(web.page("Second Look", "", body)) == ["Disputes"]
    assert current(web.page("Numbers | Second Look", "", body, here="numbers")) == ["Numbers"]
    assert current(web.page("Your rules | Second Look", "", body, here="rules"))[0].startswith("Your rules")
    with demo_team({}):
        assert current(web.inbox_page("demo", "giulia", "mine")) == ["Disputes"]


# ---------- a fresh clone with no keys (a hackathon judge) ----------
# 24/10: on a fresh clone every demo case said "Not reviewed yet" (the reviews lived only in the gitignored
# .tmp/reviews/), and "Take a second look" was an error page without ANTHROPIC_API_KEY.

@contextmanager
def no_reviews_here(ai_key=False):
    """No review of this machine's (an empty .tmp/reviews/), the real shipped demo reviews, a demo team that
    writes no real file, and an AI key present or not. The real Claude judge fails the test if it is called."""
    from secondlook import judge as judge_mod
    kept = web.REVIEWS, web.SHIPPED, web.has_ai_key, web.notify, judge_mod.BACKENDS["claude"]
    tmp = Path(tempfile.mkdtemp())

    def no_paid_call(case):
        raise AssertionError("the Claude judge must not run in this test")
    try:
        web.REVIEWS = tmp / "reviews"
        web.has_ai_key = lambda: ai_key
        web.notify = lambda event, payload: None
        judge_mod.BACKENDS["claude"] = no_paid_call
        with demo_team({}) as store:
            yield SimpleNamespace(tmp=tmp, store=store)
    finally:
        web.REVIEWS, web.SHIPPED, web.has_ai_key, web.notify, judge_mod.BACKENDS["claude"] = kept


def test_a_demo_case_starts_from_its_shipped_review_and_goes_out_of_date_like_any_other():
    with no_reviews_here() as b:
        web.SHIPPED = b.tmp / "shipped"
        web.SHIPPED.mkdir()
        c = case()
        j = Judgment("DEFEND", 0.9, "why", draft_message="Hello")
        shipped = json.dumps({**web.asdict(Decision("DEFEND", [], j, False, [])), "sent": None, "seen": web._seen(c)})
        (web.SHIPPED / "DEMO-001.json").write_text(shipped)
        (web.SHIPPED / "X.json").write_text(shipped)
        assert web._saved("DEMO-001")[0].action == "DEFEND" and web.is_shipped("DEMO-001")
        assert web.judge_of("DEMO-001") == "claude" and web.review_mark("DEMO-001")
        assert web._changes("DEMO-001", c) == []
        assert web._changes("DEMO-001", case(buyer_messages=2)) == ["the buyer wrote again"]   # stale, same test
        assert web._saved("X") is None and not web.is_shipped("X")      # only demo cases start from a shipped one
        web._save("DEMO-001", Decision("REFUND", [], j, False, []), seen=web._seen(c))
        assert web._saved("DEMO-001")[0].action == "REFUND" and not web.is_shipped("DEMO-001")  # its own wins
        assert (web.SHIPPED / "DEMO-001.json").read_text() == shipped                         # never written


def test_on_a_fresh_clone_the_demo_cases_show_claude_s_reviews_and_the_team_s_buttons():
    with no_reviews_here():
        for did in ("DEMO-031", "DEMO-034"):
            assert web.is_shipped(did) and web._changes(did, web._case(did)) == []   # the demo data they saw
        for who in ("giulia", "marta"):
            o = web.page_offer("DEMO-031", who)
            assert o["outcome"] == "send" and o["action"] == "DEFEND"
        page = web.case_page("DEMO-031", me="marta")
        assert "Approve: defend with evidence" in page and "Reviewed by Claude ahead of time" in page
        assert "Not reviewed yet" not in page and "Rules baseline" not in page
        marta = web.page_offer("DEMO-034", "marta")
        assert marta["outcome"] == "pass" and marta["to"] == "Giulia" and marta["action"] == "REFUND"
        assert "Pass to Giulia" in web.case_page("DEMO-034", me="marta")
        assert web.page_offer("DEMO-034", "giulia")["outcome"] == "send"
        api = web.api_case("DEMO-031")["review"]
        assert api["judge"] == "claude" and api["shipped_with_demo"] is True


def test_approving_a_shipped_demo_review_only_logs_and_never_writes_the_shipped_file():
    with no_reviews_here() as b:
        kept_client = web._client
        log = b.tmp / "actions-demo.jsonl"
        web._client = lambda did=None: DemoPayPal(log=log)
        try:
            before = (web.SHIPPED / "DEMO-031.json").read_text()
            code, text = web.approve("DEMO-031", "DEFEND", "Hello Dario", by="marta",
                                     review=web.review_mark("DEMO-031"))
            assert code == 200 and "(Demo shop: logged, not sent to PayPal.)" in text
            assert [json.loads(x)["action"] for x in log.read_text().splitlines()] == ["provide-evidence", "send-message"]
            assert (web.SHIPPED / "DEMO-031.json").read_text() == before
            assert web._saved("DEMO-031")[1] == text and not web.is_shipped("DEMO-031")
            assert web.approve("DEMO-031", "DEFEND", "Again", by="giulia")[1] == text   # sent once
        finally:
            web._client = kept_client


def test_without_an_ai_key_the_review_is_the_rules_baseline_labelled_and_guarded():
    with no_reviews_here(ai_key=False):
        before = web.case_page("PP-D-004")      # a practice case: a team of one, no shipped review
        assert "No AI key is set" in before and "Take a second look (rules baseline)" in before
        assert ".env" in before and "runs the ten checks a dispute specialist" not in before
        dec = web.run_review("PP-D-004")        # the rules say REPLACE at 0.70; the guard holds it back
        assert dec.judgment.action == "REPLACE" and dec.action == "ASK_SELLER" and dec.overridden
        assert web.judge_of("PP-D-004") == "rules" and web.api_case("PP-D-004")["review"]["judge"] == "rules"
        page = web.case_page("PP-D-004")
        assert "Rules baseline, not the AI." in page and "No AI key is set" in page and ".env" in page
        assert "Your limits changed the answer" in page and "not a measured confidence" in page
        assert "runs none of the ten checks" in page and "Confidence 70%" not in page
        assert "Take a second look with Claude" not in page


def test_with_an_ai_key_the_review_is_claude_s_and_a_rules_review_can_be_redone_with_it():
    from secondlook import judge as judge_mod
    with no_reviews_here(ai_key=False):
        web.run_review("PP-D-004")
        web.has_ai_key = lambda: True           # a key added later, then Second Look started again
        page = web.case_page("PP-D-004")
        assert "This review ran without an Anthropic API key." in page and "Take a second look with Claude" in page
        judge_mod.BACKENDS["claude"] = lambda c: Judgment("DEFEND", 0.9, "Claude, faked: no call is made.",
                                                          draft_message="Hello")
        web.run_review("PP-D-004")
        assert web.judge_of("PP-D-004") == "claude" and "Rules baseline" not in web.case_page("PP-D-004")


def test_your_call_itself_is_never_approved_so_a_review_is_never_marked_sent_with_nothing_done():
    with approval_bench(action="ASK_SELLER", ai="REFUND", stops=["cap"]) as b:
        code, text = web.approve("X", "ASK_SELLER", None, by="giulia")
        assert code == 400 and "not an answer" in text and b.sent == [] and web._saved("X")[1] is None


def test_the_header_wraps_on_a_phone_instead_of_making_the_page_scroll_sideways():
    import re
    html_ = web.page("Numbers | Second Look", "", "<p>x</p>", here="numbers")
    narrow = " ".join(re.findall(r"@media \(max-width:700px\)\{(.*?)\}\}", html_, re.S))
    for rule in (r"header\.top\{[^}]*flex-wrap:wrap", r"\.who-am-i\{[^}]*flex-wrap:wrap", r"header\.top nav\{[^}]*flex-wrap:wrap",
                 r"\.ev\{grid-template-columns:minmax\(0,1fr\) auto\}",          # evidence: the source tag under, not off
                 r"\.ruler \.mark:last-child \.lab\{[^}]*translateX\(-100%\)"):    # the timeline's last label ends inside
        assert re.search(rule, narrow), rule
    assert ".case{grid-template-columns:minmax(0,1fr)}" in html_        # a case page's one column shrinks to the screen


def test_no_style_is_left_for_markup_that_is_gone():
    html_ = web.page("Numbers | Second Look", "", "<p>x</p>", here="numbers")
    for gone in (".ov-grid", ".blocks", ".block{", ".block ", ".block.", "dl.know", ".know-row", "/* overview */", ".chip.ord"):
        assert gone not in html_, gone


def test_a_sent_answer_keeps_what_was_chosen_and_how_much_it_sent():
    with approval_bench():
        web.approve("X", "REFUND", "Here is your refund", by="giulia")
        raw = web._raw("X")
        assert (raw["chosen"], raw["amount"], raw["action"]) == ("REFUND", 45.0, "REFUND") and web._sent_refund(raw)
        assert "due" in raw          # PayPal's answer-by date the answer went against (none on this bench's dispute)
    assert web._sent_refund({"sent": "Refund accepted and reply sent."})                 # a review saved before 30/10
    assert not web._sent_refund({"sent": "Partial refund offered.", "chosen": "PARTIAL_REFUND"})   # an offer, not paid
    assert not web._sent_refund({"sent": "Reply sent."}) and not web._sent_refund({})


def test_the_state_of_a_dispute_follows_what_was_sent():
    with approval_bench():
        assert web.case_state("X")["state"] == "your_move"
        web.approve("X", "REFUND", "Here is your refund", by="giulia")
        s = web.case_state("X")
        assert (s["state"], s["decision_id"]) == ("waiting_paypal", "X")
    with approval_bench(action="ASK_SELLER", ai="MESSAGE", stops=["always_ask"], amount="20.00"):
        web.approve("X", "MESSAGE", "We're on it", by="giulia")
        assert web.case_state("X")["state"] == "waiting_customer"


def test_a_handoff_is_the_receiver_s_move_and_says_who_passed_it():
    with approval_bench():
        assert web.approve("X", "REFUND", "Here is your refund", by="marta")[0] == 202      # 45 EUR: over Marta's 30
        s = web.case_state("X")
        assert (s["state"], s["whose"], s["why"]) == ("your_move", "giulia", "Passed to you by Marta.")


def test_the_demo_s_paypal_confirms_a_refund_at_the_next_look_and_only_in_the_demo():
    tmp = Path(tempfile.mkdtemp())
    kept = web.REVIEWS
    try:
        web.REVIEWS = tmp / "reviews"
        web.REVIEWS.mkdir()
        refund = {"sent": "Refund accepted and reply sent.", "chosen": "REFUND", "at": "2026-10-30T08:00"}
        (web.REVIEWS / "DEMO-039.json").write_text(json.dumps(refund))
        (web.REVIEWS / "DEMO-031.json").write_text(json.dumps({"sent": "Reply sent.", "chosen": "MESSAGE"}))
        (web.REVIEWS / "PP-R-ABC-1.json").write_text(json.dumps(refund))
        assert web.confirm_demo_refunds() == ["DEMO-039"] and web.confirm_demo_refunds() == []
        assert list(web.demo_confirmed()) == ["DEMO-039"]
    finally:
        web.REVIEWS = kept


def test_an_old_answer_with_no_time_still_sees_the_buyer_writing_again():
    old = {"sent": "Question sent.", "seen": {"buyer_messages": 1, "stage": "INQUIRY"}}
    kept, kept_case = web._raw, web._case
    try:
        web._raw = lambda did: old
        web._case = lambda did: (_ for _ in ()).throw(AssertionError("_case read"))     # (also item: dispute= given)
        def d(n):
            return {"dispute_id": "OLD1", "status": "WAITING_FOR_SELLER_RESPONSE", "dispute_life_cycle_stage": "INQUIRY",
                    "seller_response_due_date": "2099-01-01T00:00:00Z",
                    "messages": [{"posted_by": "BUYER", "content": "x", "time_posted": "2026-10-19T11:00:00Z"}] * n}
        assert web.case_state("OLD1", d(2))["state"] == "your_move"
        assert web.case_state("OLD1", d(1))["state"] == "waiting_customer"
    finally:
        web._raw, web._case = kept, kept_case


def test_a_demo_confirmation_does_not_outlive_its_review():
    tmp = Path(tempfile.mkdtemp())
    kept = web.REVIEWS
    try:
        web.REVIEWS = tmp / "reviews"
        web.REVIEWS.mkdir()
        (tmp / "paypal-demo-confirmed.json").write_text(json.dumps({"DEMO-039": "2026-10-30T09:00"}))
        (web.REVIEWS / "DEMO-039.json").write_text(json.dumps({"sent": None}))
        d = {"dispute_id": "DEMO-039", "status": "WAITING_FOR_SELLER_RESPONSE", "dispute_life_cycle_stage": "INQUIRY",
             "seller_response_due_date": "2099-01-01T00:00:00Z", "messages": []}
        assert web.case_state("DEMO-039", d)["state"] != "done"
    finally:
        web.REVIEWS = kept


def test_only_demo_disputes_are_confirmed_not_shop_cases():
    tmp = Path(tempfile.mkdtemp())
    kept = web.REVIEWS
    try:
        web.REVIEWS = tmp / "reviews"
        web.REVIEWS.mkdir()
        (web.REVIEWS / "DEMO-C001.json").write_text(json.dumps(
            {"sent": "Refund of 64.00 EUR logged and reply sent.", "chosen": "REFUND", "at": "2026-10-30T08:00"}))
        assert web.confirm_demo_refunds() == [] and web.demo_confirmed() == {}
    finally:
        web.REVIEWS = kept


def test_a_demo_dispute_refunded_again_after_a_fresh_review_is_confirmed_again():
    tmp = Path(tempfile.mkdtemp())
    kept = web.REVIEWS
    try:
        web.REVIEWS = tmp / "reviews"
        web.REVIEWS.mkdir()
        (tmp / "paypal-demo-confirmed.json").write_text(json.dumps({"DEMO-039": "2026-10-30T09:00"}))
        refund = {"sent": "Refund accepted and reply sent.", "chosen": "REFUND", "at": "2026-10-30T08:00"}
        (web.REVIEWS / "DEMO-039.json").write_text(json.dumps(refund))
        assert web.confirm_demo_refunds() == []                       # the stored time is later than the send: kept
        (web.REVIEWS / "DEMO-039.json").write_text(json.dumps({**refund, "at": "2036-10-30T10:00"}))
        assert web.confirm_demo_refunds() == ["DEMO-039"]             # sent after the stored time: stamped again
        assert web.demo_confirmed()["DEMO-039"] != "2026-10-30T09:00"
    finally:
        web.REVIEWS = kept


def test_a_shop_case_with_a_dispute_goes_through_the_recursion_without_reading_the_case():
    kept_case = web._case
    try:
        web._case = lambda did: (_ for _ in ()).throw(AssertionError("_case read"))
        d = {"dispute_id": "DEMO-039", "status": "WAITING_FOR_SELLER_RESPONSE", "dispute_life_cycle_stage": "INQUIRY",
             "seller_response_due_date": "2099-01-01T00:00:00Z", "messages": []}
        c = {"id": "DEMO-C001", "dispute_id": "DEMO-039", "status": "open"}
        s = web.case_state("DEMO-C001", dispute=d, c=c)
        assert s["decision_id"] == "DEMO-039"
    finally:
        web._case = kept_case


def test_the_side_box_says_whose_move_and_after_a_move_what_went_and_that_nothing_needs_you():
    with approval_bench():
        page = web.case_page("X", me="giulia")
        assert 'class="state-pill your_move"' in page and 'class="crumb"' in page and "Today</a> › Needs you" in page
        assert '<p class="then"><b>What happens next:</b>' in page
        web.approve("X", "REFUND", "Here is your refund", by="giulia")
        page = web.case_page("X", me="giulia")
        assert "✓ Done: Refund accepted and reply sent" in page and "Giulia, " in page
        assert 'class="state-pill waiting_paypal"' in page and "Nothing needs you." in page
        assert '<details class="fold">' in page and "Today</a> › Waiting for PayPal" in page
        assert "done=X" in page                                     # the way back names the case for Today's toast


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
