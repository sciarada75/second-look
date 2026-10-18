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


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
