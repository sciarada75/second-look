"""The seller's screen: a small local web app over the same judge, guard and PayPal client.

    python3 -m secondlook serve            http://127.0.0.1:8765

Inbox → a dispute as a case file (the buyer's words, a timeline to scale, the evidence with its
sources) → "Take a second look" runs the judge (one model call, about $0.05) → the ten checks, the
recommendation, the guard's notes, a reply you can edit → Approve sends exactly what you saw.

A review is cached in .tmp/reviews/ so reloading never pays twice, and Approve executes the cached
decision: the seller approves what is on the screen, not a fresh answer.
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .guard import CHECKS, Decision, Judgment
from .paypal import MockPayPal, client_from_env

ROOT = Path(__file__).resolve().parent.parent
REVIEWS = ROOT / ".tmp" / "reviews"

REASON = {
    "MERCHANDISE_OR_SERVICE_NOT_RECEIVED": "Says it never arrived",
    "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED": "Says it's not as described",
    "CREDIT_NOT_PROCESSED": "Says the refund never came",
}
ACTION = {
    "DEFEND": "Defend with evidence", "REFUND": "Refund in full", "PARTIAL_REFUND": "Refund part",
    "REPLACE": "Send a replacement", "MESSAGE": "Reply only", "ASK_SELLER": "Your call",
}
ACTION_SAYS = {
    "DEFEND": "Your evidence goes to PayPal and the reply goes to the buyer.",
    "REFUND": "PayPal refunds the buyer in full and the reply goes with it.",
    "PARTIAL_REFUND": "PayPal offers the buyer the amount below.",
    "REPLACE": "PayPal tells the buyer a replacement is on its way.",
    "MESSAGE": "Only the reply is sent. No money moves.",
    "ASK_SELLER": "Nothing is sent. Read the checks and decide.",
}
RESULT = {
    "PASS": ("Favours you", "pass"), "FAIL": ("Favours the buyer", "fail"),
    "INCONSISTENT": ("Evidence doesn't add up", "incon"), "UNCLEAR": ("Not enough to tell", "unclear"),
    "NOT_APPLICABLE": ("Doesn't apply", "na"),
}
EVIDENCE_LABEL = {
    "order_date": "Ordered", "items": "Items", "ship_to": "Ships to", "tracking": "Tracking",
    "handling_time_promised": "Your promise", "return_policy": "Your returns policy",
    "listing_text": "Your listing", "fulfilment_status": "Status", "planned_ship_date": "Planned shipping",
    "packing_slip_qty": "Packing slip says", "shipment_weight_g": "Parcel weighed (g)",
    "unit_weight_g": "One item weighs (g)", "envelope_weight_g": "Empty envelope weighs (g)",
}

e = html.escape


# ---------- data ----------

def _client(dispute_id: str | None = None):
    if dispute_id and (ROOT / "cases" / f"{dispute_id}.json").exists():
        return MockPayPal(ROOT / "cases", ROOT / ".tmp" / "actions.jsonl")
    return client_from_env(ROOT)


def _case(dispute_id: str) -> dict:
    from .__main__ import load_case  # same loader as the CLI
    return load_case(_client(dispute_id), dispute_id)


def _saved(dispute_id: str):
    f = REVIEWS / f"{dispute_id}.json"
    if not f.exists():
        return None
    raw = json.loads(f.read_text())
    return Decision(action=raw["action"], reasons=raw["reasons"], judgment=Judgment(**raw["judgment"]),
                    overridden=raw["overridden"]), raw.get("sent")


def _save(dispute_id: str, d: Decision, sent=None) -> None:
    REVIEWS.mkdir(parents=True, exist_ok=True)
    (REVIEWS / f"{dispute_id}.json").write_text(json.dumps({**asdict(d), "sent": sent}, ensure_ascii=False))


def _t(iso):
    try:
        return datetime.strptime(str(iso)[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        try:
            return datetime.strptime(str(iso)[:10], "%Y-%m-%d")
        except ValueError:
            return None


def _gap(a: datetime, b: datetime) -> str:
    s = (b - a).total_seconds()
    if s < 3600:
        return f"{max(1, round(s / 60))} minutes later"
    if s < 2 * 86400:
        return f"{round(s / 3600)} hours later"
    return f"{round(s / 86400)} days later"


# ---------- pieces ----------

def timeline(case: dict) -> str:
    d, r = case["dispute"], case["seller_records"]
    tr = r.get("tracking") or {}
    points = [("Paid", _t(r.get("order_date") or (d.get("disputed_transactions") or [{}])[0].get("create_time"))),
              ("Dispute opened", _t(d.get("create_time"))),
              ("Shipped", _t(tr.get("shipped_date"))),
              ("Delivered" if tr.get("status") == "DELIVERED" else "Last tracking", _t(tr.get("last_update"))),
              ("Your reply due", _t(d.get("seller_response_due_date")))]
    points = sorted([p for p in points if p[1]], key=lambda p: p[1])
    if len(points) < 2:
        return ""
    t0, t1 = points[0][1], points[-1][1]
    span = max((t1 - t0).total_seconds(), 1)
    marks, prev, last_x = [], None, -100.0
    for label, t in points:
        x = 3 + 94 * (t - t0).total_seconds() / span
        lift = " lift" if x - last_x < 9 else ""  # two events close together: stagger the labels
        gap = f'<span class="gap">{e(_gap(prev, t))}</span>' if prev and label == "Dispute opened" else ""
        when = f"{t:%d %b}" if (t.hour, t.minute) == (0, 0) else f"{t:%d %b, %H:%M}"
        marks.append(f'<li class="mark{lift}{" hot" if gap else ""}" style="left:{x:.2f}%">'
                     f'<span class="lab"><b>{e(label)}</b><time>{when}</time>{gap}</span></li>')
        prev, last_x = t, x
    return f'<ol class="ruler" aria-label="Timeline">{"".join(marks)}</ol>'


def evidence(r: dict) -> str:
    src = r.get("sources", {})
    rows = []
    for k, label in EVIDENCE_LABEL.items():
        if k not in r and k not in src:
            continue
        v = r.get(k)
        if k == "items":
            v = ", ".join(f'{i["name"]} × {i["qty"]}' for i in v or [])
        elif k == "tracking":
            courier = v and (v.get("carrier_name_other") if v.get("carrier") == "OTHER" else v.get("carrier"))
            v = (f'{courier or "Courier"} {v.get("tracking_number")}, {v.get("status", "").lower()}'
                 if v else "none registered yet")
        elif k == "order_date":
            t = _t(v)
            v = f"{t:%d %b %Y, %H:%M}" if t else v
        tag = src.get(k, "practice case")
        tag = {"PayPal Transaction Search": "PayPal order", "seller's notes": "Your notes"}.get(tag, tag)
        tag = "Your shop terms" if tag.startswith("shop.json") else tag
        tag = "PayPal tracking" if tag.startswith("PayPal tracking") else tag
        rows.append(f'<div class="ev"><dt>{e(label)}</dt><dd>{e(str(v))}'
                    f'<span class="src">{e(tag)}</span></dd></div>')
    for k, why in (r.get("unavailable") or {}).items():
        rows.append(f'<div class="ev missing"><dt>{e(EVIDENCE_LABEL.get(k, k))}</dt><dd>{e(why)}</dd></div>')
    return f'<dl class="evidence">{"".join(rows)}</dl>'


def plain(text: str) -> str:
    """Guard notes are written with codes for the log; the seller reads words."""
    for code, word in sorted(ACTION.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"\b{code}\b", word.lower(), text)
    return (text.replace("INQUIRY stage", "inquiry stage").replace("CLAIM stage", "claim stage")
                .replace("PayPal does not allow", "PayPal doesn't allow"))


def first_sentences(text: str, n: int = 2):
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(parts[:n]), " ".join(parts[n:])


def checks(j: Judgment) -> str:
    rows = []
    for c in j.checks:
        word, cls = RESULT.get(c["result"], (c["result"], "na"))
        rows.append(f'<li class="check {cls}"><span class="res">{e(word)}</span>'
                    f'<b>{e(CHECKS.get(c["id"], c["id"]))}</b><q>{e(c["finding"])}</q></li>')
    return f'<ol class="checks">{"".join(rows)}</ol>'


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@1,6..72,400;1,6..72,500&family=Schibsted+Grotesk:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root{{--paper:#F5F6F2;--ink:#1E2935;--soft:#5B6672;--rule:#D5D9D2;--kraft:#B5874F;--kraft-bg:#F1E6D6;
--pass:#2E6A4E;--fail:#7B3D6A;--incon:#B07418;--unclear:#7D858E}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);font:400 17px/1.55 "Schibsted Grotesk",system-ui,sans-serif}}
a{{color:inherit}} :focus-visible{{outline:3px solid var(--kraft);outline-offset:2px}}
header.top{{display:flex;justify-content:space-between;align-items:baseline;padding:22px 56px;border-bottom:1px solid var(--rule)}}
.brand{{font-weight:700;font-size:20px;text-decoration:none}} .brand small{{font-weight:400;color:var(--soft);margin-left:10px}}
.mode{{color:var(--soft);font-size:15px}}
main{{max-width:1720px;margin:0 auto;padding:40px 56px 80px}}
q,blockquote,.quote{{font-family:Newsreader,Georgia,serif;font-style:italic}}
/* inbox */
.inbox{{list-style:none;padding:0;margin:0;max-width:1100px}}
.inbox li{{border-bottom:1px solid var(--rule)}}
.inbox a{{display:grid;grid-template-columns:1fr auto;gap:4px 32px;padding:24px 4px;text-decoration:none}}
.inbox blockquote{{grid-column:1}} .inbox .meta{{grid-column:1}}
.inbox a:hover blockquote{{text-decoration:underline;text-decoration-thickness:1px}}
.inbox blockquote{{margin:0;font-size:26px;line-height:1.3}}
.inbox .meta{{color:var(--soft);font-size:15px}} .inbox .amt{{grid-column:2;grid-row:1/3;align-self:center;font-weight:700;font-size:20px}}
.empty{{color:var(--soft);font-size:20px}}
h1.page{{font-size:36px;line-height:1.2;margin:0 0 6px}}
/* case */
.case{{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,6fr);gap:64px;align-items:start}}
.claim{{margin:0 0 6px;font-size:44px;line-height:1.15}} .claim::before{{content:"\\201C"}} .claim::after{{content:"\\201D"}}
.who{{color:var(--soft);margin:0 0 34px}}
.ruler{{position:relative;list-style:none;margin:30px 0 30px;padding:0;height:190px}}
.ruler::before{{content:"";position:absolute;left:0;right:0;top:95px;border-top:2px solid var(--ink)}}
.mark{{position:absolute;top:89px;width:0}}
.mark::before{{content:"";position:absolute;left:-7px;top:0;width:14px;height:14px;border-radius:50%;background:var(--ink)}}
.mark .lab{{position:absolute;left:0;top:24px;transform:translateX(-50%);width:170px;text-align:center}}
.mark.lift .lab{{top:auto;bottom:16px}}
.mark b{{display:block;font-size:15px}} .mark time{{display:block;font-size:14px;color:var(--soft)}}
.mark.hot::before{{background:var(--incon);box-shadow:0 0 0 5px #F3E3C4}}
.gap{{display:block;margin-top:2px;font-family:Newsreader,serif;font-style:italic;font-size:19px;color:var(--incon)}}
h2{{font-size:19px;margin:0 0 14px}}
.evidence{{margin:0}} .ev{{display:grid;grid-template-columns:150px 1fr;gap:12px;padding:10px 0;border-top:1px solid var(--rule)}}
.ev dt{{color:var(--soft)}} .ev dd{{margin:0}}
.src{{display:inline-block;margin-left:10px;padding:1px 8px;font-size:13px;background:var(--kraft-bg);color:#6E4F27;border-left:3px solid var(--kraft)}}
.ev.missing dd{{color:var(--incon)}}
/* second look */
.look{{border-left:1px solid var(--rule);padding-left:56px}}
.run button,.approve button{{font:700 19px "Schibsted Grotesk",sans-serif;padding:16px 28px;border:0;background:var(--ink);color:var(--paper);cursor:pointer}}
.run p{{color:var(--soft)}}
.checks{{list-style:none;padding:0;margin:0 0 30px}}
.check{{display:grid;grid-template-columns:190px 1fr;gap:2px 18px;padding:11px 0;border-top:1px solid var(--rule)}}
.check .res{{grid-row:1/3;font-weight:700;font-size:15px;padding-left:12px;border-left:4px solid}}
.check b{{font-weight:500}} .check q{{color:var(--soft);font-size:16px;quotes:none}}
.pass .res{{color:var(--pass);border-color:var(--pass)}} .fail .res{{color:var(--fail);border-color:var(--fail)}}
.incon .res{{color:var(--incon);border-color:var(--incon)}} .unclear .res,.na .res{{color:var(--unclear);border-color:var(--rule)}}
.verdict{{background:#fff;border:1px solid var(--rule);padding:28px 30px;margin-bottom:24px}}
.verdict h3{{margin:0;font-size:34px;line-height:1.2}} .verdict .conf{{color:var(--soft);font-size:15px;margin:4px 0 14px}}
.verdict p{{margin:0 0 10px;max-width:72ch}}
.verdict details{{margin:0 0 10px}} .verdict summary{{cursor:pointer;color:var(--soft)}}
.run button:disabled{{background:var(--soft);cursor:progress}}
.guard{{margin:14px 0 0;padding:12px 16px;background:#FBF3E4;border-left:4px solid var(--incon)}}
.guard b{{display:block;margin-bottom:4px}} .guard ul{{margin:0;padding-left:20px}}
label.reply{{display:block;font-weight:700;margin:22px 0 8px}}
textarea{{width:100%;min-height:210px;font:400 16px/1.5 "Schibsted Grotesk",sans-serif;padding:14px;border:1px solid var(--rule);background:#fff;color:var(--ink)}}
.approve{{display:flex;gap:18px;align-items:center;margin-top:16px}} .approve span{{color:var(--soft)}}
.sent{{padding:18px 22px;background:#E8F0EA;border-left:4px solid var(--pass);margin-bottom:24px}}
.sent b{{font-size:20px}}
.back{{display:inline-block;margin-bottom:26px;color:var(--soft)}}
@media (max-width:1100px){{.case{{grid-template-columns:1fr}} .look{{border:0;padding:0}} main,header.top{{padding-left:20px;padding-right:20px}}}}
@media (prefers-reduced-motion:no-preference){{.verdict,.checks{{animation:in .5s ease-out}} @keyframes in{{from{{opacity:0}}}}}}
</style></head><body>
<header class="top"><a class="brand" href="/">Second Look<small>Sell without fear.</small></a><span class="mode">{mode}</span></header>
<main>{body}</main></body></html>"""


