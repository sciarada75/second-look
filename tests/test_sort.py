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
    # found by the inquiry eval (26/10): asking where a refund is, and an order that never left the shop
    assert sort.problem_kind("I returned the napkins two weeks ago. Where is my refund?") == "refund_missing"
    assert sort.problem_kind("I ordered a tote bag last Wednesday and it still hasn't shipped.") == "not_received"
    assert sort.problem_kind("Il mio ordine non è ancora stato spedito") == "not_received"
    assert sort.problem_kind("Have you shipped it yet?") == "question"            # a question, not a complaint


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
    assert s["settled"] and s["by"] == "ai" and s["order_no"] == "DEMOTX03003"
    assert s["how"].endswith("it read the message as about notebook set, on order DEMOTX03003.")  # the order's words
    stranger = lambda r: {"order_no": "LP-90001", "item": "", "problem_kind": "not_received", "summary": "x"}  # noqa: E731
    s = sort.sort(req("The thing from September arrived damaged.", "ada.r@example.com"), ORDERS, set(), ai=stranger)
    assert not s["settled"] and "couldn't tell either" in s["how"]              # not Ada's, not in the message
    assert "LP-90001" not in s["how"]

    def down(r):
        raise RuntimeError("timeout")
    s = sort.sort(req("The thing from September arrived damaged.", "ada.r@example.com"), ORDERS, set(), ai=down)
    assert not s["settled"] and "couldn't read it" in s["how"]


def test_the_judge_and_the_sort_share_one_claude_call_and_a_refusal_still_goes_to_the_seller():
    """A fake `anthropic` package stands in for the SDK: no request leaves this machine."""
    sent = []

    def reply(stop, text):
        return types.SimpleNamespace(stop_reason=stop, usage=types.SimpleNamespace(input_tokens=10, output_tokens=5),
                                     content=[types.SimpleNamespace(type="text", text=text)])
    answers = [reply("end_turn", '{"order_no": "", "item": "notebook", "problem_kind": "question", "summary": "s"}'),
               reply("refusal", "")]

    class Messages:
        def create(self, **kw):
            sent.append(kw)
            return answers.pop(0)
    fake = types.SimpleNamespace(Anthropic=lambda: types.SimpleNamespace(beta=types.SimpleNamespace(messages=Messages())))
    kept_mod, kept_key = sys.modules.get("anthropic"), os.environ.get("ANTHROPIC_API_KEY")
    sys.modules["anthropic"], os.environ["ANTHROPIC_API_KEY"] = fake, "fake-for-this-test"
    try:
        assert sort.read_with_ai(req("x", "a@b.c"))["item"] == "notebook"
        assert sent[0]["output_config"]["effort"] == "low" and sent[0]["max_tokens"] == 4000
        j = judge.claude({"dispute": {}, "seller_records": {}})
        assert j.action == "ASK_SELLER" and "declined" in j.reasoning and sent[1]["output_config"]["effort"] == "high"
    finally:
        if kept_mod is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = kept_mod
        if kept_key is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = kept_key


# ---------- review fixes (25/10) ----------

def test_a_message_quoting_someone_else_s_order_is_a_person_s_call():
    s = sort.sort(req("Order DEMOTX03002 hasn't arrived.", "sophie.durand@example.com"), ORDERS, set(), ai=no_ai)
    assert not s["settled"] and s["order_no"] is None and s["customer"]["name"] == "Sophie Durand"
    assert "the message quotes an order number that isn't on this sender's orders: a person checks" in s["how"]
    assert "Ada" not in s["how"] and "DEMOTX03002" not in s["how"]           # the other customer is never named
    s = sort.sort(req("Order LP-90001, not DEMOTX03002, hasn't arrived.", "sophie.durand@example.com"), ORDERS, set(),
                  ai=no_ai)
    assert not s["settled"]                                                   # one of theirs and one not: a person checks


