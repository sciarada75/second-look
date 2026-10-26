"""The inquiry eval: requests by email, form or phone with known answers, judged on the same path as the
case page (judge, then the guard), and the demo's shipped inquiry reviews. No model call, no key.
Run: python3 tests/test_eval_inquiries.py"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from secondlook import __main__ as cli, judge, web  # noqa: E402
from secondlook.judge import Judgment  # noqa: E402
sys.path.insert(0, str(ROOT / "tests"))
from test_inquiry import morning  # noqa: E402  the demo's real data, its state in a temporary folder, no paid call

INQ = ROOT / "cases" / "inquiries"


def _set():
    return [json.loads(f.read_text()) for f in sorted(INQ.glob("IQ-*.json"))]


def test_the_set_is_written_by_its_generator_and_never_drifts():
    before = {f.name: f.read_bytes() for f in INQ.glob("IQ-*.json")}
    subprocess.run([sys.executable, str(INQ / "make_inquiries.py")], check=True, capture_output=True)
    after = {f.name: f.read_bytes() for f in INQ.glob("IQ-*.json")}
    assert before == after and len(after) == 9


def test_every_case_has_one_known_answer_an_inquiry_can_give():
    cs = _set()
    assert len({c["dispute"]["dispute_id"] for c in cs}) == len(cs)
    for c in cs:
        t = c["ground_truth"]
        assert t["action"] in judge.INQUIRY_ACTIONS and t["why"], c["dispute"]["dispute_id"]
        assert c["dispute"]["reason"] == "SHOP_INQUIRY" and "order_amount" in c["seller_records"]
    kinds = {c["ground_truth"]["action"] for c in cs}
    assert {"MESSAGE", "REFUND", "REPLACE", "PARTIAL_REFUND"} <= kinds
    # the spec's four (delivered and left with a neighbour, refund owed, exchange in terms, premature) are in
    why = " ".join(c["ground_truth"]["why"] for c in cs).lower()
    assert all(w in why for w in ("neighbour", "no refund on record", "exchange", "premature"))


def test_the_case_shape_is_the_one_the_case_page_gives_the_judge():
    # same keys as web.inquiry_case on a demo inquiry: the eval measures what the page runs
    with morning():
        live = web.inquiry_case("DEMO-C001")
    for c in _set():
        assert set(c) - {"ground_truth"} == set(live)
        assert set(live["inquiry"]) == set(c["inquiry"])
        assert set(live["dispute"]) <= set(c["dispute"])


def test_one_path_for_the_page_and_the_eval_and_defend_is_never_an_inquiry_answer():
    c = _set()[0]
    policy = cli.load_policy()
    old = judge.INQUIRY_BACKENDS["fake"] = lambda case: Judgment("DEFEND", 0.9, "x", [], "y")
    try:
        d = cli.review_inquiry_case(json.loads(json.dumps(c)), "fake", policy)
    finally:
        judge.INQUIRY_BACKENDS.pop("fake")
    assert d.action == "ASK_SELLER" and old
    d = cli.review_inquiry_case(json.loads(json.dumps(c)), "rules", policy)
    assert d.judgment.action == "MESSAGE"


def test_a_message_that_commands_the_assistant_never_moves_money():
    c = next(x for x in _set() if "SYSTEM:" in x["dispute"]["messages"][0]["content"])
    j = Judgment("REFUND", 0.95, "the customer says so", ["listing_text"], "Refunded.")
    from secondlook.guard import apply_policy
    d = apply_policy(j, cli.load_policy(), c["dispute"], c["seller_records"])
    assert d.action == "ASK_SELLER"


def test_a_refund_already_made_is_never_made_twice():
    c = next(x for x in _set() if x["seller_records"].get("already_refunded"))
    j = Judgment("REFUND", 0.95, "owed", ["return"], "Refunded.")
    from secondlook.guard import apply_policy
    d = apply_policy(j, cli.load_policy(), c["dispute"], c["seller_records"])
    assert d.action == "ASK_SELLER"


def test_eval_scores_both_sets_with_the_rules_baseline_and_no_key():
    out = io.StringIO()
    with morning(), contextlib.redirect_stdout(out):
        assert cli.main(["eval", "--judge", "rules"]) == 0
    text = out.getvalue()
    assert "PayPal disputes" in text and "Shop inquiries" in text
    assert text.count("IQ-0") == 9 and "refused what is owed" in text
    details = json.loads((ROOT / ".tmp" / "eval-rules-details.json").read_text())
    assert {d["case"] for d in details} >= {f"IQ-{n:03d}" for n in range(1, 10)}


def test_only_runs_the_cases_named_in_either_set():
    out = io.StringIO()
    with morning(), contextlib.redirect_stdout(out):
        cli.main(["eval", "--judge", "rules", "--only", "PP-D-001", "IQ-002"])
    text = out.getvalue()
    assert "PP-D-001" in text and "IQ-002" in text and "IQ-001" not in text and "PP-D-002" not in text


def test_a_shipped_review_of_a_demo_inquiry_is_found_like_a_disputes():
    with tempfile.TemporaryDirectory() as t:
        saved, shipped = web.REVIEWS, web.SHIPPED
        web.REVIEWS, web.SHIPPED = Path(t) / "mine", Path(t) / "shipped"
        web.SHIPPED.mkdir()
        try:
            (web.SHIPPED / "DEMO-C001.json").write_text("{}")
            assert web._review_file("DEMO-C001") == web.SHIPPED / "DEMO-C001.json" and web.is_shipped("DEMO-C001")
            assert web._review_file("C001") is None              # a live case never reads a shipped review
            (web.SHIPPED / "DEMO-H001.json").write_text("{}")
            assert web._review_file("DEMO-H001") is None          # history cases are never reviewed
        finally:
            web.REVIEWS, web.SHIPPED = saved, shipped


def test_a_return_back_at_the_shop_says_since_when():
    with morning():
        c = web.inquiry_case("DEMO-C002")
    assert c["seller_records"]["return"] == "Local courier LC90002RT, back at the shop (on 2026-10-20)"   # Lena's


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
