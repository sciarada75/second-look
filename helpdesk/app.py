"""Ticketbook, a made-up helpdesk, with Second Look inside it.

Ticketbook is NOT a real product and imitates none: it exists to show how Second Look sits inside the tool a
support team already uses. It knows what a helpdesk knows (who wrote, when, what they said). Everything about
PayPal disputes comes from Second Look's API through secondlook_client.py, and Ticketbook decides nothing
about money: what approving would do for an agent is Second Look's answer (`for_person`), and the approval
goes through Second Look's own limits.

Every string from a ticket or from the API is HTML-escaped: buyers write what they like.
Run:  python3 -m helpdesk serve   ->  http://127.0.0.1:8766
"""
from __future__ import annotations

import html
import json
import re
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse

from .secondlook_client import SecondLook, Unavailable

ROOT = Path(__file__).resolve().parent.parent
e = html.escape

# Words for what Second Look's JSON says (codes -> plain English). Display only: nothing here is decided.
ACTION = {"DEFEND": "Defend with evidence", "REFUND": "Refund in full", "PARTIAL_REFUND": "Refund part",
          "REPLACE": "Send a replacement", "MESSAGE": "Reply only", "ASK_SELLER": "Your call"}
REASON = {"MERCHANDISE_OR_SERVICE_NOT_RECEIVED": "Says it never arrived",
          "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED": "Says it's not as described",
          "CREDIT_NOT_PROCESSED": "Says the refund never came"}