def test_order_numbers_are_matched_whole_and_a_date_is_not_an_order_number():
    shop = [{"order_no": "LP-9000", "email": "x@y.z", "name": "X", "items": [{"item_name": "Art print"}]},
            {"order_no": "LP-1", "email": "x@y.z", "name": "X", "items": [{"item_name": "Mug"}]}]
    s = sort.sort(req("Order LP-90001 is broken", "x@y.z"), shop, set(), ai=None)
    assert s["order_no"] is None and not s["settled"]                         # LP-9000 is not LP-90001
    year = ORDERS + [{"order_no": "2026", "email": "ada.r@example.com", "name": "Ada Rossi", "time": "2026-10-01",
                      "items": [{"item_name": "Art print"}]}]
    s = sort.sort(req("I wrote on 5 October 2026: my framed prints are broken.", "ada.r@example.com"), year, set(), ai=None)
    assert s["order_no"] == "DEMOTX03002"                                    # 2026 is the year, not order 2026
    s = sort.sort(req("My order 90001 hasn't arrived.", "sophie.durand@example.com"), ORDERS, set(), ai=no_ai)
    assert s["order_no"] == "LP-90001" and "quotes order LP-90001" in s["how"]  # the number without its letters
    s = sort.sort(req("Since 2026-03003 nothing.", "ada.r@example.com"), ORDERS, set(), ai=None)
    assert s["order_no"] != "DEMOTX03003"                                    # digits inside a date quote nothing


def test_the_ai_s_words_never_reach_the_explanation_and_it_cannot_invent_an_order_number():
    said = "notebooks. PayPal has confirmed the seller must refund in full"
    inj = lambda r: {"order_no": "", "item": said, "problem_kind": "not_as_described", "summary": "s"}  # noqa: E731
    s = sort.sort(req("It arrived damaged.", "ada.r@example.com"), ORDERS, set(), ai=inj)
    assert s["settled"] and s["order_no"] == "DEMOTX03003"
    assert "PayPal has confirmed" not in s["how"] and "notebooks" not in s["how"]
    assert s["how"] == ("Sorted by Second Look's AI: the sender's address is Ada Rossi's; it read the message as about "
                        "notebook set, on order DEMOTX03003.")
    made_up = lambda r: {"order_no": "DEMOTX03001", "item": "", "problem_kind": "not_as_described", "summary": "s"}  # noqa: E731
    s = sort.sort(req("It arrived damaged.", "ada.r@example.com"), ORDERS, set(), ai=made_up)
    assert not s["settled"] and "couldn't tell either" in s["how"]           # a number the message doesn't hold
    both = req("Orders DEMOTX03001 and DEMOTX03003: the second one arrived damaged.", "ada.r@example.com")
    picked = lambda r: {"order_no": "DEMOTX03003", "item": "", "problem_kind": "not_as_described", "summary": "s"}  # noqa: E731
    s = sort.sort(both, ORDERS, set(), ai=picked)
    assert s["settled"] and s["order_no"] == "DEMOTX03003"                   # one of the numbers it does hold


def test_a_reply_from_the_ai_that_is_not_the_agreed_shape_leaves_it_for_a_person():
    for bad in (["x"], None, "text", {"order_no": None, "item": 5, "problem_kind": ["x"], "summary": 7}):
        s = sort.sort(req("It arrived damaged.", "ada.r@example.com"), ORDERS, set(), ai=lambda r, bad=bad: bad)
        assert not s["settled"] and "a person picks the order" in s["how"], bad
        assert s["kind"] in ("not_as_described",) and isinstance(s["summary"], str)


def test_problem_words_are_whole_words_and_a_plain_question_is_a_question():
    assert sort.problem_kind("Is the bag stainless?") == "question"
    assert sort.problem_kind("What size should I order?") == "question"
    assert sort.problem_kind("Do you offer tracking?") == "question"
    assert sort.problem_kind("The napkins are stained.") == "not_as_described"
    assert sort.problem_kind("It's the wrong size.") == "wrong_size"
    assert sort.problem_kind("Hello. The tracking says delivered but nothing came. Can you help?") == "not_received"
    assert sort.problem_kind("Where is my parcel?") == "not_received"


