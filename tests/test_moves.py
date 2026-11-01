"""The moves: what fits each cause, what PayPal allows, and fixed texts that never promise money a move doesn't send
(spec 2026-10-30, Part 2). Run: python3 tests/test_moves.py"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secondlook import moves  # noqa: E402

FACTS = {"first": "Sophie", "carrier": "Local courier", "tracking": " (tracking LC90001IT)", "amount": "64.00 EUR",
         "order": "order LP-90001", "delivered": " on 15 Oct", "shop": "Linen & Paper"}


def test_the_cause_comes_from_paypal_s_reason_else_the_shop_s_case():
    assert moves.kind_of(None, {"reason": "CREDIT_NOT_PROCESSED"}) == "refund_missing"
    assert moves.kind_of({"problem": {"kind": "wrong_size"}}, None) == "wrong_size"
    assert moves.kind_of({"problem": {"kind": "something new"}}, None) == "question"


def test_at_most_two_others_that_fit_never_the_pick_never_a_defence_on_a_shop_request():
    assert moves.others("not_received", "REFUND", None, inquiry=False) == ["MESSAGE", "DEFEND"]
    assert moves.others("not_received", "MESSAGE", None, inquiry=True) == ["REFUND", "REPLACE"]
    assert moves.others("wrong_size", "REPLACE", None, inquiry=True) == ["RETURN", "REFUND"]
    assert moves.others("question", "MESSAGE", None, inquiry=True) == []


def test_only_what_paypal_allows_on_a_dispute():
    assert moves.others("not_received", "REFUND", {"DEFEND", "REFUND"}, inquiry=False) == ["DEFEND"]
    assert moves.others("not_as_described", "REFUND", set(), inquiry=False) == []


def test_no_text_promises_money_its_move_doesn_t_send():
    # The one exception: a defence after a refund the records say was paid speaks of that refund's proof (what PayPal
    # gets), and sends no money.
    proof = "we've shared the proof of that refund with PayPal"
    for kind in moves.FITS:
        for action in ("MESSAGE", "REPLACE", "DEFEND"):
            for inquiry in (True, False):
                for facts in ({}, FACTS, {**FACTS, "refund_paid": True}):
                    t = moves.text(action, kind, facts, inquiry=inquiry)
                    if action == "DEFEND" and facts.get("refund_paid"):
                        assert proof in t and "We refunded" in t, (kind, inquiry)
                        t = t.replace(proof, "").replace("We refunded", "")
                    assert not re.search(r"refund|money back|rimbors", t, re.I), (action, kind, inquiry, facts)
    assert "64.00 EUR" in moves.text("REFUND", "not_received", FACTS)


def test_a_defence_after_a_paid_refund_says_what_paypal_gets():
    t = moves.text("DEFEND", "not_received", {**FACTS, "refund_paid": True})
    assert t.startswith("Hi Sophie,\n\nWe refunded order LP-90001 already") and "shipping record" not in t
    assert "delivered" not in t and t.endswith("Linen & Paper")
    assert moves.then("DEFEND", {**FACTS, "refund_paid": True}, inquiry=False) == (
        "PayPal gets the proof of your refund and Sophie your reply. No money moves.")
    assert "shipping record" in moves.then("DEFEND", FACTS, inquiry=False)


def test_defence_text_claims_a_delivery_only_when_the_courier_recorded_one():
    t = moves.text("DEFEND", "not_received", {"first": "Sophie"})
    assert "shared our shipping record" in t and "delivered" not in t
    assert "was delivered on 15 Oct" in moves.text("DEFEND", "not_received", FACTS)


def test_a_dispute_and_a_shop_request_do_not_say_the_same_about_money_and_offers():
    d = moves.text("REPLACE", "not_as_described", FACTS, inquiry=False)
    assert "offered" in d and "accept" in d
    assert "We're refunding" in moves.text("REFUND", "question", FACTS, inquiry=True)
    assert "We've refunded" not in moves.text("REFUND", "question", FACTS, inquiry=True)
    r = moves.text("REFUND", "question", FACTS, inquiry=False)
    assert "We've refunded" in r and "through PayPal" in r


def test_an_unknown_action_never_borrows_a_reply_only_text():
    try:
        moves.text("PARTIAL_REFUND", "question", {})
    except KeyError:
        return
    raise AssertionError("expected KeyError")


def test_nothing_is_left_unfilled_or_awkward_when_facts_are_missing():
    for inquiry in (True, False):
        for kind in moves.FITS:
            for action in ("MESSAGE", "REFUND", "REPLACE", "DEFEND"):
                for s in (moves.text(action, kind, {}, inquiry=inquiry), moves.label(action, inquiry, {}),
                          moves.then(action, {}, inquiry=inquiry)):
                    assert "{" not in s and "for order your order" not in s, s
    assert moves.then("MESSAGE", {}, inquiry=True) == "The customer gets your reply. No money moves."


def test_a_paypal_reason_we_do_not_map_never_borrows_the_shop_case_s_kind():
    assert moves.kind_of({"problem": {"kind": "not_received"}}, {"reason": "UNAUTHORISED"}) == "question"


def test_texts_are_filled_with_the_case_s_facts_and_signed_by_the_shop():
    t = moves.text("MESSAGE", "not_received", FACTS)
    assert t.startswith("Hi Sophie,") and "Local courier" in t and "LC90001IT" in t and t.endswith("Linen & Paper")
    assert moves.text("MESSAGE", "question", {}).startswith("Hi there,")      # a fact missing: never a crash


def test_each_button_says_everything_it_sends_and_what_happens_next():
    assert moves.label("REFUND", False, FACTS) == "Answer and refund 64.00 EUR"
    assert moves.label("REPLACE", True, FACTS) == "Answer and exchange"
    assert moves.label("REPLACE", False, FACTS) == "Offer a replacement"
    assert moves.label("MESSAGE", False, FACTS) == "Reply only"
    assert moves.then("MESSAGE", FACTS, inquiry=True) == "Sophie gets your reply. No money moves."
    assert "PayPal" in moves.then("REFUND", FACTS, inquiry=False)


def test_refund_on_return_is_a_shop_request_s_move_and_never_once_the_item_is_back():
    # 31/10, Claudia: the shop's terms refund after the return, so "send it back first" comes before a refund
    assert moves.others("not_as_described", "MESSAGE", None, inquiry=True) == ["RETURN", "REFUND"]
    assert moves.others("wrong_size", "REPLACE", None, inquiry=True, returned=True) == ["REFUND", "MESSAGE"]
    for kind in moves.FITS:                                      # PayPal runs its own returns: never on a dispute
        for pick in ("MESSAGE", "REFUND", "REPLACE", "DEFEND"):
            assert "RETURN" not in moves.others(kind, pick, None, inquiry=False), (kind, pick)
            assert "RETURN" not in moves.others(kind, pick, {"REFUND", "REPLACE", "DEFEND"}, inquiry=False)
    assert not any("RETURN" in moves.others(k, "MESSAGE", None, inquiry=True)
                   for k in ("not_received", "refund_missing", "question"))
    try:
        moves.text("RETURN", "wrong_size", FACTS, inquiry=False)
    except KeyError:
        pass
    else:
        raise AssertionError("a dispute has no refund-on-return text")


def test_refund_on_return_asks_for_the_item_and_never_says_the_money_went():
    facts = {**FACTS, "window": " within 14 days", "refund_days": " within 5 days"}
    for kind in ("wrong_size", "not_as_described"):
        for f in (facts, FACTS, {}):
            t = moves.text("RETURN", kind, f, inquiry=True)
            assert "send it back" in t and "{" not in t, t
            assert not re.search(r"refunded|we're refunding|we are refunding|money back", t, re.I), t
    t = moves.text("RETURN", "wrong_size", facts, inquiry=True)
    assert "within 14 days" in t and "we'll refund 64.00 EUR within 5 days" in t and t.endswith("Linen & Paper")
    assert moves.label("RETURN", True, FACTS) == "Ask for it back, refund when it arrives"
    assert moves.then("RETURN", FACTS, inquiry=True) == (
        "Sophie gets your reply. No money moves now: the refund of 64.00 EUR is yours to send when the return "
        "reaches you.")
    back = moves.text("REFUND", "wrong_size", {**FACTS, "returned": True}, inquiry=True)
    assert "it has reached us" in back and "We're refunding 64.00 EUR" in back
    assert "reached us" not in moves.text("REFUND", "wrong_size", FACTS, inquiry=True)


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
