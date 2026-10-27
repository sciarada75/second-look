"""Numbers: this week or month so far beside the same days of the one before (like for like), the weeks on record, and
what holds right now. One counting function (today.period) for all of it. Run: python3 tests/test_numbers.py"""
import json
import sys
import threading
from datetime import date
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from secondlook import web  # noqa: E402
from test_inquiry import morning  # noqa: E402

FLOWS = ("orders", "requests", "solved_before_dispute", "ai_answered", "answers", "minutes", "back", "fees")


def test_the_demo_s_own_records_begin_on_1_september():
    assert web.records_from("demo") == date(2026, 9, 1)


def test_october_so_far_beside_the_same_days_of_september():
    with morning():
        v = web.numbers_view("demo")
        a, b, m = v["this"], v["before"], v["month"]
        assert (v["by"], a["first"], a["last"], b["first"], b["last"]) == (
            "month", date(2026, 10, 1), date(2026, 10, 20), date(2026, 9, 1), date(2026, 9, 20))
        assert {k: a[k] for k in FLOWS} == {k: m[k] for k in FLOWS}          # this month: the same figures as before
        assert (m["requests"], m["solved_before_dispute"], m["ai_answered"]) == (65, 31, 1)
        assert (a["to"], b["to"]) == (None, "2026-09-21T00:00") and b["requests"] > 0
        assert [w["first"] for w in v["weeks"]][0] == date(2026, 9, 7) and len(v["weeks"]) == 7   # 31 Aug: before 1 Sep
        assert v["weeks"][-1]["so_far"] and not v["weeks"][-2]["so_far"]
        w = web.numbers_view("demo", "week")
        assert (w["by"], w["this"]["first"], w["before"]["first"], w["before"]["last"]) == (
            "week", date(2026, 10, 19), date(2026, 10, 12), date(2026, 10, 13))
        assert web.numbers_view("demo", "year")["by"] == "month"


def test_before_the_first_record_there_is_no_record_never_a_zero():
    with morning():
        kept = web.records_from
        web.records_from = lambda src: date(2026, 10, 1)
        try:
            v = web.numbers_view("demo")
        finally:
            web.records_from = kept
        assert v["before"] is None and all(w["first"] >= date(2026, 10, 1) for w in v["weeks"])
        assert web.records_from("live") is None                              # no case in the live shop here


def test_numbers_as_data_over_http():
    with morning():
        srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            con = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            con.request("GET", "/api/numbers?shop=demo&by=week")
            data = json.loads(con.getresponse().read())
            assert data["by"] == "week" and data["this"]["first"] == "2026-10-19" and data["month"]["requests"] == 65
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