def inbox_page(practice: bool) -> str:
    pp = MockPayPal(ROOT / "cases", ROOT / ".tmp" / "actions.jsonl") if practice else client_from_env(ROOT)
    items = []
    for state in (["REQUIRED_ACTION"] if practice else ["REQUIRED_ACTION", "REQUIRED_OTHER_PARTY_ACTION"]):
        items += pp.list_disputes(state)
    seen, rows = set(), []
    for d in items:
        if d["dispute_id"] in seen:
            continue
        seen.add(d["dispute_id"])
        full = d if practice else pp.get_dispute(d["dispute_id"])
        msg = next((m["content"] for m in full.get("messages", []) if m.get("posted_by") == "BUYER"), "")
        due = _t(full.get("seller_response_due_date"))
        waiting = "Waiting for the buyer" if full.get("status") == "WAITING_FOR_BUYER_RESPONSE" else (
            f"Reply by {due:%d %b}" if due else "")
        rows.append(f'<li><a href="/d/{e(d["dispute_id"])}"><blockquote>{e(msg)}</blockquote>'
                    f'<span class="amt">{e(d["dispute_amount"]["value"])} {e(d["dispute_amount"]["currency_code"])}</span>'
                    f'<span class="meta">{e(REASON.get(full.get("reason"), full.get("reason", "")))}. {e(waiting)}</span></a></li>')
    other = '<a href="/">Your PayPal disputes</a>' if practice else '<a href="/?practice=1">Practice cases</a>'
    body = (f'<h1 class="page">{"Practice cases" if practice else "Your PayPal disputes"}</h1>'
            f'<p class="who">{other}</p>'
            + (f'<ul class="inbox">{"".join(rows)}</ul>' if rows else
               '<p class="empty">No open disputes. When a buyer opens one, it appears here.</p>'))
    return PAGE.format(title="Second Look", mode="Practice cases" if practice else "PayPal sandbox", body=body)


