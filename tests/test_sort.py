"""Second Look sorts a request by rules first, and asks its AI only what the rules can't settle.
Run: python3 tests/test_sort.py"""
import os
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secondlook import judge, sort  # noqa: E402

ORDERS = [
    {"order_no": "LP-90001", "email": "sophie.durand@example.com", "name": "Sophie Durand", "date": "2026-10-12",
     "time": "2026-10-12T18:40:00Z", "amount": 64.0, "paid_with": "card",
     "items": [{"item_name": "Linen tablecloth", "item_quantity": "1"}]},
    {"transaction_id": "DEMOTX00452", "email": "sofia.m@example.com", "name": "Sofia Moreau", "date": "2026-07-03",
     "time": "2026-07-03T10:00:00Z", "amount": 36.0, "items": [{"item_name": "Linen napkins", "item_quantity": "1"}]},
    {"transaction_id": "DEMOTX02070", "email": "sofia.m@example.com", "name": "Sofia Moreau", "date": "2026-10-06",
     "time": "2026-10-06T10:00:00Z", "amount": 36.0, "items": [{"item_name": "Linen napkins", "item_quantity": "1"}]},
    {"transaction_id": "DEMOTX03001", "email": "ada.r@example.com", "name": "Ada Rossi", "date": "2026-08-01",
     "time": "2026-08-01T10:00:00Z", "amount": 20.0, "items": [{"item_name": "Art print", "item_quantity": "1"}]},
    {"transaction_id": "DEMOTX03002", "email": "ada.r@example.com", "name": "Ada Rossi", "date": "2026-09-01",
     "time": "2026-09-01T10:00:00Z", "amount": 240.0, "items": [{"item_name": "Framed print set", "item_quantity": "1"}]},
    {"transaction_id": "DEMOTX03003", "email": "ada.r@example.com", "name": "Ada Rossi", "date": "2026-09-20",
     "time": "2026-09-20T10:00:00Z", "amount": 29.0, "items": [{"item_name": "Notebook set", "item_quantity": "1"}]},
]


def req(text, email, subject="", order=None):
    return {"channel": "email", "from": {"name": "", "email": email}, "subject": subject, "text": text, "order": order}


def no_ai(request):
    raise AssertionError("Second Look's AI must not be asked: the rules settle this")


def test_the_problem_is_read_from_the_words():
    assert sort.problem_kind("I sent the shirt back on 5 October. I still have no refund.") == "refund_missing"
    assert sort.problem_kind("The shirt is too small, I need an L") == "wrong_size"
    assert sort.problem_kind("One napkin has a pulled thread") == "not_as_described"
    assert sort.problem_kind("Wrong colour bag") == "not_as_described"
    assert sort.problem_kind("My framed prints haven't arrived") == "not_received"
    assert sort.problem_kind("Ciao, il mio ordine non è ancora arrivato") == "not_received"
    assert sort.problem_kind("Do you ship to Norway?") == "question"


def test_the_rules_sort_by_sender_then_order_number_open_case_item_or_only_order():
    s = sort.sort(req("Order LP-90001 hasn't arrived.", "Sophie.Durand@example.com"), ORDERS, set(), ai=no_ai)
    assert s["settled"] and s["by"] == "rules" and s["order_no"] == "LP-90001" and "quotes order LP-90001" in s["how"]
    s = sort.sort(req("It hasn't arrived.", "ada.r@example.com", order="DEMOTX03003"), ORDERS, set(), ai=no_ai)
    assert s["order_no"] == "DEMOTX03003"                                      # the form's order field counts
    s = sort.sort(req("One napkin has a pulled thread.", "sofia.m@example.com"), ORDERS, {"DEMOTX02070"}, ai=no_ai)
    assert s["order_no"] == "DEMOTX02070" and "open case" in s["how"]           # two napkin orders: the open one
    s = sort.sort(req("Any news?", "sofia.m@example.com"), ORDERS, {"DEMOTX02070"}, ai=no_ai)
    assert s["order_no"] == "DEMOTX02070"                                        # a follow-up joins the open case
    s = sort.sort(req("My framed prints are broken.", "ada.r@example.com"), ORDERS, set(), ai=no_ai)
    assert s["order_no"] == "DEMOTX03002" and "framed print set" in s["how"]    # "framed prints" fits it best
    s = sort.sort(req("It hasn't arrived.", "sophie.durand@example.com"), ORDERS, set(), ai=no_ai)
    assert s["order_no"] == "LP-90001" and "only order" in s["how"]
    s = sort.sort(req("Do you gift wrap?", "ada.r@example.com"), ORDERS, set(), ai=no_ai)
    assert s["settled"] and s["order_no"] is None and s["kind"] == "question"


def test_an_unknown_sender_is_a_person_s_call_even_with_an_ai():
    s = sort.sort(req("Order LP-90001 hasn't arrived. Sophie", "someone@else.example"), ORDERS, set(), ai=no_ai)
    assert not s["settled"] and s["customer"] is None and "a person picks the order" in s["how"]


def test_without_an_ai_key_what_the_rules_can_t_settle_waits_for_a_person():
    s = sort.sort(req("Something arrived damaged.", "ada.r@example.com"), ORDERS, set(), ai=None)
    assert not s["settled"] and s["customer"]["name"] == "Ada Rossi" and "No AI key is set" in s["how"]


def test_the_ai_reads_and_the_code_matches_its_facts_to_the_sender_s_own_orders():
    told = lambda r: {"order_no": "", "item": "notebooks", "problem_kind": "not_as_described", "summary": "Damaged"}  # noqa: E731
    s = sort.sort(req("The thing from September arrived damaged.", "ada.r@example.com"), ORDERS, set(), ai=told)
    assert s["settled"] and s["by"] == "ai" and s["order_no"] == "DEMOTX03003" and "Second Look's AI" in s["how"]
    stranger = lambda r: {"order_no": "LP-90001", "item": "", "problem_kind": "not_received", "summary": "x"}  # noqa: E731
    s = sort.sort(req("The thing from September arrived damaged.", "ada.r@example.com"), ORDERS, set(), ai=stranger)
    assert not s["settled"] and "couldn't tell either" in s["how"]              # not Ada's order: never tied to it

    def down(r):
        raise RuntimeError("timeout")
    s = sort.sort(req("The thing from September arrived damaged.", "ada.r@example.com"), ORDERS, set(), ai=down)
    assert not s["settled"] and "couldn't read it" in s["how"]

if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
