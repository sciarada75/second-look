"""An answered shop request closes itself, as solved before any dispute, once the customer stays quiet for the shop's
days (policy.json "close_answered_after_days", 3). Code, not AI. Run: python3 tests/test_closing.py"""
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from secondlook import cases as cases_mod, web  # noqa: E402
from test_inquiry import morning  # noqa: E402  the demo's real data, its state in a temporary folder, no paid call


@contextmanager
def on_day(d):
    """The shop's today, moved: the demo's is 20 Oct."""
    kept = web.shop_today
    web.shop_today = lambda src: d
    try:
        yield
    finally:
        web.shop_today = kept


def case(*entries, **extra):
    return {"id": "C1", "status": "open", "dispute_id": None, "money": [], "customer": {"name": "Ann Lee"},
            "timeline": [{"at": at, "direction": way, "channel": "email", "text": "…"} for at, way in entries], **extra}


def test_the_day_it_closes_is_days_after_the_shop_s_reply_when_that_reply_is_the_last_word():
    c = case(("2026-10-20T07:40", "in"), ("2026-10-20T07:41", "out"))
    assert cases_mod.closes_on(c, 3) == date(2026, 10, 23)
    assert cases_mod.closes_on(case(("2026-10-20T07:40", "in"), ("2026-10-20T07:41", "out"), ("2026-10-21T09:00", "note")), 3) \
        == date(2026, 10, 23)                                                  # a note is nobody's word
    assert cases_mod.closes_on(case(("2026-10-20T07:40", "in")), 3) is None                      # not answered yet
    assert cases_mod.closes_on(case(("2026-10-20T07:40", "in"), ("2026-10-20T07:41", "out"),
                                    ("2026-10-21T09:00", "in")), 3) is None                      # the customer wrote again
    assert cases_mod.closes_on(case(("2026-10-20T07:40", "in"), ("2026-10-20T07:41", "out"), dispute_id="D1"), 3) is None
    assert cases_mod.closes_on(case(("2026-10-20T07:40", "in"), ("2026-10-20T07:41", "out"),
                                    money=[{"kind": "refund", "amount": 5.0}]), 3) is None       # a person closes those
    assert cases_mod.closes_on(case(("2026-10-20T07:40", "in"), ("2026-10-20T07:41", "out"), status="closed"), 3) is None


def test_margot_s_answered_request_closes_itself_on_the_third_quiet_day_signed():
    with morning():
        assert web.close_quiet("demo") == []                                   # the demo's today: 20 Oct
        with on_day(date(2026, 10, 22)):
            assert web.close_quiet("demo") == []                               # two quiet days: still open
        with on_day(date(2026, 10, 23)):
            assert web.close_quiet("demo") == ["DEMO-C004"]
            assert web.close_quiet("demo") == []                               # once
        c = web.case_store("demo").get("DEMO-C004")
        assert (c["status"], c["outcome"], c["closed_by"]) == ("closed", "solved", "Second Look")
        assert c["closed_at"]
        note = c["timeline"][-1]
        assert (note["direction"], note["by"], note["text"]) == ("note", "Second Look",
                                                                 "Closed by Second Look: no reply in 3 days.")
        assert "Closed: solved before any dispute" in web.case_file_page("DEMO-C004", me="giulia")   # as a person's close reads


def test_the_shop_s_setting_sets_the_days():
    kept = web._policy
    try:
        web._policy = lambda: {**kept(), "close_answered_after_days": 5}
        assert web.quiet_days() == 5
        for bad in (0, -2, "3", 2.5, True, None):
            web._policy = lambda: {**kept(), "close_answered_after_days": bad}
            assert web.quiet_days() == 3, bad
    finally:
        web._policy = kept
    with morning():                                                            # the rules page reads the demo's state
        assert "after 3 days with no word from the customer" in web.rules_page(demo=True, me="giulia")


def test_a_look_at_the_shop_closes_what_is_due_and_the_customer_s_next_message_opens_a_new_case():
    with morning():
        assert "Answered · closes on 23 Oct if Margot doesn&#x27;t write" in web.case_file_page("DEMO-C004", me="giulia")
        with on_day(date(2026, 10, 23)):
            web.today_view("demo")                                             # the morning screen's look closes it
        assert web.case_store("demo").get("DEMO-C004")["status"] == "closed"
        code, out = web.receive("demo", {"channel": "email", "from": {"name": "Margot Lefèvre",
                                                                     "email": "margot.lefevre@example.com"},
                                         "text": "The napkins never came. Order LP-90003.", "source_id": "test:margot2"})
        assert code == 201 and out["case_id"] != "DEMO-C004"
        assert web.case_store("demo").get(out["case_id"])["earlier_case"] == "DEMO-C004"


def test_the_customer_writing_before_the_day_keeps_it_open():
    with morning():
        web.case_store("demo").add("DEMO-C004", cases_mod.entry("2026-10-21T08:00", "email", "in", "Still nothing?",
                                                               "Margot Lefèvre"))
        with on_day(date(2026, 10, 30)):
            assert web.close_quiet("demo") == []
        assert web.case_store("demo").get("DEMO-C004")["status"] == "open"


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
