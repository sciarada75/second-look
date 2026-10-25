"""Bookbox, the made-up bookkeeping stand-in: it keeps the money events Second Look posts, JSON only, and shows
them on one page, escaped. Run: python3 tests/test_bookbox.py"""
import os
import sys
import tempfile
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bookbox import app as bookbox  # noqa: E402


def test_bookbox_takes_json_money_events_only_and_shows_them_escaped():
    box = bookbox.Bookbox(Path(tempfile.mkdtemp()) / "r.jsonl")
    assert not box.add({"event": "answer.sent"}) and not box.add(["x"])
    assert box.add({"event": "money", "kind": "<script>refund</script>", "amount": 5})
    assert "&lt;script&gt;refund&lt;/script&gt;" in box.page() and "<script>refund" not in box.page()
    assert "a made-up bookkeeping stand-in, not a real product" in box.page() and "credit note" in box.page()


def test_bookbox_hears_only_second_look_s_json_and_with_a_key_only_its_key():
    box = bookbox.Bookbox(Path(tempfile.mkdtemp()) / "r.jsonl")
    handler = type("H", (bookbox.Handler,), {"box": box})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        def post(body, ctype="application/json", path="/hooks/secondlook"):
            con = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
            con.request("POST", path, body=body, headers={"Content-Type": ctype})
            return con.getresponse().status
        assert post('{"event": "money", "kind": "refund"}') == 204 and post("x", "text/plain") == 415
        assert post("{nope") == 400
        os.environ["BOOKBOX_HOOK_KEY"] = "k1"
        try:
            assert post('{"event": "money", "kind": "refund"}') == 403
            assert post('{"event": "money", "kind": "refund"}', path="/hooks/secondlook?key=k1") == 204
        finally:
            del os.environ["BOOKBOX_HOOK_KEY"]
        assert len(box.received()) == 2 and box.received()[0]["kind"] == "refund"
    finally:
        srv.shutdown()


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
