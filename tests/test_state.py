"""Every case is in exactly one state, decided in one place (spec 2026-10-30, Part 1). Run: python3 tests/test_state.py"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secondlook import state  # noqa: E402

TODAY = date(2026, 10, 20)


def dispute(status="WAITING_FOR_SELLER_RESPONSE", stage="INQUIRY", messages=(), **more):
    return {"dispute_id": "D1", "create_time": "2026-10-19T11:00:00Z", "status": status,
            "dispute_life_cycle_stage": stage, "seller_response_due_date": "2026-11-08T11:00:00Z",
            "dispute_amount": {"value": "29.00", "currency_code": "EUR"},
            "disputed_transactions": [{"buyer": {"name": "Pablo García"}}],
            "messages": [{"posted_by": "BUYER", "time_posted": "2026-10-19T11:00:00.000Z", "content": "Stuck."},
                         *messages], **more}


def case(status="open", money=(), unconfirmed=None, dispute_id=None):
    c = {"id": "C1", "customer": {"name": "Margot Lefèvre"}, "status": status, "dispute_id": dispute_id,
         "money": list(money), "timeline": []}
    if unconfirmed:
        c["unconfirmed"] = unconfirmed
    return c


def test_a_paypal_inquiry_nobody_answered_is_your_move_until_paypal_s_date():
    s = state.of(None, dispute(), TODAY, holder="luca")
    assert (s["state"], s["whose"], s["until"], s["paypal"]) == ("your_move", "luca", date(2026, 11, 8), True)
    assert s["then"].startswith("Answer by 08 Nov") and s["label"] == "Your move"


def test_a_reply_on_an_inquiry_waits_for_the_customer_until_paypal_closes_it():
    s = state.of(None, dispute(), TODAY, answered_at="2026-10-20T05:52")
    assert (s["state"], s["whose"], s["until"]) == ("waiting_customer", "customer", date(2026, 11, 8))
    assert s["then"] == "If Pablo doesn't escalate by 8 Nov, PayPal closes the dispute."


def test_a_refund_waits_for_paypal_and_the_demo_s_confirmation_makes_it_done():
    s = state.of(None, dispute(), TODAY, answered_at="2026-10-20T05:52", money_sent=True)
    assert (s["state"], s["whose"]) == ("waiting_paypal", "paypal") and "Pablo" in s["why"]
    s = state.of(None, dispute(), TODAY, answered_at="2026-10-20T05:52", money_sent=True,
                 confirmed_at="2026-10-30T08:00")
    assert s["state"] == "done" and "demo: simulated" in s["why"]


def test_the_buyer_writing_after_the_answer_makes_it_your_move_again():
    later = {"posted_by": "BUYER", "time_posted": "2026-10-21T09:00:00.000Z", "content": "Still nothing."}
    s = state.of(None, dispute(messages=[later]), TODAY, answered_at="2026-10-20T05:52", holder="giulia")
    assert (s["state"], s["whose"], s["why"]) == ("your_move", "giulia", "Pablo wrote again.")


def test_paypal_s_own_statuses():
    assert state.of(None, dispute(status="UNDER_REVIEW", stage="CHARGEBACK"), TODAY)["state"] == "waiting_paypal"
    s = state.of(None, dispute(status="WAITING_FOR_BUYER_RESPONSE", stage="CHARGEBACK",
                               buyer_response_due_date="2026-10-30T00:00:00Z"), TODAY)
    assert (s["state"], s["until"]) == ("waiting_customer", date(2026, 10, 30))
    s = state.of(None, dispute(status="WAITING_FOR_BUYER_RESPONSE", buyer_response_due_date="2026-10-30T00:00:00Z"), TODAY)
    assert (s["state"], s["until"]) == ("waiting_customer", date(2026, 11, 8))
    assert state.of(None, dispute(status="RESOLVED"), TODAY)["state"] == "done"


def test_evidence_on_a_claim_leaves_the_decision_to_paypal():
    s = state.of(None, dispute(stage="CHARGEBACK"), TODAY, answered_at="2026-10-20T05:52")
    assert (s["state"], s["whose"]) == ("waiting_paypal", "paypal")


def test_a_shop_request_answered_waits_for_the_customer_until_it_closes_itself():
    s = state.of(case(), None, TODAY, answered_at="2026-10-20T05:41", closes_on=date(2026, 10, 23))
    assert (s["state"], s["until"], s["paypal"]) == ("waiting_customer", date(2026, 10, 23), False)
    assert s["then"] == "If Margot doesn't write, it closes itself on 23 Oct."


def test_a_request_kept_open_past_its_closing_day_is_your_move_and_says_so():
    s = state.of(case(), None, TODAY, answered_at="2026-10-20T05:41", closes_on=TODAY)
    assert s["state"] == "your_move"
    assert s["why"] == "It was due to close itself on 20 Oct; something kept it open: check it."
    assert s["then"] == "No PayPal deadline: this came to the shop, not to PayPal."


def test_a_shop_request_is_your_move_with_no_paypal_deadline_said_plainly():
    s = state.of(case(), None, TODAY)
    assert (s["state"], s["until"], s["why"]) == ("your_move", None, "Waiting for your answer.")
    assert s["then"] == "No PayPal deadline: this came to the shop, not to PayPal."
    assert state.of(case(), None, TODAY, answered_at="2026-10-20T05:41")["why"] == "Margot wrote again."


def test_what_keeps_a_shop_request_on_your_move_says_why():
    assert state.of(case(), None, TODAY, holder="giulia", handoff_from="Marta")["why"] == "Passed to you by Marta."
    assert "check the payment in PayPal" in state.of(case(unconfirmed=[{"amount": 9}]), None, TODAY)["why"]
    logged = case(money=[{"kind": "refund", "amount": 64.0}])
    assert state.of(logged, None, TODAY, answered_at="2026-10-20T05:41")["why"] == \
        "A refund is logged: mark it paid, then close the case."
    paid = case(money=[{"kind": "refund", "amount": 64.0, "status": "paid"}])
    assert state.of(paid, None, TODAY, answered_at="2026-10-20T05:41")["why"] == \
        "Refunded or replaced: close the case with what happened."


def test_a_review_out_of_date_is_your_move_unless_paypal_holds_the_move():
    s = state.of(None, dispute(), TODAY, answered_at="2026-10-20T05:52", money_sent=True, out_of_date=True)
    assert (s["state"], s["why"]) == ("your_move", "Changed since the last look: take a fresh look.")


def test_a_closed_case_is_done_whatever_its_dispute_says():
    assert state.of(case(status="closed"), dispute(), TODAY)["state"] == "done"


def test_an_answer_counts_only_at_the_stage_it_was_given():
    esc = dispute(stage="CHARGEBACK", seller_response_due_date="2026-11-20T00:00:00Z")
    s = state.of(None, esc, TODAY, answered_at="2026-10-20T05:52", answered_stage="INQUIRY")
    assert (s["state"], s["until"]) == ("your_move", date(2026, 11, 20))
    s = state.of(None, esc, TODAY, answered_at="2026-10-20T05:52", answered_stage="INQUIRY", money_sent=True)
    assert s["state"] == "your_move"


def test_a_claim_answer_counts_only_at_the_due_date_it_was_given():
    d = dispute(stage="CHARGEBACK", seller_response_due_date="2026-11-20T00:00:00Z")
    s = state.of(None, d, TODAY, answered_at="2026-10-20T05:52", answered_stage="CHARGEBACK",
                 answered_due="2026-11-20T00:00:00Z")
    assert s["state"] == "waiting_paypal"
    s = state.of(None, d, TODAY, answered_at="2026-10-20T05:52", answered_stage="CHARGEBACK",
                 answered_due="2026-11-10T00:00:00Z")
    assert s["state"] == "your_move"


def test_paypal_s_live_wait_for_the_buyer_wins_over_our_record():
    d = dispute(status="WAITING_FOR_BUYER_RESPONSE", stage="CHARGEBACK")
    assert state.of(None, d, TODAY, answered_at="2026-10-20T05:52")["state"] == "waiting_customer"


def test_a_dispute_on_the_case_that_was_not_loaded_is_said():
    s = state.of(case(dispute_id="PP-1"), None, TODAY)
    assert s["paypal"] is True and s["then"] == "A PayPal dispute is on this case: check it in PayPal."


def test_every_state_has_a_label():
    assert set(state.LABEL) == set(state.STATES)


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
