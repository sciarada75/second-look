"""The public demo (render.yaml): made-up data only, no keys, nothing a visitor can leave for the next one to read.
Run: python3 tests/test_hosted.py"""
import sys
import threading
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secondlook import web  # noqa: E402


@contextmanager
def hosted(on=True):
    kept = web.HOSTED
    web.HOSTED = on
    try:
        yield
    finally:
        web.HOSTED = kept


@contextmanager
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()


def post(port, path, headers=None, body=b""):
    conn = HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("POST", path, body=body, headers=headers or {})
    r = conn.getresponse()
    text = r.read().decode()
    conn.close()
    return r.status, text


def test_it_refuses_to_start_with_any_key_in_its_environment():
    assert web.hosted_problem({}) is None
    for key in ("PAYPAL_CLIENT_ID", "PAYPAL_SECRET", "ANTHROPIC_API_KEY"):
        assert key in web.hosted_problem({key: "x"})
    assert web.hosted_problem({"PAYPAL_CLIENT_ID": ""}) is None      # an empty value is no key


def test_only_the_demo_shop_can_be_asked_for():
    with hosted():
        assert web.asked_shop({"shop": ["live"]}) == "demo" and web.asked_shop({}) == "demo"
    with hosted(False):
        assert web.asked_shop({"shop": ["live"]}) == "live" and web.asked_shop({}) == ""


def test_the_shop_switch_offers_no_paypal_sandbox():
    with hosted():
        assert "your PayPal sandbox" not in web.shop_badge("demo") and "Practice cases" in web.shop_badge("demo")
    with hosted(False):
        assert "your PayPal sandbox" in web.shop_badge("demo")


def test_a_page_of_the_live_shop_is_simply_not_there():
    with hosted():
        assert "Test Store" in web.shop_badge("live") or web.shop_badge("live")     # never crashes: an error page uses it
    with hosted(), server() as port:
        for path in ("/d/PP-R-ABC-1", "/c/C-0001"):
            conn = HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", path)
            r = conn.getresponse()
            assert r.status == 404 and "public demo" in r.read().decode(), path
            conn.close()


def test_every_page_says_it_is_a_shared_public_demo():
    with hosted():
        assert web.HOSTED_NOTE in web.page("T", "", "<p>x</p>", demo=True)
    with hosted(False):
        assert web.HOSTED_NOTE not in web.page("T", "", "<p>x</p>", demo=True)


def test_a_visitor_can_leave_no_text_for_the_next_one():
    with hosted(), server() as port:
        for path in ("/api/requests", "/rules/add", "/rules/accept", "/rules/discard", "/rules/remove"):
            code, text = post(port, path, {"Content-Type": "application/json"}, b'{"text": "hello"}')
            assert code == 403 and "public demo" in text, (path, code, text)


def test_the_same_site_check_knows_its_public_address():
    site = {"Host": "second-look.onrender.com", "Origin": "https://second-look.onrender.com"}
    elsewhere = {"Host": "second-look.onrender.com", "Origin": "https://evil.example"}
    with hosted(), server() as port:
        assert post(port, "/nothing-here", site)[0] == 404             # past the check; no such page
        assert post(port, "/nothing-here", elsewhere)[0] == 403
    with hosted(False), server() as port:
        assert post(port, "/nothing-here", site)[0] == 403             # on your own machine: only your own machine


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