CSS = """
:root{--page:#EEF1F5;--card:#FFFFFF;--rail:#1C2541;--rail-soft:#2A3558;--accent:#2F6FDE;--accent-bg:#E6EEFC;
  --ink:#1B2333;--soft:#5E6B7E;--line:#D8DEE7;--kraft:#B5874F;--kraft-bg:#F7F0E6;--ok:#1F7A55;--ok-bg:#E3F3EB;
  --warn:#9A5A12;--warn-bg:#FBF0DF;--bad:#B4322E;--bad-bg:#FBE7E6}
*{box-sizing:border-box}
html,body{margin:0}
body{background:var(--page);color:var(--ink);font:400 15px/1.5 "IBM Plex Sans",system-ui,sans-serif;
  display:grid;grid-template-columns:212px 1fr;min-height:100vh}
a{color:var(--accent)} :focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.rail{background:var(--rail);color:#fff;padding:22px 16px;display:flex;flex-direction:column;gap:28px}
.brand b{display:block;font-size:20px;font-weight:600;letter-spacing:-.01em}
.brand small{display:block;font-size:12px;color:#AEB7CF;margin-top:2px}
.rail nav{display:flex;flex-direction:column;gap:2px}
.rail nav a{color:#D9DEEB;text-decoration:none;padding:7px 10px;border-radius:6px;display:flex;justify-content:space-between}
.rail nav a.on{background:var(--rail-soft);color:#fff}
.rail nav a span{color:#8E99B8;font-size:13px}
.rail .foot{margin-top:auto;font-size:12px;color:#8E99B8}
.shell{min-width:0;display:flex;flex-direction:column}
.top{display:flex;justify-content:space-between;align-items:center;padding:12px 28px;background:var(--card);
  border-bottom:1px solid var(--line);font-size:14px}
.crumb{color:var(--soft)} .crumb a{color:var(--soft);text-decoration:none} .crumb b{color:var(--ink);font-weight:500}
.who{position:relative} .who summary{cursor:pointer;list-style:none;color:var(--soft)} .who summary::-webkit-details-marker{display:none}
.who summary b{color:var(--ink);font-weight:500}
.who .menu{position:absolute;right:0;top:28px;background:var(--card);border:1px solid var(--line);border-radius:8px;
  box-shadow:0 6px 18px rgba(28,37,65,.12);min-width:160px;padding:4px;z-index:5}
.who .menu a{display:block;padding:6px 10px;border-radius:5px;color:var(--ink);text-decoration:none}
.who .menu a:hover,.who .menu a.on{background:var(--accent-bg)}
main{padding:24px 28px 48px;max-width:1240px;width:100%}
h1{font-size:22px;font-weight:600;margin:0 0 4px;letter-spacing:-.01em}
.meta{color:var(--soft);font-size:14px;margin:0 0 20px}
.chip{display:inline-block;font-size:12px;font-weight:500;padding:2px 9px;border-radius:999px;background:var(--accent-bg);color:var(--accent)}
.chip.solved{background:#E9ECF1;color:var(--soft)}
.list{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.row{display:grid;grid-template-columns:36px minmax(140px,1.1fr) 2fr 80px 110px;gap:14px;align-items:center;
  padding:12px 18px;border-top:1px solid var(--line);color:var(--ink);text-decoration:none}
.row:first-child{border-top:0} .row:hover{background:#F6F8FB}
.row .name{font-weight:500} .row .name small{display:block;color:var(--soft);font-weight:400;font-size:13px;overflow:hidden;text-overflow:ellipsis}
.row .subj{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .subj small{display:block;color:var(--soft);font-size:13px;overflow:hidden;text-overflow:ellipsis} .row time{color:var(--soft);font-size:13px;text-align:right}
.av{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;font-size:13px;font-weight:600;color:#fff;background:#5B6B8C}
.grid{display:grid;grid-template-columns:minmax(0,3fr) minmax(320px,2fr);gap:24px;align-items:start}
.msg{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-bottom:12px}
.msg header{display:flex;gap:10px;align-items:center;margin-bottom:10px}
.msg header b{font-weight:500} .msg header small{color:var(--soft);font-size:13px;display:block}
.msg p{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}
.flash{border-radius:8px;padding:10px 14px;margin:0 0 18px;background:var(--ok-bg);color:var(--ok)}
.flash.err{background:var(--bad-bg);color:var(--bad)}
.apps h2{font-size:13px;font-weight:500;color:var(--soft);margin:0 0 8px}
.sl{background:var(--card);border:1px solid var(--line);border-top:3px solid var(--kraft);border-radius:10px;
  animation:arrive .28s ease-out both}
@keyframes arrive{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.sl > header{display:flex;align-items:center;gap:8px;padding:10px 16px;background:var(--kraft-bg);border-bottom:1px solid #EADCC8;
  font-weight:600;font-size:14px}
.sl > header .dot{width:10px;height:10px;border-radius:50%;background:var(--kraft)}
.sl > header small{margin-left:auto;font-weight:400;color:#8A6A40;font-size:12px}
.sl .body{padding:14px 16px 16px}
.sl .body > *:first-child{margin-top:0}
.sl p{margin:8px 0} .sl .soft{color:var(--soft);font-size:13px}
.case{border-top:1px solid var(--line);margin-top:14px;padding-top:14px}
.case .line{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.case .amt{font-weight:600}
.pill{font-size:12px;font-weight:500;padding:2px 9px;border-radius:999px}
.pill.you{background:var(--warn-bg);color:var(--warn)} .pill.buyer{background:var(--ok-bg);color:var(--ok)}
.pill.paypal{background:#E9ECF1;color:var(--soft)} .pill.claim{background:#EFE6F3;color:#6B3F80}
.rec{font-size:18px;font-weight:600;margin:10px 0 2px}
.sl ul{margin:6px 0;padding-left:18px} .sl li{margin:3px 0}
.flag li::marker{color:var(--bad)} .flag b{font-weight:500}
.costs{background:#F6F8FB;border-radius:8px;padding:8px 12px;font-size:14px}
.sl label{display:block;font-size:13px;color:var(--soft);margin:12px 0 4px}
.sl textarea{width:100%;min-height:150px;font:inherit;font-size:14px;padding:10px;border:1px solid var(--line);border-radius:8px;resize:vertical}
.sl .draft{white-space:pre-wrap;font-size:14px;background:#F6F8FB;border-radius:8px;padding:10px}
.sl button{margin-top:10px;font:500 15px "IBM Plex Sans",system-ui,sans-serif;padding:9px 16px;border:0;border-radius:7px;
  background:var(--accent);color:#fff;cursor:pointer;width:100%}
.sl button.pass{background:var(--card);color:var(--accent);border:1.5px solid var(--accent)}
.note{font-size:13px;color:var(--soft);margin-top:6px}
.state{border-radius:8px;padding:8px 12px;font-size:14px;margin-top:12px}
.state.sent{background:var(--ok-bg);color:var(--ok)} .state.stop{background:var(--warn-bg);color:var(--warn)}
.open-sl{display:inline-block;margin-top:12px;font-size:14px}
.history{border-top:1px solid var(--line);margin-top:14px;padding-top:10px}
.history h3{font-size:13px;font-weight:500;color:var(--soft);margin:0 0 6px}
.history li{font-size:14px}
@media (max-width:900px){body{grid-template-columns:1fr}.rail{flex-direction:row;align-items:center;padding:12px 16px}
  .rail nav{flex-direction:row}.rail .foot{display:none}.grid{grid-template-columns:1fr}main{padding:16px}.top{padding:10px 16px}
  .row{grid-template-columns:32px 1fr 80px}.row .subj,.row time{display:none}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""


def when(iso: str) -> str:
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").strftime("%-d %b, %H:%M")
    except (TypeError, ValueError):
        return iso or ""


def initials(name: str) -> str:
    return "".join(w[0] for w in (name or "?").split()[:2]).upper() or "?"


AVATAR = ["#5B6B8C", "#3D7A8C", "#6C5B8C", "#4F7A5B", "#8C6B4F", "#2F6FDE"]


def avatar(name: str) -> str:
    return f'<span class="av" style="background:{AVATAR[sum(map(ord, name or "")) % len(AVATAR)]}" aria-hidden="true">{e(initials(name))}</span>'


def money(amount) -> str:
    """An amount as Second Look gave it: {"value": "58.00", "currency_code": "EUR"}."""
    if not isinstance(amount, dict):
        return ""
    return f'{amount.get("value", "")} {amount.get("currency_code", "")}'.strip()


def pill(case: dict) -> str:
    """Whose move it is, from the dispute's status and stage as Second Look reports them."""
    if case.get("stage") and case.get("stage") != "INQUIRY":
        return '<span class="pill claim">PayPal claim</span>'
    cls, text = {"WAITING_FOR_SELLER_RESPONSE": ("you", "Your move"),
                 "WAITING_FOR_BUYER_RESPONSE": ("buyer", "Waiting for the buyer")}.get(case.get("status"), ("paypal", "PayPal reviewing"))
    return f'<span class="pill {cls}">{e(text)}</span>'


