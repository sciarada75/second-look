"""The inquiry eval: requests by email, form or phone with known answers, made by the app's own path and judged
on the case page's own path (judge, then the guard); and the demo's shipped inquiry reviews. No model call, no key.
Run: python3 tests/test_eval_inquiries.py"""
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "cases" / "inquiries"))
from secondlook import __main__ as cli, judge, web  # noqa: E402
from secondlook.guard import apply_policy  # noqa: E402
from secondlook.judge import Judgment  # noqa: E402
from test_inquiry import morning  # noqa: E402  the demo's real data, its state in a temporary folder, no paid call
import make_inquiries  # noqa: E402

INQ = ROOT / "cases" / "inquiries"


def _set():
    return [json.loads(f.read_text()) for f in sorted(INQ.glob("IQ-*.json"))]


@contextlib.contextmanager
def no_env():
    """cli.main without reading .env: no key ever reaches this process."""
    kept = cli.load_dotenv
    cli.load_dotenv = lambda path: None
    try:
        yield
    finally:
        cli.load_dotenv = kept


def test_the_files_are_what_the_app_makes_today():
    # compared in memory: a stale file fails here, and is never quietly rewritten by the test
    made = make_inquiries.build()
    assert len(made) == 9 and made == {f.name: f.read_text() for f in INQ.glob("IQ-*.json")}


def test_every_case_has_one_known_answer_an_inquiry_can_give():
    cs = _set()
    assert len({c["dispute"]["dispute_id"] for c in cs}) == 9
    for c in cs:
        t = c["ground_truth"]
        assert t["action"] in judge.INQUIRY_ACTIONS and t["why"], c["dispute"]["dispute_id"]
        assert c["seller_records"]["order_no"], c["dispute"]["dispute_id"]       # every request found its order
    assert {"MESSAGE", "REFUND", "REPLACE"} <= {c["ground_truth"]["action"] for c in cs}
    assert {c["inquiry"]["channel"] for c in cs} == {"email", "form", "call"}
    # the spec's four (delivered and left with a neighbour, refund owed, exchange in terms, premature) are in
    why = " ".join(c["ground_truth"]["why"] for c in cs).lower()
    assert all(w in why for w in ("neighbour", "nothing has been refunded", "exchange", "premature"))


def test_the_judge_never_reads_the_answer():
    for c in _set():
        seen = []
        judge.INQUIRY_BACKENDS["peek"] = lambda case: seen.append(case) or Judgment("MESSAGE", 0.9, "x", [], "y")
        try:
            cli._eval_set("t", [c], lambda x: cli.review_inquiry_case(x, "peek", cli.load_policy()),
                          "MESSAGE", "o", "O", [])
        finally:
            judge.INQUIRY_BACKENDS.pop("peek")
        text = judge._inquiry_text(seen[0])
        assert "ground_truth" not in seen[0] and c["ground_truth"]["why"][:30] not in text


def test_the_page_and_the_eval_run_one_path():
    called = []
    with morning():
        kept = cli.review_inquiry_case
        cli.review_inquiry_case = lambda case, j, policy: called.append((case["inquiry"]["case_id"], j)) or "decision"
        try:
            assert web.review_inquiry("DEMO-C001", "rules") == "decision"
        finally:
            cli.review_inquiry_case = kept
    assert called == [("DEMO-C001", "rules")]


def test_defend_is_never_an_inquiry_answer():
    judge.INQUIRY_BACKENDS["fake"] = lambda case: Judgment("DEFEND", 0.9, "x", [], "y")
    try:
        d = cli.review_inquiry_case(json.loads(json.dumps(_set()[0])), "fake", cli.load_policy())
    finally:
        judge.INQUIRY_BACKENDS.pop("fake")
    assert d.action == "ASK_SELLER"


def test_a_message_that_commands_the_assistant_never_moves_money():
    c = next(x for x in _set() if "SYSTEM:" in x["dispute"]["messages"][0]["content"])
    d = apply_policy(Judgment("REFUND", 0.95, "the customer says so", ["listing_text"], "Refunded."),
                     cli.load_policy(), c["dispute"], c["seller_records"])
    assert d.action == "ASK_SELLER"


def test_a_refund_already_made_is_never_made_twice():
    c = next(x for x in _set() if x["seller_records"].get("already_refunded"))
    assert c["dispute"]["dispute_amount"]["value"] == "0.00"                  # nothing left of the order
    d = apply_policy(Judgment("REFUND", 0.95, "owed", ["return"], "Refunded."),
                     cli.load_policy(), c["dispute"], c["seller_records"])
    assert d.action == "ASK_SELLER"


def test_eval_scores_both_sets_with_the_rules_baseline_and_no_key():
    out = io.StringIO()
    with morning(), no_env(), contextlib.redirect_stdout(out):
        assert cli.main(["eval", "--judge", "rules"]) == 0
    text = out.getvalue()
    assert "PayPal disputes: 16" in text and "Shop inquiries: 9" in text
    assert text.count("IQ-0") == 9 and "refused what is owed" in text and "losing fights" in text
    details = json.loads((ROOT / ".tmp" / "eval-rules-details.json").read_text())
    assert {d["case"] for d in details} == {f"IQ-{n:03d}" for n in range(1, 10)} | {f"PP-D-{n:03d}" for n in range(1, 17)}


def test_only_runs_the_cases_named_and_never_writes_over_a_full_run():
    out = io.StringIO()
    full = ROOT / ".tmp" / "eval-rules-details.json"
    before = full.read_text() if full.exists() else None
    with morning(), no_env(), contextlib.redirect_stdout(out):
        cli.main(["eval", "--judge", "rules", "--only", "PP-D-001", "IQ-002"])
    text = out.getvalue()
    assert "PP-D-001" in text and "IQ-002" in text and "IQ-001" not in text and "PP-D-002" not in text
    assert (full.read_text() if full.exists() else None) == before
    assert len(json.loads((ROOT / ".tmp" / "eval-rules-only-details.json").read_text())) == 2


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


def test_a_return_back_at_the_shop_says_the_day_it_came_back():
    with morning():
        assert web.inquiry_case("DEMO-C002")["seller_records"]["return"] == \
            "Local courier LC90002RT, back at the shop (on 2026-10-20)"            # Lena's: the courier's day
        base = web.shop_orders

        def logged(day):
            def orders(src):
                os_ = base(src)
                for o in os_:
                    if o.get("order_no") == "LP-90002":
                        o["return"] = {**o["return"], "received_at_shop": day}
                return os_
            return orders
        web.shop_orders = logged("2026-10-22")       # the shop logged it two days late: the courier's day counts
        assert "(on 2026-10-20)" in web.inquiry_case("DEMO-C002")["seller_records"]["return"]
        web.shop_orders = logged("2026-10-19")       # the shop's own record is earlier: that day counts
        assert "(on 2026-10-19)" in web.inquiry_case("DEMO-C002")["seller_records"]["return"]


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