def case_page(dispute_id: str, flash: str = "") -> str:
    case = _case(dispute_id)
    d, r = case["dispute"], case["seller_records"]
    msg = next((m["content"] for m in d.get("messages", []) if m.get("posted_by") == "BUYER"), "")
    amt = d["dispute_amount"]
    practice = isinstance(_client(dispute_id), MockPayPal)
    left = (f'<a class="back" href="/{"?practice=1" if practice else ""}">All disputes</a>'
            f'<p class="claim quote">{e(msg)}</p>'
            f'<p class="who">{e(REASON.get(d["reason"], d["reason"]))}. {e(amt["value"])} {e(amt["currency_code"])}'
            f'{", ".join([""] + [i["name"] for i in r.get("items", [])])}</p>'
            f'{timeline(case)}<h2>What the evidence says</h2>{evidence(r)}')
    banner = ""
    if d.get("status") == "WAITING_FOR_BUYER_RESPONSE":
        given = [ev for ev in d.get("evidences", []) if ev.get("source") == "SUBMITTED_BY_SELLER"]
        banner = ('<div class="sent"><b>' + ("Your evidence is with PayPal. " if given else "")
                  + 'Waiting for the buyer.</b><br>PayPal will tell you if they reply or escalate.</div>')
    elif d.get("status") == "UNDER_REVIEW":
        banner = '<div class="sent"><b>PayPal is reviewing this case.</b></div>'
    saved = _saved(dispute_id)
    if not saved:
        # the dispute id goes in by replace(), not format(): the script below has braces of its own
        right = banner + ('<form class="run" method="post" action="/d/DISPUTE_ID/review"><h2>Ten checks before you answer</h2>'
                 '<p>Second Look reads the dispute and the evidence, runs the ten checks a dispute specialist '
                 'would run, and recommends one answer. Nothing is sent until you approve.</p>'
                 '<button>Take a second look</button></form>'
                 '<script>document.querySelector(".run").addEventListener("submit",e=>{const b=e.target.querySelector("button");'
                 'b.disabled=true;b.textContent="Reading the dispute… about 30 seconds";});</script>').replace("DISPUTE_ID", e(dispute_id))
    else:
        dec, sent = saved
        j = dec.judgment
        guard = ""
        if dec.reasons:
            guard = (f'<div class="guard"><b>Your limits changed the answer'
                     f'{" from " + e(ACTION.get(j.action, j.action)) if dec.overridden else ""}:</b>'
                     f'<ul>{"".join(f"<li>{e(plain(n))}</li>" for n in dec.reasons)}</ul></div>')
        amount = f' ({e(j.partial_amount)})' if dec.action == "PARTIAL_REFUND" and j.partial_amount else ""
        lead, rest = first_sentences(j.reasoning)
        verdict = (f'<section class="verdict"><h3>{e(ACTION.get(dec.action, dec.action))}{amount}</h3>'
                   f'<p class="conf">Confidence {j.confidence:.0%}. {e(ACTION_SAYS.get(dec.action, ""))}</p>'
                   f'<p>{e(lead)}</p>'
                   + (f'<details><summary>Full reasoning</summary><p>{e(rest)}</p></details>' if rest else "")
                   + f'{guard}</section>')
        if sent:
            action_part = (f'<div class="sent"><b>Sent to PayPal: {e(ACTION.get(dec.action, dec.action).lower())}.</b>'
                           f'<br>{e(sent)}</div>')
        elif dec.action == "ASK_SELLER":
            action_part = '<p class="conf">Nothing to approve: this one is your call.</p>'
        else:
            action_part = (f'<form method="post" action="/d/{e(dispute_id)}/approve">'
                           f'<label class="reply" for="reply">Your reply to the buyer</label>'
                           f'<textarea id="reply" name="message">{e(j.draft_message)}</textarea>'
                           f'<input type="hidden" name="action" value="{e(dec.action)}">'
                           f'<div class="approve"><button>Approve: {e(ACTION.get(dec.action, dec.action).lower())}</button>'
                           f'<span>Sends exactly this to PayPal.</span></div></form>')
        right = f'{banner}{flash}{verdict}{action_part}<h2 style="margin-top:34px">The ten checks</h2>{checks(j)}'
    body = f'<div class="case"><section>{left}</section><section class="look">{right}</section></div>'
    return PAGE.format(title=f"{msg[:40]} | Second Look", mode="Practice case" if practice else "PayPal sandbox", body=body)