def words(action) -> str:
    return ACTION.get(action, str(action or ""))


def label(check_id) -> str:
    """A check's id as words: "paypal_protection" -> "PayPal protection"."""
    return str(check_id or "").replace("_", " ").capitalize().replace("Paypal", "PayPal").replace("paypal", "PayPal")


def costs_line(c: dict) -> str:
    """Second Look's own figures for each way out, as given."""
    cur = c.get("currency", "")
    m = lambda v: f"{float(v):,.2f} {cur}"  # noqa: E731
    out = []
    now = c.get("refund_now") or {}
    if now.get("out_of_pocket") is not None:
        out.append(f"Refund now: you're out {m(now['out_of_pocket'])}.")
    elif now.get("back_to_buyer") is not None:
        out.append(f"Refund now: {m(now['back_to_buyer'])} back to the buyer.")
    fee = (c.get("settled") or {}).get("dispute_fee")
    if fee is not None:
        out.append("Settle it in the dispute: " + ("no PayPal fee." if not fee else f"{m(fee)} PayPal fee."))
    lost = c.get("claim_lost") or {}
    if lost.get("out_of_pocket") is not None:
        out.append(f"Lose a claim: you're out {m(lost['out_of_pocket'])}.")
    elif lost.get("dispute_fee") is not None:
        out.append(f"Lose a claim: the refund plus a {m(lost['dispute_fee'])} PayPal fee.")
    return f'<p class="costs">{e(" ".join(out))}</p>' if out else ""


def event_text(ev: dict) -> str:
    """One Second Look notification as a line in the ticket's history (plain text: escaped when shown)."""
    kind = ev.get("event")
    if kind == "answer.sent":
        by = ev.get("by")
        text = f"answer sent to PayPal by {by}" if by else "answer sent to PayPal"
        at = re.search(r"\b(\d{1,2}:\d{2})\b", str(ev.get("what_happened") or ""))
        return text + (f", {at.group(1)}" if at else "")
    if kind == "case.handed_off":
        return f"passed to {ev.get('to') or 'a colleague'} by {ev.get('from') or 'a colleague'}"
    if kind == "review.ready":
        return f"review ready ({words(ev.get('recommended'))})"
    return str(kind)


