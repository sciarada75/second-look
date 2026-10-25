"""Bookbox, a made-up bookkeeping stand-in: what a shop's accounting system would receive from Second Look.

Bookbox is NOT a real product and imitates none. It shows the seam Decision 5 describes: Second Look sends the
facts of every money event it causes (refund logged, refund paid or cancelled, replacement, refund through PayPal),
live, as JSON to one address; the accounting system books them. Bookbox only keeps them and shows them on one page.
It never makes a credit note: that is the accountant's.

Every string it shows is HTML-escaped. Run:  python3 -m bookbox serve   ->  http://127.0.0.1:8767
Second Look sends here when started with SECONDLOOK_BOOKS_URL=http://127.0.0.1:8767/hooks/secondlook
"""
from __future__ import annotations

import hmac
import html
import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
e = html.escape
FIELDS = ["date", "kind", "order_no", "invoice_no", "amount", "currency", "fees", "item", "approved_by", "channel",
          "case_id", "dispute_id", "status"]
HEADS = {"date": "Date", "kind": "What", "order_no": "Order", "invoice_no": "Invoice", "amount": "Amount", "currency": "",
         "fees": "Fees", "item": "Item", "approved_by": "Approved by", "channel": "Channel", "case_id": "Case",
         "dispute_id": "PayPal dispute", "status": "Status"}


class Bookbox:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def add(self, payload) -> bool:
        """Keep one money event (one JSON line), with the time it arrived. Anything that isn't one is ignored."""
        if not (isinstance(payload, dict) and payload.get("event") == "money" and isinstance(payload.get("kind"), str)):
            return False
        line = {k: payload.get(k) for k in FIELDS} | {"received": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
        return True

    def received(self) -> list:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                x = json.loads(line)
            except ValueError:
                continue
            if isinstance(x, dict):
                out.append(x)
        return out

    def page(self) -> str:
        rows = "".join("<tr>" + "".join(f"<td>{e(str(x.get(k) if x.get(k) is not None else ''))}</td>" for k in FIELDS)
                       + "</tr>" for x in reversed(self.received()))
        head = "".join(f"<th>{e(HEADS[k])}</th>" for k in FIELDS)
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Bookbox</title>
<style>body{{margin:0;font:400 15px/1.5 Georgia,serif;background:#FBF8F1;color:#2B2A26}}
header{{padding:16px 28px;background:#2F4A3A;color:#F3EFE2}} header b{{font-size:20px}} header small{{display:block;opacity:.8}}
main{{padding:22px 28px}} table{{border-collapse:collapse;width:100%;background:#fff}}
th,td{{text-align:left;padding:7px 9px;border-bottom:1px solid #E2DccC;font-size:14px}} th{{background:#EFE9D9}}
.note{{color:#6B675C;max-width:70ch}}</style></head><body>
<header><b>Bookbox</b><small>a made-up bookkeeping stand-in, not a real product</small></header>
<main><h1>What Bookbox received from Second Look</h1>
<p class="note">Each line is one money event Second Look sent, newest first: the facts the books need. Bookbox makes no
credit note; that is the accountant's.</p>
<table><thead><tr>{head}</tr></thead><tbody>{rows or '<tr><td colspan="13">Nothing received yet.</td></tr>'}</tbody></table>
</main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    box: Bookbox = None  # set by serve()

    def _send(self, body: str, code: int = 200, ctype: str = "text/html; charset=utf-8"):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if urlparse(self.path).path == "/":
            return self._send(self.box.page())
        self._send("Not found", 404, "text/plain; charset=utf-8")

    def do_POST(self):
        u = urlparse(self.path)
        length = (self.headers.get("Content-Length") or "0").strip()
        if not length.isdigit():               # a length that isn't a number: no way to read the body
            self.close_connection = True
            return self._send("Content-Length must be a number of bytes.", 400, "text/plain; charset=utf-8")
        raw = self.rfile.read(min(int(length), 100_000))
        if u.path != "/hooks/secondlook":
            return self._send("Not found", 404, "text/plain; charset=utf-8")
        key = os.environ.get("BOOKBOX_HOOK_KEY")   # with a key set, Second Look's address must carry ?key=<it>
        if key and not hmac.compare_digest((parse_qs(u.query).get("key") or [""])[0].encode(), key.encode()):
            return self._send("Wrong or missing key.", 403, "text/plain; charset=utf-8")
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return self._send("Send JSON (Content-Type: application/json).", 415, "text/plain; charset=utf-8")
        try:
            payload = json.loads(raw or b"null")
        except ValueError:
            return self._send("Not JSON", 400, "text/plain; charset=utf-8")
        self.box.add(payload)
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):  # quiet terminal
        pass


def serve(port: int = 8767) -> None:
    Handler.box = Bookbox(ROOT / ".tmp" / "bookbox-received.jsonl")
    print(f"Bookbox: http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
