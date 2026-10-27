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


def test_the_numbers_page_compares_like_for_like_and_keeps_snapshots_apart():
    with morning():
        html_ = web.numbers_page("demo", "giulia")
        for words in ("October so far (1–20 Oct) against the same days of September (1–20 Sep)",
                      "Requests, every channel", "per 100 orders", "Solved before any PayPal dispute",
                      "Answered by Second Look&#x27;s AI on its own", "Staff time", "Money given back",
                      "PayPal dispute fees", "Requests, week by week", "Right now",
                      "Open cases could still cost at most 1,109.00 EUR", "PayPal's high-volume line",
                      "PayPal disputes, last 90 days",
                      'href="/books.csv?month=2026-10&shop=demo">Export for accounting (CSV, October 2026)',
                      'href="/numbers?by=week&shop=demo">This week', 'href="/?shop=demo">Disputes and requests'):
            assert words in html_, words
        nav = html_.split("<nav>")[1].split("</nav>")[0]
        assert '<a href="/numbers?shop=demo" aria-current="page">Numbers</a>' in nav
        week = web.numbers_page("demo", "giulia", "week")
        assert "This week so far (19–20 Oct) against the same days last week (12–13 Oct)" in week
        kept = web.records_from
        web.records_from = lambda src: date(2026, 10, 1)
        try:
            assert "no record yet" in web.numbers_page("demo", "giulia")
        finally:
            web.records_from = kept


def test_the_change_column_says_which_way_and_by_how_much():
    assert web._change(5, 3, "n", "EUR") == "+2" and web._change(3, 5, "n", "EUR") == "−2"
    assert web._change(3, 3, "n", "EUR") == "same"
    assert web._change(10.5, 30.0, "money", "EUR") == "−19.50 EUR"
    assert web._change(150, 120, "min", "EUR") == "+30 min"
    assert web._change(138.57, 138.6, "min", "EUR") == "same"               # whole minutes, as the cells show them
    assert web._change(6.4, 5.6, "min", "EUR") == "same" and web._change(0.57, 0, "min", "EUR") == "+1 min"
    assert web._span(date(2026, 10, 1), date(2026, 10, 20)) == "1–20 Oct"
    assert web._span(date(2026, 9, 28), date(2026, 10, 4)) == "28 Sep–4 Oct"


def test_an_old_overview_link_lands_on_numbers():
    with morning():
        srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            con = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            con.request("GET", "/overview?shop=demo")
            r = con.getresponse()
            r.read()
            assert r.status == 303 and r.getheader("Location") == "/numbers?shop=demo"
            con.request("GET", "/numbers?shop=demo&by=week")
            r = con.getresponse()
            assert r.status == 200 and "This week so far" in r.read().decode()
            con.request("GET", "/numbers?practice=1")
            r = con.getresponse()
            r.read()
            assert r.status == 303 and r.getheader("Location") == "/?practice=1"
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