class Helpdesk:
    def __init__(self, tickets_path, events_path, sl):
        self.tickets_path, self.events_path, self.sl = Path(tickets_path), Path(events_path), sl
        self._lock = threading.Lock()

    # ---------- Second Look's notifications ----------

    def add_event(self, payload) -> bool:
        """Keep one notification from Second Look (one JSON line). Anything that isn't one is ignored.
        Stored as it came: it is escaped when shown, never when stored."""
        if not (isinstance(payload, dict) and isinstance(payload.get("event"), str)
                and isinstance(payload.get("dispute_id"), str)):
            return False
        with self._lock:
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.events_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        return True

    def events_for(self, dispute_id: str) -> list:
        """This case's notifications, oldest first (newest last)."""
        try:
            lines = self.events_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict) and ev.get("dispute_id") == dispute_id:
                out.append(ev)
        return out

    def history(self, dispute_ids: list) -> str:
        evs = [ev for did in dispute_ids for ev in self.events_for(did)]
        if not evs:
            return ""
        items = "".join(f"<li>Second Look: {e(event_text(ev))}</li>" for ev in evs)
        return f'<div class="history"><h3>In this ticket</h3><ul>{items}</ul></div>'

    # ---------- data ----------

    def tickets(self) -> dict:
        return json.loads(self.tickets_path.read_text(encoding="utf-8"))

    def agent(self, agent_id: str | None) -> dict:
        agents = self.tickets().get("agents") or [{"id": "agent", "name": "Agent"}]
        return next((a for a in agents if a.get("id") == agent_id), agents[0])

    def is_agent(self, agent_id: str | None) -> bool:
        return any(a.get("id") == agent_id for a in self.tickets().get("agents") or [])

    def ticket(self, ticket_id: int) -> dict | None:
        return next((t for t in self.tickets().get("tickets", []) if t.get("id") == ticket_id), None)

    def secondlook_url(self) -> str:
        return getattr(self.sl, "base", "http://127.0.0.1:8765")

    # ---------- pages ----------

    def _page(self, title: str, crumb: str, me: dict, body: str, here: str = "inbox") -> str:
        data = self.tickets()
        open_n = sum(1 for t in data.get("tickets", []) if t.get("status") == "open")
        menu = "".join(f'<a href="?as={e(quote(a["id"]))}"{" class=on" if a["id"] == me["id"] else ""}>{e(a["name"])}</a>'
                       for a in data.get("agents", []))
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body>
<aside class="rail"><div class="brand"><b>Ticketbook</b><small>a made-up helpdesk</small></div>
<nav aria-label="Views"><a href="/"{" class=on" if here == "inbox" else ""}>Inbox <span>{open_n} open</span></a></nav>
<p class="foot">Ticketbook — a made-up helpdesk, not a real product. It shows Second Look inside another tool.</p></aside>
<div class="shell"><div class="top"><div class="crumb">{crumb}</div>
<details class="who"><summary>Signed in as <b>{e(me["name"])}</b> ▾</summary><div class="menu">{menu}</div></details></div>
<main>{body}</main></div></body></html>"""

    def inbox_page(self, agent_id: str | None) -> str:
        me = self.agent(agent_id)
        rows = []
        for t in self.tickets().get("tickets", []):
            first = (t.get("messages") or [{}])[0]
            status = t.get("status", "open")
            rows.append(f'<a class="row" href="/t/{int(t["id"])}">{avatar(t.get("from_name", ""))}'
                        f'<span class="name">{e(t.get("from_name", ""))}<small>{e(t.get("from_email", ""))}</small></span>'
                        f'<span class="subj">{e(t.get("subject", ""))}<small>{e(first.get("text", ""))}</small></span>'
                        f'<span><span class="chip {e(status)}">{e(status.capitalize())}</span></span>'
                        f'<time>{e(when(first.get("at")))}</time></a>')
        body = (f'<h1>Inbox</h1><p class="meta">Emails to Linen &amp; Paper customer care, newest first.</p>'
                f'<div class="list">{"".join(rows) or "<p class=row>No tickets.</p>"}</div>')
        return self._page("Inbox | Ticketbook", "Ticketbook › <b>Inbox</b>", me, body)

    def ticket_page(self, ticket_id: int, agent_id: str | None, flash: str = "", ok: bool = True) -> str:
        me = self.agent(agent_id)
        t = self.ticket(ticket_id)
        if not t:
            return self._page("Not found | Ticketbook", 'Ticketbook › <a href="/">Inbox</a>', me,
                              f'<h1>No ticket #{int(ticket_id)}</h1><p><a href="/">Back to the inbox</a></p>')
        thread = "".join(
            f'<article class="msg"><header>{avatar(t.get("from_name", "") if m.get("from") == "customer" else me["name"])}'
            f'<span><b>{e(t.get("from_name", "") if m.get("from") == "customer" else m.get("from", ""))}</b>'
            f'<small>{e(when(m.get("at")))}</small></span></header><p>{e(m.get("text", ""))}</p></article>'
            for m in t.get("messages", []))
        status = t.get("status", "open")
        note = f'<p class="flash{"" if ok else " err"}" role="status">{e(flash)}</p>' if flash else ""
        body = (f'{note}<h1>{e(t.get("subject", ""))}</h1>'
                f'<p class="meta">#{int(t["id"])} from {e(t.get("from_name", ""))} &lt;{e(t.get("from_email", ""))}&gt; '
                f'<span class="chip {e(status)}">{e(status.capitalize())}</span></p>'
                f'<div class="grid"><section aria-label="Conversation">{thread}</section>'
                f'<aside class="apps" aria-label="Apps"><h2>Apps</h2>{self.panel(t, me)}</aside></div>')
        return self._page(f"#{int(t['id'])} {t.get('subject', '')} | Ticketbook",
                          f'Ticketbook › <a href="/">Inbox</a> › <b>Ticket #{int(t["id"])}</b>', me, body)

    # ---------- the Second Look panel: only what the API says ----------

    def panel(self, t: dict, me: dict) -> str:
        try:
            body = self._panel_body(t, me)
        except Unavailable:
            body = "<p>Second Look isn't answering. Is it running on port 8765?</p>"
        return ('<section class="sl" aria-label="Second Look"><header><span class="dot"></span>Second Look'
                f'<small>PayPal disputes</small></header><div class="body">{body}</div></section>')

    def _panel_body(self, t: dict, me: dict) -> str:
        cu = self.sl.customer(t.get("from_email", ""))
        if not cu:
            return "<p>No orders or PayPal disputes for this email in Second Look.</p>"
        disputes = cu.get("disputes") or []
        n = len(disputes)
        line = f'{cu.get("name") or t.get("from_name", "")}: {cu.get("orders", 0)} orders, {n} PayPal dispute{"" if n == 1 else "s"}'
        if cu.get("dispute_rate") is not None:
            line += f' ({float(cu["dispute_rate"]):.0%})'
        line += "."
        if cu.get("shop_dispute_rate") is not None:
            line += f' Your shop: {float(cu["shop_dispute_rate"]):.0%}.'
        parts = [f"<p>{e(line)}</p>"]
        open_ids = [d.get("dispute_id") for d in disputes if d.get("outcome") == "Open" and d.get("dispute_id")]
        if not open_ids:
            parts.append('<p class="soft">No open PayPal dispute.</p>')
        for did in open_ids:
            parts.append(self._case_block(str(did), me, int(t["id"])))
        parts.append(self.history([str(d) for d in open_ids]))
        return "".join(parts)

    def _case_block(self, did: str, me: dict, tid: int) -> str:
        link = (f'<a class="open-sl" href="{e(self.secondlook_url())}/d/{e(quote(did))}?as={e(quote(me["id"]))}" '
                f'target="_blank" rel="noopener">Open in Second Look</a>')
        c = self.sl.case(did, as_person=me["id"])
        if not c:
            return f'<div class="case"><p>Second Look has no case {e(did)}.</p>{link}</div>'
        head = (f'<div class="line">{pill(c)}<span class="amt">{e(money(c.get("amount")))}</span>'
                f'<span>{e(REASON.get(c.get("reason"), c.get("reason") or ""))}</span></div>'
                f'<p class="soft">PayPal dispute {e(did)}</p>')
        r = c.get("review")
        if not r:
            return (f'<div class="case">{head}<p>Not reviewed yet. Open in Second Look to take a second look.</p>'
                    f'{link}</div>')
        out = [head, f'<p class="rec">{e(words(r.get("recommended")))}</p>']
        conf = r.get("confidence")
        sub = f"Confidence {float(conf):.0%}." if isinstance(conf, (int, float)) else ""
        if r.get("recommended") == "ASK_SELLER" and r.get("ai_said") and r.get("ai_said") != "ASK_SELLER":
            sub += f' The AI\'s own answer: {words(r["ai_said"]).lower()}.'
        if sub:
            out.append(f'<p class="soft">{e(sub.strip())}</p>')
        notes = [n for n in r.get("limits_notes") or [] if n]
        if notes:
            out.append('<ul>' + "".join(f"<li>{e(str(n))}</li>" for n in notes) + '</ul>')
        flagged = [k for k in r.get("checks") or [] if isinstance(k, dict) and k.get("result") in ("FAIL", "INCONSISTENT")]
        if flagged:
            out.append('<label>What doesn\'t add up</label><ul class="flag">' + "".join(
                f'<li><b>{e(label(k.get("id")))}</b>: {e(str(k.get("finding", "")))}</li>'
                for k in flagged) + '</ul>')
        costs = (c.get("evidence") or {}).get("costs")
        if isinstance(costs, dict):
            out.append(costs_line(costs))
        out.append(self._action(c, r, did, me, tid))
        out.append(link)
        return f'<div class="case">{"".join(out)}</div>'

    def _action(self, c: dict, r: dict, did: str, me: dict, tid: int) -> str:
        """The button Second Look's for_person allows, and nothing else."""
        draft = r.get("draft_reply") or ""
        shown = f'<label>Drafted reply</label><div class="draft">{e(draft)}</div>' if draft else ""
        if r.get("sent"):
            return f'<p class="state sent">Sent: {e(str(r["sent"]))}</p>'
        if r.get("out_of_date"):
            return (f'<p class="state stop">Out of date in Second Look: {e(", ".join(map(str, r["out_of_date"])))}.</p>'
                    + shown)
        fp = c.get("for_person") or {}
        kind = fp.get("outcome")
        if kind == "refused":
            return f'<p class="state stop">{e(str(fp.get("why") or "Second Look does not allow this answer."))}</p>' + shown
        if kind == "unknown_person":
            return (f'<p class="state stop">Second Look doesn\'t know {e(me["name"])} as a person in this shop\'s team.</p>'
                    + shown)
        if kind not in ("send", "pass"):
            return (f'<p class="state stop">Second Look didn\'t say what approving would do for {e(me["name"])}. '
                    'Decide in Second Look.</p>' + shown)
        if kind == "send":
            button = f'<button type="submit">Approve as {e(fp.get("person") or me["name"])}: {e(words(fp.get("action")).lower())}</button>'
            say = "Second Look sends this to PayPal and the buyer."
        else:
            to = fp.get("to") or "a colleague"
            button = f'<button type="submit" class="pass">Pass to {e(to)}</button>'
            say = f"Over your limit: {to} decides. Nothing is sent now."
        return (f'<form method="post" action="/t/{tid}/approve">'
                f'<input type="hidden" name="dispute_id" value="{e(did)}">'
                f'<input type="hidden" name="action" value="{e(str(fp.get("action") or ""))}">'
                f'<input type="hidden" name="review" value="{e(str(r.get("mark") or ""))}">'
                f'<input type="hidden" name="by" value="{e(me["id"])}">'
                f'<label for="msg-{e(did)}">Reply to the buyer</label>'
                f'<textarea id="msg-{e(did)}" name="message">{e(draft)}</textarea>'
                f'{button}<p class="note">{e(say)}</p></form>')

    # ---------- actions ----------

    def approve(self, ticket_id: int, agent_id: str, form: dict) -> tuple:
        """The agent's approval, sent to Second Look as it is: Second Look applies the limits and answers."""
        try:
            return self.sl.approve(form["dispute_id"], form["action"], form.get("message"), agent_id, form.get("review"))
        except Unavailable:
            return 503, "Second Look isn't answering. Nothing was sent."


