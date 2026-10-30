"""The moves: what fits each cause, what PayPal allows, and fixed texts that never promise money a move doesn't send
(spec 2026-10-30, Part 2). Run: python3 tests/test_moves.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secondlook import moves  # noqa: E402

FACTS = {"first": "Sophie", "carrier": "Local courier", "tracking": " (tracking LC90001IT)", "amount": "64.00 EUR",
         "order": "LP-90001", "delivered": " on 15 Oct", "shop": "Linen & Paper"}


def test_the_cause_comes_from_paypal_s_reason_else_the_shop_s_case():
    assert moves.kind_of(None, {"reason": "CREDIT_NOT_PROCESSED"}) == "refund_missing"
    assert moves.kind_of({"problem": {"kind": "wrong_size"}}, None) == "wrong_size"
    assert moves.kind_of({"problem": {"kind": "something new"}}, None) == "question"


def test_at_most_two_others_that_fit_never_the_pick_never_a_defence_on_a_shop_request():
    assert moves.others("not_received", "REFUND", None, inquiry=False) == ["MESSAGE", "DEFEND"]
    assert moves.others("not_received", "MESSAGE", None, inquiry=True) == ["REFUND", "REPLACE"]
    assert moves.others("wrong_size", "REPLACE", None, inquiry=True) == ["REFUND", "MESSAGE"]
    assert moves.others("question", "MESSAGE", None, inquiry=True) == []


def test_only_what_paypal_allows_on_a_dispute():
    assert moves.others("not_received", "REFUND", {"DEFEND", "REFUND"}, inquiry=False) == ["DEFEND"]
    assert moves.others("not_as_described", "REFUND", set(), inquiry=False) == []


def test_no_text_promises_money_its_move_doesn_t_send():
    for kind in moves.FITS:
        for action in ("MESSAGE", "REPLACE", "DEFEND"):
            assert "refund" not in moves.text(action, kind, FACTS).lower(), (action, kind)
    assert "64.00 EUR" in moves.text("REFUND", "not_received", FACTS)


def test_texts_are_filled_with_the_case_s_facts_and_signed_by_the_shop():
    t = moves.text("MESSAGE", "not_received", FACTS)
    assert t.startswith("Hi Sophie,") and "Local courier" in t and "LC90001IT" in t and t.endswith("Linen & Paper")
    assert moves.text("MESSAGE", "question", {}).startswith("Hi there,")      # a fact missing: never a crash


def test_each_button_says_everything_it_sends_and_what_happens_next():
    assert moves.label("REFUND", False, FACTS) == "Answer and refund 64.00 EUR"
    assert moves.label("REPLACE", True, FACTS) == "Answer and exchange"
    assert moves.label("MESSAGE", False, FACTS) == "Reply only"
    assert moves.then("MESSAGE", FACTS, inquiry=True) == "Sophie gets your reply. No money moves."
    assert "PayPal" in moves.then("REFUND", FACTS, inquiry=False)


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
