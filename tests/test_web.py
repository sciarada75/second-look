"""The seller never approves an answer to a situation that no longer exists. Run: python3 tests/test_web.py"""
import html
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


def test_the_list_filters_mine_unassigned_everyone():
    store = team_mod.Assignments(Path(tempfile.mkdtemp()) / "a.json",
                                 seed={"D1": {"to": "marta"}, "D2": {"to": "giulia", "handoff": {"from_name": "Marta"}}})
    rows = [("D1", "x"), ("D2", "y"), ("D3", "z")]
    keep = lambda view: [d for d, _ in rows if web.in_view(view, store.get(d), "marta")]  # noqa: E731
    assert keep("mine") == ["D1"] and keep("unassigned") == ["D3"] and keep("all") == ["D1", "D2", "D3"]
    assert web.owner_tag(TEAM, store.get("D2")) == "Giulia · passed by Marta"
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
    saved, web.team_for = web.team_for, lambda did: team_mod.of(None)
    try:
        solo = web.inbox_page("demo")
    finally:
        web.team_for = saved
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
        assert "Sent by Giulia" in sent and "Marta suggests" not in sent and "Giulia's case." in sent
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


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