class Handler(BaseHTTPRequestHandler):
    hd: Helpdesk = None  # set by serve()
    _cookie = None
    _film = False

    def _agent(self, qs: dict) -> str | None:
        asked = (qs.get("as") or [""])[0]
        if self.hd.is_agent(asked):
            self._cookie = f"tb_agent={asked}; Path=/; SameSite=Lax"
            return asked
        jar = dict(c.strip().split("=", 1) for c in (self.headers.get("Cookie") or "").split(";") if "=" in c)
        kept = jar.get("tb_agent")
        return kept if self.hd.is_agent(kept) else self.hd.agent(None)["id"]

    def _send(self, body: str, code: int = 200, ctype: str = "text/html; charset=utf-8"):
        if self._film:
            body = body.replace("</style>", "*{animation:none!important;transition:none!important}</style>", 1)
        b = body.encode()
        self.send_response(code)
        if self._cookie:
            self.send_header("Set-Cookie", self._cookie)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _redirect(self, to: str):
        self.send_response(303)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        self._film = "film" in qs
        try:
            if u.path == "/favicon.ico":
                return self._send("", 204)
            me = self._agent(qs)
            if u.path == "/":
                return self._send(self.hd.inbox_page(me))
            parts = u.path.strip("/").split("/")
            if len(parts) == 2 and parts[0] == "t" and parts[1].isdigit():
                tid = int(parts[1])
                page = self.hd.ticket_page(tid, me, flash=(qs.get("flash") or [""])[0],
                                           ok=(qs.get("ok") or ["1"])[0] == "1")
                return self._send(page, 200 if self.hd.ticket(tid) else 404)
            self._send("Not found", 404, "text/plain; charset=utf-8")
        except Exception as err:  # noqa: BLE001 - say what went wrong, never a blank page
            self._send(f"<p>That didn't work: {e(str(err))}</p>", 500)

    def do_POST(self):
        u = urlparse(self.path)
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        parts = u.path.strip("/").split("/")
        try:
            if len(parts) == 3 and parts[0] == "t" and parts[1].isdigit() and parts[2] == "approve":
                tid = int(parts[1])
                # keep_blank_values: an emptied reply box arrives empty, never as "use the draft"
                form = {k: v[0] for k, v in parse_qs(raw.decode(), keep_blank_values=True).items()}
                by = form.get("by")  # the agent the page was shown to
                if not self.hd.is_agent(by) or not form.get("dispute_id") or not form.get("action"):
                    code, text = 400, "Choose who you are at the top of the page, then try again."
                else:
                    code, text = self.hd.approve(tid, by, form)
                q = {"flash": text, "ok": "1" if code in (200, 202) else "0"}
                if "film=1" in (self.headers.get("Referer") or ""):
                    q["film"] = "1"
                return self._redirect(f"/t/{tid}?{urlencode(q)}")
            if parts == ["hooks", "secondlook"]:
                # Second Look -> Ticketbook: a notification (answer.sent, case.handed_off, review.ready)
                try:
                    payload = json.loads(raw or b"null")
                except ValueError:
                    return self._send("Not JSON", 400, "text/plain; charset=utf-8")
                self.hd.add_event(payload)
                self.send_response(204)
                self.end_headers()
                return None
            self._send("Not found", 404, "text/plain; charset=utf-8")
        except Exception as err:  # noqa: BLE001
            self._send(f"<p>That didn't work: {e(str(err))}</p>", 500)

    def log_message(self, *args):  # quiet terminal
        pass


def serve(port: int = 8766, secondlook: str = "http://127.0.0.1:8765") -> None:
    Handler.hd = Helpdesk(ROOT / "helpdesk" / "tickets.json", ROOT / ".tmp" / "helpdesk-events.jsonl",
                          SecondLook(secondlook))
    print(f"Ticketbook: http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