# ---------- server ----------

class Handler(BaseHTTPRequestHandler):
    def _send(self, body: str, code: int = 200):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _redirect(self, to: str):
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    def _fail(self, err: Exception):
        self._send(PAGE.format(title="Something went wrong", mode="",
                               body=f'<h1 class="page">That didn\'t work.</h1>'
                                    f'<p>{e(str(err))}</p><p><a href="/">Back to the disputes</a></p>'), 500)

    def do_GET(self):
        u = urlparse(self.path)
        try:
            if u.path == "/favicon.ico":
                return self._send("", 204)
            if u.path == "/":
                return self._send(inbox_page("practice" in parse_qs(u.query)))
            if u.path.startswith("/d/"):
                return self._send(case_page(u.path[3:].strip("/")))
            self._send("Not found", 404)
        except Exception as err:  # show the reason on the page, never a blank screen
            self._fail(err)

    def do_POST(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
        try:
            if len(parts) == 3 and parts[0] == "d" and parts[2] == "review":
                from .__main__ import review
                did = parts[1]
                _save(did, review(_client(did), did, "claude"))
                return self._redirect(f"/d/{did}")
            if len(parts) == 3 and parts[0] == "d" and parts[2] == "approve":
                from .__main__ import execute
                did = parts[1]
                saved = _saved(did)
                if not saved or saved[0].action != form.get("action", [""])[0]:
                    return self._send("This answer changed since you saw it. Reload the page.", 409)
                dec = saved[0]
                dec.judgment.draft_message = form.get("message", [dec.judgment.draft_message])[0]
                case = _case(did)
                result = execute(_client(did), dec, case["dispute"], case["seller_records"])
                sent = {"DEFEND": "Evidence submitted and reply sent.", "MESSAGE": "Reply sent.",
                        "REFUND": "Refund accepted and reply sent.", "PARTIAL_REFUND": "Partial refund offered.",
                        "REPLACE": "Replacement offered."}.get(dec.action, "Done.")
                if isinstance(_client(did), MockPayPal):
                    sent += " (Practice case: logged, not sent to PayPal.)"
                _save(did, dec, sent)
                return self._redirect(f"/d/{did}")
            self._send("Not found", 404)
        except Exception as err:
            self._fail(err)

    def log_message(self, *args):  # quiet terminal
        pass


def serve(port: int = 8765) -> None:
    print(f"Second Look: http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
