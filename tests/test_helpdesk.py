"""Ticketbook shows Second Look from its API and decides nothing itself. Run: python3 tests/test_helpdesk.py"""
import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from helpdesk.secondlook_client import SecondLook, Unavailable  # noqa: E402


def fake_secondlook(routes):
    """A tiny local server answering fixed JSON per (method, path): stands in for Second Look."""
    seen = []

    class H(BaseHTTPRequestHandler):
        def _answer(self, method):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"null") if n else None
            seen.append((method, self.path, body))
            code, data = routes.get((method, self.path.split("?")[0]), (404, {"error": "unknown"}))
            b = json.dumps(data).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

        def do_GET(self):
            self._answer("GET")

        def do_POST(self):
            self._answer("POST")

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}", seen


def test_the_client_reads_and_approves_through_the_api():
    srv, url, seen = fake_secondlook({
        ("GET", "/api/customers/dario.v@example.com"): (200, {"payer_id": "P1", "disputes": [{"dispute_id": "DEMO-031", "outcome": "Open"}]}),
        ("GET", "/api/disputes/DEMO-031"): (200, {"dispute_id": "DEMO-031", "review": {"mark": "abc"}}),
        ("POST", "/api/disputes/DEMO-031/approve"): (202, {"dispute_id": "DEMO-031", "result": "Passed to Giulia: ..."}),
    })
    try:
        sl = SecondLook(url)
        assert sl.customer("dario.v@example.com")["payer_id"] == "P1"
        assert sl.case("DEMO-031", as_person="marta")["review"]["mark"] == "abc"
        assert seen[-1][1] == "/api/disputes/DEMO-031?as=marta"
        code, text = sl.approve("DEMO-031", action="REFUND", message="Hello", by="marta", review="abc")
        assert code == 202 and text.startswith("Passed to Giulia")
        assert seen[-1][2] == {"action": "REFUND", "message": "Hello", "by": "marta", "review": "abc"}
        assert sl.customer("nobody@example.com") is None          # 404 = unknown customer, not an error
    finally:
        srv.shutdown()


def test_second_look_down_is_reported_not_raised_as_a_crash():
    sl = SecondLook("http://127.0.0.1:9")                          # nothing listens there
    try:
        sl.customer("x@example.com")
        assert False, "expected Unavailable"
    except Unavailable:
        pass


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