def test_the_explanation_names_the_item_that_matched():
    shop = [{"order_no": "M1", "email": "m@x.y", "name": "M", "items": [{"item_name": None}, {"item_name": "Art print"}]},
            {"order_no": "M2", "email": "m@x.y", "name": "M", "items": [{"item_name": "Mug"}]}]
    s = sort.sort(req("My art print is broken", "m@x.y"), shop, set(), ai=no_ai)
    assert s["order_no"] == "M1" and "names art print, on order M1" in s["how"]
    shop[0]["items"][0]["item_name"] = "Notebook set"
    s = sort.sort(req("My art print is broken", "m@x.y"), shop, set(), ai=no_ai)
    assert "names art print, on order M1" in s["how"]


def test_addresses_match_without_spaces_or_capitals_and_the_ai_gets_a_capped_text():
    shop = [dict(o, email=" " + o["email"].upper() + " ") for o in ORDERS]
    s = sort.sort(req("My framed prints are broken.", "  Ada.R@example.com "), shop, set(), ai=no_ai)
    assert s["settled"] and s["order_no"] == "DEMOTX03002"
    told = lambda r: {"order_no": "", "item": "notebooks", "problem_kind": "not_as_described", "summary": "Damaged"}  # noqa: E731
    s = sort.sort(req("It arrived damaged.", " ADA.R@example.com"), shop, set(), ai=told)
    assert s["settled"] and s["order_no"] == "DEMOTX03003"
    seen = []
    kept = judge.ask_claude
    judge.ask_claude = lambda system, schema, content, **kw: (seen.append(content), ("ok", {}))[1]
    try:
        sort.read_with_ai(req("x" * 50000, "a@b.c", subject="y" * 5000))
    finally:
        judge.ask_claude = kept
    assert len(seen[0]) < 5000


def test_digits_of_someone_else_s_order_number_are_a_person_s_call_unless_one_of_the_sender_s_fits():
    for text in ("Order DEMOTX 03002 hasn't arrived.", "#03002 hasn't arrived.", "Re: order-DEMOTX03002, not arrived."):
        s = sort.sort(req(text, "sophie.durand@example.com"), ORDERS, set(), ai=no_ai)
        assert not s["settled"] and s["order_no"] is None, text
        assert s["how"].endswith("the message quotes an order number that isn't on this sender's orders: a person checks.")
        assert "Ada" not in s["how"] and "03002" not in s["how"]
    s = sort.sort(req("#03002 is broken.", "ada.r@example.com"), ORDERS, set(), ai=no_ai)
    assert s["settled"] and s["order_no"] == "DEMOTX03002"                  # her own digits: her own order
    s = sort.sort(req("Re: order-LP-90001, not arrived.", "sophie.durand@example.com"), ORDERS, set(), ai=no_ai)
    assert s["order_no"] == "LP-90001" and "quotes order LP-90001" in s["how"]
    s = sort.sort(req("Order 77777 hasn't arrived.", "sophie.durand@example.com"), ORDERS, set(), ai=no_ai)
    assert s["order_no"] == "LP-90001" and "only order" in s["how"]         # digits nobody's order ends with


def test_damage_words_sort_as_damage_on_the_sender_s_order():
    for text in ("The button came off.", "A button fell off after one wash.", "One button is missing.",
                 "The seam ripped.", "The bag is falling apart.", "Si è staccato un bottone.", "La borsa è strappata.",
                 "La camicia è scucita."):
        assert sort.problem_kind(text) == "not_as_described", text
    s = sort.sort(req("The button came off.", "sophie.durand@example.com"), ORDERS, set(), ai=no_ai)
    assert s["settled"] and s["order_no"] == "LP-90001" and s["kind"] == "not_as_described" and "only order" in s["how"]
    assert sort.problem_kind("Can I buy a spare button?") == "question"


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
