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
from datetime import timedelta
from urllib.parse import parse_qs, unquote, urlparse

from . import evidence as evidence_mod, ledger
from .demo import DemoPayPal, LABEL as DEMO_LABEL, is_demo
from .guard import may_approve, CHECKS, Decision, Judgment
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
    "ASK_SELLER": "Nothing is sent until you choose. Start with what doesn't add up.",
}
EVIDENCE_LABEL = {
    "order_date": "Ordered", "items": "Items", "ship_to": "Ships to", "tracking": "Tracking",
    "handling_time_promised": "Your promise", "return_policy": "Your returns policy",
    "listing_text": "Your listing", "fulfilment_status": "Status", "planned_ship_date": "Planned shipping",
    "packing_slip_qty": "Packing slip says", "shipment_weight_g": "Parcel weighed (g)",
    "unit_weight_g": "One item weighs (g)", "envelope_weight_g": "Empty envelope weighs (g)",
    "buyer_history": "This buyer",
}

e = html.escape


# ---------- data ----------

def _client(dispute_id: str | None = None):
    if is_demo(dispute_id):
        return DemoPayPal()
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


def _save(dispute_id: str, d: Decision, sent=None, seen=None) -> None:
    REVIEWS.mkdir(parents=True, exist_ok=True)
    (REVIEWS / f"{dispute_id}.json").write_text(json.dumps({**asdict(d), "sent": sent, "seen": seen},
                                                           ensure_ascii=False))


# ---------- the seller's rules ----------
# Preferences are plain sentences the judge follows in every review (policy.json "seller_preferences").
# This is how Second Look learns: from rules the seller writes and can read, never silently from past cases.
POLICY = ROOT / "policy.json"


def _policy() -> dict:
    return json.loads(POLICY.read_text())


def add_rule(text: str) -> bool:
    text = " ".join(text.split())[:300]
    pol = _policy()
    rules = pol.setdefault("seller_preferences", [])
    if not text or text in rules:
        return False
    rules.append(text)
    POLICY.write_text(json.dumps(pol, indent=2, ensure_ascii=False) + "\n")
    return True


def remove_rule(index: int) -> None:
    pol = _policy()
    rules = pol.get("seller_preferences", [])
    if 0 <= index < len(rules):
        rules.pop(index)
        POLICY.write_text(json.dumps(pol, indent=2, ensure_ascii=False) + "\n")


# A rule written in the middle of a dispute (tired, upset, one case in view) can clash with other rules or
# PayPal's, and it changes every later review. So a case can only SUGGEST a rule; it waits on the rules
# page, next to the case it came from, until the seller accepts, edits or discards it there.
SUGGESTED = ROOT / "records" / "suggested_rules.json"


def suggestions() -> list:
    try:
        return json.loads(SUGGESTED.read_text())
    except (OSError, ValueError):
        return []


def suggest_rule(text: str, case_id: str = "") -> bool:
    text = " ".join(text.split())[:300]
    items = suggestions()
    if not text or any(x["text"] == text for x in items) or text in _policy().get("seller_preferences", []):
        return False
    items.append({"text": text, "from_case": case_id, "date": datetime.utcnow().strftime("%Y-%m-%d")})
    SUGGESTED.parent.mkdir(parents=True, exist_ok=True)
    SUGGESTED.write_text(json.dumps(items, indent=1, ensure_ascii=False) + "\n")
    return True


def settle_suggestion(index: int, accept_as: str | None) -> None:
    """Accept (with the seller's final wording) or discard one suggestion."""
    items = suggestions()
    if 0 <= index < len(items):
        items.pop(index)
        if accept_as:
            add_rule(accept_as)
        SUGGESTED.write_text(json.dumps(items, indent=1, ensure_ascii=False) + "\n")


# a send button works once: the first click locks it (PayPal refuses a second message anyway)
LOCK = ('<script>document.querySelectorAll(".send").forEach(f=>f.addEventListener("submit",e=>{'
        'const b=e.target.querySelector("button");b.disabled=true;b.textContent="Sending to PayPal…";}));</script>')

TEACH = ('<details class="teach"><summary>Suggest a rule for later (nothing changes now)</summary>'
         '<label for="rule">Write it down while it is fresh. It waits on Your rules, next to this case, '
         'until you read it there with your other rules and accept it.</label>'
         '<input id="rule" name="rule" maxlength="300" '
         'placeholder="For example: never promise a delivery date, only a shipping date."></details>')


def rules_page(flash: str = "", demo: bool = False) -> str:
    pol = _policy()
    cur = pol.get("currency", "")
    limits = [f'Refunds above {pol["max_auto_refund"]:.0f} {cur} always come back to you.',
              f'Disputes above {pol["always_ask_above"]:.0f} {cur} always come back to you.',
              f'Answers it is less than {pol["min_confidence"]:.0%} sure of come back to you.']
    if pol.get("defend_if_delivered_to_paypal_address"):
        limits.append("A parcel delivered to the buyer's PayPal address is always defended.")
    rb = pol.get("repeat_buyer")
    if rb:
        limits.append(f'Refunds come back to you when a buyer disputes {rb["times_shop_rate"]:g} times more often than '
                      f'your shop usually sees, with at least {rb["min_earlier_disputes"]} earlier disputes. '
                      f'Compared only once your shop has {rb["min_shop_orders"]} orders in 90 days.')
    rows = "".join(f'<li><span>{e(r)}</span><form method="post" action="/rules/remove">'
                   f'<input type="hidden" name="i" value="{i}"><button class="quiet">Remove</button></form></li>'
                   for i, r in enumerate(pol.get("seller_preferences", [])))
    pending = "".join(
        f'<li><form method="post" action="/rules/accept" class="sugg"><input type="hidden" name="i" value="{i}">'
        f'<textarea name="text" rows="2" aria-label="Suggested rule">{e(x["text"])}</textarea>'
        f'<span class="t-sub">Suggested {e(x.get("date", ""))}'
        + (f' from <a href="/d/{e(x["from_case"])}{"?shop=demo" if is_demo(x["from_case"]) else ""}">{e(x["from_case"])}</a>' if x.get("from_case") else "")
        + f'</span><span class="sugg-actions"><button>Accept as written</button>'
        f'<button class="quiet" formaction="/rules/discard">Discard</button></span></form></li>'
        for i, x in enumerate(suggestions()))
    review = ('<section class="pending"><h2>Suggested, waiting for you</h2><p class="who">Read each one against your rules '
              'below and against PayPal\'s rules. Edit the wording if it needs it. From the moment you accept it, '
              f'it applies to every review.</p><ul class="rulelist">{pending}</ul></section>') if pending else ""
    n = len(suggestions())
    whatnow = (f'<p class="whatnow"><b>What now</b><span>{n} suggested rule{"s wait" if n != 1 else " waits"} for you just below. '
               'Accept it as written, reword it, or discard it.</span></p>' if n else "")
    body = (f'<a class="back" href="/">All disputes</a><h1 class="page">Your rules</h1>{flash}{whatnow}{review}'
            '<p class="who">The same rules and limits apply in every shop you open here.</p>'
            '<section class="rules"><h2>How you like to answer</h2>'
            '<p class="who">Plain sentences. Second Look follows them in every review, and you can change them any time.</p>'
            f'<ul class="rulelist">{rows or "<li><span>No rules yet.</span></li>"}</ul>'
            '<form method="post" action="/rules/add" class="addrule"><input name="rule" maxlength="300" '
            'placeholder="Add a rule, for example: offer an exchange before a refund on fit complaints." '
            'aria-label="New rule"><button>Add rule</button></form>'
            '<h2>Your limits</h2><p class="who">Numbers, enforced by code after the AI has answered. '
            'They can make an answer more careful, never more generous.</p>'
            f'<ul class="limits">{"".join(f"<li>{e(x)}</li>" for x in limits)}</ul></section>')
    return page("Your rules | Second Look", "", body, demo)

# What a review was based on. If any of it changes, the review is out of date and Approve is withdrawn:
# the seller must never approve an answer to a situation that no longer exists.
CHANGED = {"buyer_messages": "the buyer wrote again", "stage": "PayPal moved the case to another stage",
           "amount": "the amount in dispute changed", "tracking": "tracking was added or changed",
           "ship_to": "PayPal now shows the buyer's address"}


def _seen(case: dict) -> dict:
    d, r = case["dispute"], case["seller_records"]
    return {"buyer_messages": sum(1 for m in d.get("messages", []) if m.get("posted_by") == "BUYER"),
            "stage": d.get("dispute_life_cycle_stage"), "amount": d["dispute_amount"]["value"],
            "tracking": (r.get("tracking") or {}).get("tracking_number"), "ship_to": bool(r.get("ship_to"))}


def _changes(dispute_id: str, case: dict) -> list:
    f = REVIEWS / f"{dispute_id}.json"
    seen = json.loads(f.read_text()).get("seen") if f.exists() else None
    if seen is None:
        return ["this review was saved before Second Look tracked changes"]
    now = _seen(case)
    return [CHANGED[k] for k in CHANGED if seen.get(k) != now.get(k)]


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
    marks, prev, last_x, level = [], None, -100.0, 0
    for label, t in points:
        x = 3 + 94 * (t - t0).total_seconds() / span
        # events close together take turns: below the line, above it, higher above it
        level = (level + 1) % 3 if x - last_x < 9 else 0
        lift = ["", " lift", " lift2"][level]
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
        tag = {"PayPal Transaction Search": "PayPal order", "seller's notes": "Your notes",
               "PayPal disputes and Transaction Search": "PayPal history"}.get(tag, tag)
        tag = "Your shop terms" if tag.startswith("shop.json") else tag
        tag = "PayPal tracking" if tag.startswith("PayPal tracking") else tag
        # the tag's look says how much the fact can be relied on: PayPal's records, your published terms, your word
        kind = "paypal" if tag.startswith("PayPal") else "shop" if tag == "Your shop terms" else \
               "notes" if tag == "Your notes" else "practice"
        rows.append(f'<div class="ev"><dt>{e(label)}</dt><dd>{e(str(v))}</dd>'
                    f'<dd class="tag"><span class="src {kind}">{e(tag)}</span></dd></div>')
    for k, why in (r.get("unavailable") or {}).items():
        rows.append(f'<div class="ev missing"><dt>{e(EVIDENCE_LABEL.get(k, k))}</dt><dd>{e(why)}</dd></div>')
    legend = ('<p class="legend"><span class="src paypal">PayPal</span> PayPal\'s own records '
              '<span class="src shop">Your shop terms</span> what you published '
              '<span class="src notes">Your notes</span> your word only</p>')
    return f'{legend}<dl class="evidence">{"".join(rows)}</dl>'


def plain(text: str) -> str:
    """Guard notes are written with codes for the log; the seller reads words."""
    for code, word in sorted(ACTION.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"\b{code}\b", word.lower(), text)
    return (text.replace("INQUIRY stage", "inquiry stage").replace("CLAIM stage", "claim stage")
                .replace("PayPal does not allow", "PayPal doesn't allow"))


def first_sentences(text: str, n: int = 2):
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(parts[:n]), " ".join(parts[n:])


# The ten checks, grouped by what they mean for the decision, most decisive first.
GROUPS = [
    ("INCONSISTENT", "Doesn't add up: check these first", "incon"),
    ("FAIL", "Supports the buyer's claim", "fail"),
    ("PASS", "Speaks against the claim", "pass"),
    ("UNCLEAR", "Can't tell yet", "unclear"),
]


def _bucket(c: dict) -> str:
    # A clean "hidden instructions" check is not an argument against the buyer, only "nothing to flag";
    # a hit is a red flag whatever label the judge gave it.
    if c["id"] == "hidden_instructions":
        return "CLEAN" if c["result"] in ("PASS", "NOT_APPLICABLE") else "INCONSISTENT"
    return c["result"]


def checks(j: Judgment) -> str:
    out = []
    for result, title, cls in GROUPS:
        rows = [f'<li class="check {cls}"><b>{e(CHECKS.get(c["id"], c["id"]))}</b><q>{e(c["finding"])}</q></li>'
                for c in j.checks if _bucket(c) == result]
        if rows:
            out.append(f'<section class="group {cls}"><h4>{e(title)} <span>{len(rows)}</span></h4>'
                       f'<ul class="checks">{"".join(rows)}</ul></section>')
    na = [CHECKS.get(c["id"], c["id"]).lower() for c in j.checks if _bucket(c) == "NOT_APPLICABLE"]
    if any(_bucket(c) == "CLEAN" for c in j.checks):
        out.append('<p class="na-line">Nothing to flag: the buyer\'s text gives no orders to the assistant.</p>')
    if na:
        out.append(f'<p class="na-line">Not relevant here: {e("; ".join(na))}.</p>')
    return "".join(out)


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
/* context colour: green = your live PayPal shop, kraft = the made-up demo shop, grey = practice cases */
header.top{{--ctx:var(--pass);--ctx-bg:#E8F0EA;display:flex;justify-content:space-between;align-items:center;padding:18px 56px;
  border-top:6px solid var(--ctx);border-bottom:1px solid var(--rule);background:linear-gradient(var(--ctx-bg),var(--paper) 140%)}}
header.top.demo{{--ctx:var(--kraft);--ctx-bg:#F6EDE0}} header.top.practice{{--ctx:var(--unclear);--ctx-bg:#ECEEEF}}
.who-am-i{{display:flex;align-items:center;gap:26px}}
.brand{{display:flex;align-items:center;gap:10px;font-weight:700;font-size:20px;text-decoration:none}} .brand small{{font-weight:400;color:var(--soft);margin-left:4px}}
.shop{{position:relative;padding-left:26px;border-left:1px solid var(--rule);font-weight:500}}
.shop summary{{display:flex;align-items:center;gap:10px;cursor:pointer;list-style:none}} .shop summary::-webkit-details-marker{{display:none}}
.switch{{font-size:13px;font-weight:500;color:var(--soft);border:1px solid var(--rule);padding:2px 8px;background:#fff}}
.shop-menu{{position:absolute;top:46px;left:26px;z-index:5;background:#fff;border:1px solid var(--rule);box-shadow:0 8px 24px rgba(30,41,53,.12);min-width:300px}}
.shop-menu a{{display:flex;align-items:center;gap:12px;padding:12px 16px;text-decoration:none;border-top:1px solid var(--rule)}} .shop-menu a:first-child{{border-top:0}}
.shop-menu a:hover{{background:var(--paper)}} .shop-menu small{{display:block;color:var(--soft);font-size:13px;font-weight:400}}
.mono{{display:inline-grid;place-items:center;width:34px;height:34px;border-radius:50%;color:#fff;font:700 13px "Schibsted Grotesk",sans-serif;letter-spacing:.5px}}
.mode{{font-size:14px;font-weight:500;padding:3px 10px;border-left:3px solid var(--ctx);background:#fff;color:var(--ink)}}
.count{{display:inline-block;margin-left:6px;padding:0 8px;border-radius:10px;background:var(--incon);color:#fff;font-size:12px;font-weight:700;text-decoration:none}}
.pill{{display:inline-block;padding:2px 10px;border-radius:12px;font-size:13px;font-weight:700;margin-right:6px;vertical-align:1px}}
.pill.you{{background:#F6E6C8;color:#7A4E0C}} .pill.buyer{{background:#DDEBE1;color:var(--pass)}}
.pill.paypal{{background:#E4E7EA;color:var(--soft)}} .pill.onclaim{{background:#EEDDE9;color:var(--fail)}}
.filters{{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:6px 0 10px}}
.filters input,.filters select{{font:400 16px "Schibsted Grotesk",sans-serif;padding:9px 12px;border:1px solid var(--rule);background:#fff;color:var(--ink)}}
.filters input{{min-width:320px}}
.exposure{{margin:10px 0 26px;max-width:1100px}}
.xchart{{list-style:none;padding:0;margin:0}}
.xchart li{{display:grid;grid-template-columns:300px 1fr 120px;grid-template-rows:auto auto;gap:2px 16px;align-items:center;padding:8px 0}}
.xchart .x-label{{font-weight:500}} .xchart b{{text-align:right;font-variant-numeric:tabular-nums;font-size:20px}}
.xchart .t-sub{{grid-column:2/4}}
.x-track{{height:20px;background:#ECEEE8}} .x-bar{{display:block;height:20px;border-radius:0 4px 4px 0}}
.xchart .pass .x-bar{{background:var(--pass)}} .xchart .incon .x-bar{{background:var(--incon)}} .xchart .fail .x-bar{{background:var(--fail)}}
.pending{{background:#FBF3E4;border-left:4px solid var(--incon);padding:18px 22px;margin:0 0 30px;max-width:900px}}
.sugg{{display:grid;grid-template-columns:1fr;gap:8px;width:100%}} .sugg textarea{{min-height:64px;font-family:Newsreader,Georgia,serif;font-style:italic;font-size:18px}}
.sugg-actions{{display:flex;gap:12px}} .sugg-actions button:first-child{{font:700 15px "Schibsted Grotesk",sans-serif;padding:8px 16px;border:0;background:var(--ink);color:var(--paper);cursor:pointer}}
header.top nav{{display:flex;gap:6px;align-items:center}}
header.top nav a{{font-size:15px;text-decoration:none;padding:7px 14px;border-radius:18px;color:var(--soft)}}
header.top nav a:hover{{background:#fff;color:var(--ink)}}
header.top nav a[aria-current]{{background:var(--ink);color:#fff;font-weight:700}}
header.top nav .mode{{margin-left:14px}}
.whatnow{{display:flex;gap:14px;align-items:baseline;background:#fff;border:1px solid var(--rule);border-left:5px solid var(--incon);
  padding:14px 18px;margin:8px 0 26px;max-width:1100px;font-size:17px}}
.whatnow b{{color:var(--incon);white-space:nowrap}} .whatnow.calm{{border-left-color:var(--pass)}} .whatnow.calm b{{color:var(--pass)}}
.teach{{margin-top:14px;color:var(--soft)}} .teach summary{{cursor:pointer;font-size:15px}}
.teach label{{display:block;margin:10px 0 6px;font-size:15px}}
.teach input,.addrule input{{width:100%;font:400 16px/1.4 "Schibsted Grotesk",sans-serif;padding:10px 12px;border:1px solid var(--rule);background:#fff;color:var(--ink)}}
.rules{{max-width:900px}} .rules h2{{margin-top:36px}}
.rulelist,.limits{{list-style:none;padding:0;margin:0 0 18px}}
.rulelist li{{display:flex;justify-content:space-between;gap:24px;align-items:center;padding:12px 0;border-top:1px solid var(--rule)}}
.rulelist li span{{font-family:Newsreader,Georgia,serif;font-style:italic;font-size:19px}}
.limits li{{padding:10px 0;border-top:1px solid var(--rule)}}
.addrule{{display:flex;gap:12px}} .addrule button{{white-space:nowrap;font:700 16px "Schibsted Grotesk",sans-serif;padding:10px 20px;border:0;background:var(--ink);color:var(--paper);cursor:pointer}}
button.quiet{{cursor:pointer;background:none;color:var(--soft);border:1px solid var(--rule);padding:6px 12px;font-size:14px}}
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
.who{{color:var(--soft);margin:0 0 34px}} .case .pill{{margin-bottom:10px}}
.ruler{{position:relative;list-style:none;margin:30px 0 30px;padding:0;height:190px}}
.ruler::before{{content:"";position:absolute;left:0;right:0;top:95px;border-top:2px solid var(--ink)}}
.mark{{position:absolute;top:89px;width:0}}
.mark::before{{content:"";position:absolute;left:-7px;top:0;width:14px;height:14px;border-radius:50%;background:var(--ink)}}
.mark .lab{{position:absolute;left:0;top:24px;transform:translateX(-50%);width:170px;text-align:center}}
.mark.lift .lab{{top:auto;bottom:16px}} .mark.lift2 .lab{{top:auto;bottom:56px}}
.mark b{{display:block;font-size:15px}} .mark time{{display:block;font-size:14px;color:var(--soft)}}
.mark.hot::before{{background:var(--incon);box-shadow:0 0 0 5px #F3E3C4}}
.gap{{display:block;margin-top:2px;font-family:Newsreader,serif;font-style:italic;font-size:19px;color:var(--incon)}}
h2{{font-size:19px;margin:0 0 14px}}
.evidence{{margin:0}} .ev{{display:grid;grid-template-columns:150px 1fr 150px;gap:12px;padding:10px 0;border-top:1px solid var(--rule)}}
.ev dt{{color:var(--soft)}} .ev dd{{margin:0}} .ev dd.tag{{text-align:right}} .ev dd.tag .src{{margin-left:0}}
.src{{display:inline-block;margin-left:10px;padding:1px 8px;font-size:13px;font-weight:500;background:var(--kraft-bg);color:#6E4F27;border-left:3px solid var(--kraft)}}
.src.paypal{{background:var(--ink);color:#fff;border-left-color:var(--ink)}}
.src.shop{{background:var(--kraft-bg);color:#6E4F27;border-left-color:var(--kraft)}}
.src.notes{{background:transparent;color:var(--soft);border:1px dashed var(--soft);border-left-width:1px}}
.legend{{color:var(--soft);font-size:14px;margin:-4px 0 12px}} .legend .src{{margin-left:0;margin-right:4px}} .legend .src+.src,.legend .src:not(:first-child){{margin-left:14px}}
.ev.missing dd{{color:var(--incon)}}
/* second look */
.look{{border-left:1px solid var(--rule);padding-left:56px}}
.run button,.approve button{{font:700 19px "Schibsted Grotesk",sans-serif;padding:16px 28px;border:0;background:var(--ink);color:var(--paper);cursor:pointer}}
.run p{{color:var(--soft)}}
.group{{margin:0 0 22px;padding-left:16px;border-left:4px solid var(--rule)}}
.group h4{{margin:0 0 4px;font-size:17px;font-weight:700}} .group h4 span{{font-weight:400;color:var(--soft);margin-left:6px}}
.group.pass{{border-color:var(--pass)}} .group.pass h4{{color:var(--pass)}}
.group.fail{{border-color:var(--fail)}} .group.fail h4{{color:var(--fail)}}
.group.incon{{border-color:var(--incon);background:#FBF3E4;padding:12px 16px}} .group.incon h4{{color:var(--incon)}}
.group.unclear h4{{color:var(--soft)}}
.checks{{list-style:none;padding:0;margin:0}}
.check{{padding:8px 0;border-top:1px solid var(--rule)}} .check:first-child{{border-top:0}}
.check b{{display:block;font-weight:500}} .check q{{color:var(--soft);font-size:16px;quotes:none}}
.na-line{{color:var(--soft);font-size:15px;margin:0 0 30px}}
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
.talk{{list-style:none;padding:0;margin:0 0 28px;max-width:640px}} .talk li{{padding:10px 0 10px 16px;border-left:4px solid var(--rule);margin-bottom:8px}}
.talk b{{display:block;font-size:14px;font-weight:500;color:var(--soft)}} .talk q{{quotes:none;font-family:Newsreader,Georgia,serif;font-style:italic;font-size:19px}}
.talk li.buyer{{border-color:var(--fail)}} .talk li.you{{border-color:var(--ink)}} .talk li.proof{{border-color:var(--pass)}}
.stale{{padding:14px 18px;background:#FBF3E4;border-left:4px solid var(--incon);margin:0 0 14px}}
.back{{display:block;margin-bottom:18px;color:var(--soft)}} .draft summary{{cursor:pointer;color:var(--soft)}} .draft p{{color:var(--soft)}}
/* demo label, deadlines, costs */
.mode.demo{{background:var(--kraft-bg);color:#6E4F27;border-left:3px solid var(--kraft);padding:2px 10px;font-weight:500}}
.demo-note{{display:inline-block;margin:0 0 8px;padding:6px 12px;background:var(--kraft-bg);border-left:3px solid var(--kraft);color:#6E4F27;font-size:15px}}
.nobody{{margin:-22px 0 26px;padding:8px 12px;border-left:3px solid var(--incon);color:var(--ink);font-size:16px}}
.cardlink{{margin:14px 0 0}}
.costs{{margin:30px 0;border:1px solid var(--rule);background:#fff;padding:14px 18px}} .costs table{{width:100%;border-collapse:collapse;margin-top:12px}}
.costs summary{{cursor:pointer;display:grid;gap:4px}} .costs summary b{{font-size:19px}} .costs summary span{{color:var(--soft);font-size:15px}}
.costs th,.costs td{{text-align:left;vertical-align:top;padding:10px 12px 10px 0;border-top:1px solid var(--rule);font-size:16px}}
.costs th{{font-weight:700;width:30%}} .costs td:last-child{{font-weight:500}}
.cost-note{{color:var(--soft);font-size:15px;margin:10px 0 0}}
/* overview */
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin:24px 0 36px}}
.tile{{background:#fff;border:1px solid var(--rule);padding:18px 20px;display:flex;flex-direction:column;gap:4px}}
.tile b{{font-size:34px;line-height:1.1;font-variant-numeric:tabular-nums}} .t-label{{font-weight:500}} .t-sub{{color:var(--soft);font-size:14px}}
.ov-grid{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:56px;align-items:start}}
.bl-h{{font-size:15px;color:var(--soft);font-weight:500;margin:16px 0 6px}}
.barlist{{list-style:none;padding:0;margin:0}}
.barlist li{{display:grid;grid-template-columns:200px 1fr 40px;gap:12px;align-items:center;padding:5px 0}}
.bl-track{{height:14px;background:transparent}} .bl-bar{{display:block;height:14px;background:var(--ink);border-radius:0 4px 4px 0;min-width:2px}}
.bl-n{{font-variant-numeric:tabular-nums;text-align:right}}
.meter{{position:relative;height:18px;background:var(--rule);margin:18px 0 26px}}
.m-fill{{position:absolute;left:0;top:0;bottom:0;background:var(--ink);border-radius:0 4px 4px 0}}
.m-line{{position:absolute;top:-6px;bottom:-6px;border-left:2px solid var(--incon)}} .m-line i{{position:absolute;top:26px;left:-14px;font-style:normal;font-size:14px;color:var(--incon)}}
table.waiting{{width:100%;border-collapse:collapse;margin-top:8px}}
.waiting th,.waiting td{{text-align:left;padding:10px 14px 10px 0;border-top:1px solid var(--rule);font-size:16px;vertical-align:top}}
.waiting th{{font-size:14px;color:var(--soft);font-weight:500}}
.api{{margin-top:40px}} .api code{{display:inline-block;background:#fff;border:1px solid var(--rule);padding:10px 14px;font-size:15px}}
@media (max-width:1100px){{.ov-grid{{grid-template-columns:1fr}} .barlist li{{grid-template-columns:140px 1fr 32px}} .case{{grid-template-columns:1fr}} .look{{border:0;padding:0}} main,header.top{{padding-left:20px;padding-right:20px}}}}
@media (prefers-reduced-motion:no-preference){{.verdict,.checks{{animation:in .5s ease-out}} @keyframes in{{from{{opacity:0}}}}}}
</style></head><body>
<header class="top {context}"><div class="who-am-i"><a class="brand" href="/">{mark}Second Look<small>Sell without fear.</small></a>{shop}</div>{nav}</header>
<main>{body}</main></body></html>"""


def pill_for_on(on: str, stage: str | None = None) -> str:
    """Colour says whose move it is: amber = yours, green = the buyer's, grey = PayPal's, plum = a claim."""
    if stage and stage != "INQUIRY":
        return '<span class="pill onclaim">PayPal claim</span>'
    cls, text = {"you": ("you", "Your move"), "the buyer": ("buyer", "Waiting for the buyer"),
                 "PayPal": ("paypal", "PayPal reviewing")}.get(on, ("paypal", on))
    return f'<span class="pill {cls}">{e(text)}</span>'


def pill_for(d: dict) -> str:
    on = {"WAITING_FOR_SELLER_RESPONSE": "you", "WAITING_FOR_BUYER_RESPONSE": "the buyer"}.get(d.get("status"), "PayPal")
    return pill_for_on(on, d.get("dispute_life_cycle_stage"))


# The shop's badge: initials on its own colour, so a glance says whose shop this is.
BADGE_COLOURS = ["#3E6B57", "#6B4E7A", "#9A5B3C", "#3F5D7D", "#7A6A3A"]


def _badge(name: str, colour: str | None) -> str:
    initials = "".join(w[0] for w in name.replace("&", " ").split() if w[:1].isalnum())[:2].upper() or "?"
    colour = colour or BADGE_COLOURS[sum(map(ord, name)) % len(BADGE_COLOURS)]
    return f'<span class="mono" style="background:{e(colour)}" aria-hidden="true">{e(initials)}</span>'


def shop_badge(context: str) -> str:
    """Which shop you're in, and the switch to the other one (and to the practice cases)."""
    try:
        demo_shop = DemoPayPal().shop
        live_shop = json.loads((ROOT / "shop.json").read_text())
    except (OSError, ValueError):
        return ""
    shops = [("demo", demo_shop.get("name", "Demo shop"), "demo shop, made-up data", demo_shop.get("brand_colour"), "/?shop=demo"),
             ("live", live_shop.get("name", "Your shop"), "your PayPal sandbox", live_shop.get("brand_colour"), "/?shop=live")]
    if context == "practice":
        here = '<span class="mono" style="background:#7D858E" aria-hidden="true">PC</span>Practice cases'
    else:
        _, name, _, colour, _ = next(x for x in shops if x[0] == context)
        here = f'{_badge(name, colour)}{e(name)}'
    menu = "".join(f'<a href="{url}">{_badge(name, colour)}<span>{e(name)}<small>{e(what)}</small></span></a>'
                   for key, name, what, colour, url in shops if key != context)
    menu += ('<a href="/?practice=1"><span class="mono" style="background:#7D858E" aria-hidden="true">PC</span>'
             '<span>Practice cases<small>test disputes with known answers</small></span></a>' if context != "practice" else "")
    return (f'<details class="shop"><summary>{here}<span class="switch">Switch</span></summary>'
            f'<div class="shop-menu">{menu}</div></details>')


MARK = ('<svg class="mark-logo" width="30" height="22" viewBox="0 0 30 22" aria-hidden="true">'
        '<circle cx="11" cy="11" r="9" fill="#B5874F"/><circle cx="19" cy="11" r="9" fill="none" stroke="#1E2935" stroke-width="3"/></svg>')


def page(title: str, mode: str, body: str, demo: bool = False) -> str:
    q = "?shop=demo" if demo else ""
    waiting = len(suggestions())
    rules = f'Your rules<span class="count">{waiting} to review</span>' if waiting else "Your rules"
    context = "demo" if demo else "practice" if mode.startswith("Practice") else "live"
    here = "rules" if title.startswith("Your rules") else "overview" if title.startswith("Overview") or \
        "customer" in body[:400] else "disputes"
    cur = lambda k: ' aria-current="page"' if here == k else ""  # noqa: E731
    nav = (f'<nav><a href="/{q}"{cur("disputes")}>Disputes</a><a href="/overview"{cur("overview")}>Overview</a>'
           f'<a href="/rules"{cur("rules")}>{rules}</a>'
           f'<span class="mode {context}">{e(DEMO_LABEL if demo else mode or "PayPal sandbox")}</span></nav>')
    return PAGE.format(title=title, nav=nav, body=body, context=context, shop=shop_badge(context), mark=MARK)


def _shop(src: str):
    """The client, the shop's disputes and orders, and 'today' for a source: live sandbox or demo shop."""
    if src == "demo":
        pp = DemoPayPal()
        return pp, pp.disputes(), pp.orders(), pp.today
    pp = client_from_env(ROOT)
    if isinstance(pp, MockPayPal):
        raise RuntimeError("No PayPal keys in .env: the overview needs the live sandbox, or open the demo shop.")
    now = datetime.utcnow()
    return pp, evidence_mod.shop_disputes(pp, now), evidence_mod._orders(pp, now), now.date()


def inbox_page(src: str) -> str:
    practice, demo = src == "practice", src == "demo"
    pp = DemoPayPal() if demo else MockPayPal(ROOT / "cases", ROOT / ".tmp" / "actions.jsonl") if practice else client_from_env(ROOT)
    today = pp.today if demo else datetime.utcnow().date()
    items = []
    for state in (["REQUIRED_ACTION"] if practice else ["REQUIRED_ACTION", "REQUIRED_OTHER_PARTY_ACTION"]):
        items += pp.list_disputes(state)
    seen, rows = set(), []
    for d in items:
        if d["dispute_id"] in seen:
            continue
        seen.add(d["dispute_id"])
        full = d if practice or demo else pp.get_dispute(d["dispute_id"])
        msg = next((m["content"] for m in full.get("messages", []) if m.get("posted_by") == "BUYER"), "")
        due = _t(full.get("seller_response_due_date"))
        left = ledger.days_left(full, today)
        claim = " PayPal claim." if full.get("dispute_life_cycle_stage") in ("CHARGEBACK", "PRE_ARBITRATION", "ARBITRATION") else ""
        waiting = ("Waiting for the buyer" if full.get("status") == "WAITING_FOR_BUYER_RESPONSE" else
                   f"Reply by {due:%d %b}" + (f" ({left} days left)" if left is not None and not practice else "") if due else "")
        rows.append((full.get("status") != "WAITING_FOR_SELLER_RESPONSE", left if left is not None else 99,
                     f'<li><a href="/d/{e(d["dispute_id"])}"><blockquote>{e(msg)}</blockquote>'
                     f'<span class="amt">{e(d["dispute_amount"]["value"])} {e(d["dispute_amount"]["currency_code"])}</span>'
                     f'<span class="meta">{pill_for(full)} {e(REASON.get(full.get("reason"), full.get("reason", "")))}.{e(claim)} {e(waiting)}</span></a></li>'))
    ordered = sorted(rows, key=lambda r: (r[0], r[1])) if not practice else rows
    yours = [r for r in ordered if not r[0]]
    if practice:
        whatnow = ('<p class="whatnow calm"><b>What now</b><span>Practice cases have known answers. Open any one and press '
                   '"Take a second look" to see what Second Look would do. Nothing reaches PayPal.</span></p>')
    elif yours:
        first = yours[0]
        whatnow = (f'<p class="whatnow"><b>What now</b><span>{len(yours)} case{"s" if len(yours) != 1 else ""} wait on you. '
                   f'Start at the top: the nearest deadline comes first'
                   + (f' ({first[1]} days left)' if first[1] != 99 else '') + '.</span></p>')
    else:
        whatnow = ('<p class="whatnow calm"><b>What now</b><span>Nothing waits on you. The open cases wait on the buyer '
                   'or on PayPal; each comes back here if they answer.</span></p>' if rows else "")
    rows = [r[2] for r in ordered]
    other = ('<a href="/?shop=live">Your PayPal disputes</a> · <a href="/?shop=demo">Demo shop</a>' if practice else
             '<a href="/?shop=live">Your PayPal disputes</a> · <a href="/?practice=1">Practice cases</a>' if demo else
             '<a href="/?shop=demo">Demo shop</a> · <a href="/?practice=1">Practice cases</a>')
    title = "Practice cases" if practice else f"{DemoPayPal().shop['name']}: open disputes" if demo else "Your PayPal disputes"
    about = f'<p class="demo-note">{e(pp.shop["about"])}</p>' if demo else ""
    body = (f'<h1 class="page">{e(title)}</h1>{about}<p class="who">{other}</p>{whatnow}'
            + ('<div class="filters" role="search"><input id="q" type="search" placeholder="Search what the buyer said, reason, amount" '
               'aria-label="Search disputes"></div><script>addEventListener("DOMContentLoaded",()=>{const q=document.getElementById("q"),rows=[...document.querySelectorAll(".inbox li")];'
               'q.addEventListener("input",()=>rows.forEach(r=>r.hidden=!!q.value&&!r.textContent.toLowerCase().includes(q.value.toLowerCase())))});</script>'
               if len(rows) > 3 else "")
            + (f'<ul class="inbox">{"".join(rows)}</ul>' if rows else
               '<p class="empty">No open disputes. When a buyer opens one, it appears here.</p>'))
    return page("Second Look", "Practice cases" if practice else "PayPal sandbox", body, demo)


def costs_block(c: dict | None, hist: dict | None) -> str:
    """What each way out costs, from PayPal's fee rules, PayPal's fee on this payment and the shop's own costs."""
    if not c:
        return ""
    cur = c["currency"]
    m = lambda v: f"{v:,.2f} {cur}"  # noqa: E731
    fee = f"PayPal's {m(c['paypal_fee'])} fee on the payment, which it keeps" if c.get("paypal_fee") is not None else "PayPal's fee on the payment"
    oop = c["refund_now"]["out_of_pocket"]
    rows = [("Refund now", f"{m(c['amount'])} back to the buyer.",
             f"You're out {m(oop)}: the item, the postage and {fee}." if oop is not None else
             f"You lose the item, the postage and {fee}. Add your item costs to see the total.")]
    rows.append(("Settle it in the dispute", "Reply, or send your evidence. The buyer withdraws or lets it close.",
                 "No PayPal dispute fee."))
    lost = c["claim_lost"]
    rows.append(("It becomes a claim, and you lose", f"{m(c['amount'])} back, plus a {m(lost['dispute_fee'])} PayPal fee.",
                 f"You're out {m(lost['out_of_pocket'])}." if lost.get("out_of_pocket") is not None else ""))
    won = c["claim_won"]["dispute_fee"]
    rows.append(("It becomes a claim, and you win", "You keep the sale.",
                 f"{m(won)} fee: you are a high-volume seller, charged even when you win." if won else "No fee."))
    trs = "".join(f'<tr><th scope="row">{e(a)}</th><td>{e(b)}</td><td>{e(x)}</td></tr>' for a, b, x in rows)
    notes = []
    if hist and hist.get("earlier_disputes"):
        notes.append(ledger.describe_escalations(hist["earlier_disputes"], hist["earlier_escalated"],
                                                 hist["shop_closed"], hist["shop_escalated"]))
    t = c.get("threshold") or {}
    if t.get("counts"):
        notes.append(f"Your claims last quarter: {t['claims']} in {t['sales']:,} sales ({t['ratio']:.2%}). "
                     + ("You are above PayPal's 1.5% high-volume line." if t["high_volume"] else
                        f"{t['claims_to_threshold']} more and you cross PayPal's 1.5% line, where every claim costs "
                        f"{m(28.0 if cur == 'EUR' else 30.0)}."))
    lost_oop = lost.get("out_of_pocket")
    gist = ("Refund now: you're out " + (m(oop) if oop is not None else "the item and postage")
            + ". Settle it in the dispute: no fee. Lose a claim: you're out "
            + (m(lost_oop) if lost_oop is not None else f"the item, postage and a {m(lost['dispute_fee'])} fee") + ".")
    return (f'<details class="costs"><summary><b>What each way out costs</b><span>{e(gist)}</span></summary><table>{trs}</table>'
            + "".join(f'<p class="cost-note">{e(n)}</p>' for n in notes) + '</details>')


def bar_list(rows: list, total: int) -> str:
    """One hue, counts written out: a list of how cases ended."""
    out = []
    for label, n in rows:
        w = 100 * n / total if total else 0
        out.append(f'<li title="{e(label)}: {n} of {total}"><span class="bl-label">{e(label)}</span>'
                   f'<span class="bl-track"><span class="bl-bar" style="width:{w:.1f}%"></span></span>'
                   f'<span class="bl-n">{n}</span></li>')
    return f'<ul class="barlist">{"".join(out)}</ul>'


def overview_whatnow(ov: dict) -> str:
    mine = [w for w in ov["waiting"] if w["on"] == "you"]
    if not mine:
        return ('<p class="whatnow calm"><b>What now</b><span>Nothing waits on you. Below: how cases ended, and what the '
                'open ones could still cost.</span></p>')
    w = mine[0]
    left = f', {w["days_left"]} days left' if w["days_left"] is not None else ""
    return (f'<p class="whatnow"><b>What now</b><span>{len(mine)} open case{"s" if len(mine) != 1 else ""} wait on you. '
            f'The most urgent: <a href="/d/{e(w["dispute_id"])}">{e(w["reason"])}'
            f'{e(" from " + w["buyer"] if w.get("buyer") else "")}</a>{e(left)}.</span></p>')


def overview_page(src: str) -> str:
    demo = src == "demo"
    pp, disputes, orders, today = _shop(src)
    cur = "EUR"
    ov = ledger.overview(disputes, orders, today, cur)
    m = lambda v: f"{v:,.0f} {cur}"  # noqa: E731
    c, hv = ov["counts"], ov["high_volume"]
    q = "?shop=demo" if demo else ""
    tiles = [("Handled", f'{ov["handled"]}', f'closed in the last {ov["window_days"]} days'),
             ("Settled before a claim", f'{ov["settled_before_claim"]} of {ov["handled"]}', "no PayPal dispute fee"),
             ("Money kept", m(ov["kept"]), "won, withdrawn, or closed with no claim"),
             ("Given back", m(ov["refunded"]), "refunds and accepted offers"),
             ("Dispute fees", m(ov["fees_paid"]), "estimated from PayPal's fee table")]
    kpis = "".join(f'<div class="tile"><span class="t-label">{e(a)}</span><b>{e(b)}</b><span class="t-sub">{e(x)}</span></div>'
                   for a, b, x in tiles)
    stayed = [(ledger.OUTCOME_LABEL[k], c[k]) for k in ("won", "withdrew", "closed") if c[k]]
    back = [(ledger.OUTCOME_LABEL[k], c[k]) for k in ("settled_offer", "refunded", "covered", "lost_claim", "lost_no_reply") if c[k]]
    meter_w = min(100, 100 * hv["ratio"] / 0.02) if hv["sales"] else 0
    meter = (f'<section class="meter-box"><h2>PayPal\'s high-volume line</h2>'
             f'<p class="who">Claims and card chargebacks against sales, {ov["quarter"][0]:%b}–'
             f'{(ov["quarter"][1] - timedelta(days=1)):%b %Y} (PayPal counts the three previous full months). '
             f'At 1.5% with more than 100 sales, every claim costs {m(28)}, even the ones you win.</p>'
             f'<div class="meter" role="img" aria-label="{hv["ratio"]:.2%} of sales, line at 1.5%">'
             f'<span class="m-fill" style="width:{meter_w:.1f}%"></span><span class="m-line" style="left:75%"><i>1.5%</i></span></div>'
             f'<p><b>{hv["claims"]} claims in {hv["sales"]:,} sales: {hv["ratio"]:.2%}.</b> '
             + ("Above the line." if hv["high_volume"] else f'{hv["claims_to_threshold"]} more claims this quarter and you cross it.')
             + '</p></section>')
    ex = ledger.exposure(disputes, today, hv["high_volume"], cur)
    top = max(ex["all_lost"], 1)
    bars = [("If you win them all", ex["all_won"], "pass",
             "Nothing leaves your account." if not ex["all_won"] else "High-volume fee on every claim, even won."),
            (f"If they end like your last {ex['closed']} cases", ex["like_before"], "incon",
             f"{ex['share']:.0%} of the money disputed actually left your account." if ex["share"] is not None else "No closed cases yet to compare with."),
            ("If you lose them all", ex["all_lost"], "fail",
             f"Every refund, plus a {m(28 if hv['high_volume'] else 14)} PayPal fee on each.")]
    chart = "".join(
        f'<li class="{cls}"><span class="x-label">{e(a)}</span><span class="x-track"><span class="x-bar" '
        f'style="width:{0 if v is None else max(0.4, 100 * v / top):.1f}%"></span></span>'
        f'<b>{"—" if v is None else e(m(v))}</b><span class="t-sub">{e(note)}</span></li>' for a, v, cls, note in bars)
    exposure_box = (f'<section class="exposure"><h2>What the {ex["open"]} open cases could cost</h2>'
                    f'<p class="who">{m(ex["at_stake"])} in dispute. Money that would leave your account: refunds and '
                    'PayPal dispute fees. When you refund, the goods and the postage are lost on top.</p>'
                    f'<ul class="xchart">{chart}</ul></section>')
    reasons = sorted({w["reason"] for w in ov["waiting"]})
    filters = ('<div class="filters" role="search"><input id="q" type="search" placeholder="Search buyer, reason, case" '
               'aria-label="Search open cases"><select id="on" aria-label="Waiting on"><option value="">Waiting on anyone</option>'
               '<option value="you">Waiting on you</option><option value="the buyer">Waiting on the buyer</option>'
               '<option value="PayPal">Waiting on PayPal</option></select><select id="why" aria-label="Reason">'
               '<option value="">Any reason</option>' + "".join(f'<option>{e(r)}</option>' for r in reasons) + '</select>'
               '<span id="shown" class="t-sub"></span></div>'
               '<script>addEventListener("DOMContentLoaded",()=>{const q=document.getElementById("q"),on=document.getElementById("on"),why=document.getElementById("why"),'
               'n=document.getElementById("shown"),rows=[...document.querySelectorAll("table.waiting tbody tr")];'
               'const f=()=>{let k=0;rows.forEach(r=>{const ok=(!q.value||r.textContent.toLowerCase().includes(q.value.toLowerCase()))'
               '&&(!on.value||r.dataset.on===on.value)&&(!why.value||r.dataset.why===why.value);r.hidden=!ok;k+=ok});'
               'n.textContent=k+" of "+rows.length+" shown"};[q,on,why].forEach(x=>x.addEventListener("input",f));f()});</script>')
    waits = "".join(
        f'<tr data-on="{e(w["on"])}" data-why="{e(w["reason"])}"><td><a href="/d/{e(w["dispute_id"])}{q}">{e(w["reason"])}</a>'
        f'<span class="t-sub">{e(" · " + w["buyer"] if w.get("buyer") else "")}{e(" · PayPal claim" if w["stage"] != "INQUIRY" else "")}</span></td>'
        f'<td>{w["amount"]:.2f}</td>'
        f'<td>{pill_for_on(w["on"], w["stage"])}</td><td>{"" if w["days_left"] is None else e(str(w["days_left"]))}</td><td>{e(w["next"])}</td></tr>'
        for w in ov["waiting"])
    body = (f'<h1 class="page">Overview</h1>'
            + (f'<p class="demo-note">{e(pp.shop["about"])}</p>' if demo else "")
            + f'<p class="who">Last {ov["window_days"]} days: {ov["disputes"]} disputes in {ov["orders"]:,} orders. '
              f'From PayPal\'s own records: each case\'s stage and outcome.</p>'
            + ('' if ov["handled"] else '<p class="demo-note">No closed cases in this shop yet: the history fills in as cases '
                 'close. To see an overview with a history, <a href="/overview?shop=demo">open the demo shop</a>.</p>')
            + overview_whatnow(ov)
            + f'<div class="kpis">{kpis}</div>'
            f'<div class="ov-grid"><section><h2>How they ended</h2>'
            f'<h3 class="bl-h">The money stayed with you</h3>{bar_list(stayed, ov["handled"])}'
            f'<h3 class="bl-h">Money went back</h3>{bar_list(back, ov["handled"])}'
            f'<p class="cost-note">{ov["escalated"]} of {ov["handled"]} went past the inquiry to a PayPal claim.</p></section>{meter}</div>'
            f'<h2 style="margin-top:40px">Open now: {ov["open"]}</h2>{exposure_box}{filters}'
            f'<table class="waiting"><thead><tr><th>Case</th><th>Amount</th><th>Waiting on</th><th>Days left</th>'
            f'<th>If nobody answers</th></tr></thead><tbody>{waits}</tbody></table>')
    return page("Overview | Second Look", "PayPal sandbox", body, demo)


def customer_page(key: str, src: str) -> str:
    demo = src == "demo"
    pp, disputes, orders, today = _shop(src)
    cu = ledger.customer(key, disputes, orders)
    q = "?shop=demo" if demo else ""
    if not cu:
        return page("Customer | Second Look", "PayPal sandbox", '<h1 class="page">No customer with that id or email.</h1>', demo)
    rate = (f'{len(cu["disputes"])} disputes in {cu["orders"]} orders ({cu["dispute_rate"]:.0%}). '
            f'Your shop: {cu["shop_dispute_rate"]:.1%}.' if cu["dispute_rate"] is not None else "")
    if cu["times_shop_rate"]:
        rate += f' {cu["times_shop_rate"]:.0f}× your usual rate.' if cu["times_shop_rate"] >= 2 else " About your usual rate."
    rows = "".join(f'<tr><td>{e(x["opened"])}</td><td><a href="/d/{e(x["dispute_id"])}">{e(x["reason"])}</a></td>'
                   f'<td>{x["amount"]:.2f}</td><td>{"PayPal claim" if x["escalated"] else "Inquiry"}</td><td>{e(x["outcome"])}</td></tr>'
                   for x in cu["disputes"])
    api = f'/api/customers/{cu["email"] or cu["payer_id"]}{q}'
    body = (f'<a class="back" href="/overview{q}">Overview</a><h1 class="page">{e(cu["name"] or cu["payer_id"])}</h1>'
            f'<p class="who">{e(cu["email"] or "")} · PayPal payer {e(cu["payer_id"])}</p>'
            f'<div class="kpis">'
            f'<div class="tile"><span class="t-label">Orders</span><b>{cu["orders"]}</b><span class="t-sub">{cu["spent"]:,.2f} EUR, since {e(cu["first_order"] or "")}</span></div>'
            f'<div class="tile"><span class="t-label">Disputes</span><b>{len(cu["disputes"])}</b><span class="t-sub">{e(rate)}</span></div>'
            f'<div class="tile"><span class="t-label">Taken to a claim</span><b>{cu["escalated"]}</b><span class="t-sub">past the inquiry</span></div>'
            f'<div class="tile"><span class="t-label">Refunded</span><b>{cu["refunded"]:,.2f}</b><span class="t-sub">EUR</span></div></div>'
            f'<table class="waiting"><thead><tr><th>Opened</th><th>Case</th><th>Amount</th><th>Went to</th><th>Outcome</th></tr></thead>'
            f'<tbody>{rows or "<tr><td colspan=5>No disputes.</td></tr>"}</tbody></table>'
            f'<section class="api"><h2>In your customer database</h2><p class="who">Your CRM or helpdesk can ask for this card '
            f'when this customer orders or calls, by email or PayPal payer id:</p><code>GET {e(api)}</code></section>')
    return page(f"{cu['name'] or 'Customer'} | Second Look", "PayPal sandbox", body, demo)


def customer_json(key: str, src: str) -> dict | None:
    _, disputes, orders, _today = _shop(src)
    return ledger.customer(key, disputes, orders)


EVIDENCE_KIND = {"PROOF_OF_FULFILLMENT": "proof of shipment or delivery", "PROOF_OF_REFUND": "proof of refund",
                 "PROOF_OF_RETURN": "proof of return"}


def conversation(d: dict) -> str:
    """Everything said and sent on this case, in order: a seller must see whether they already answered."""
    items = [(m.get("time_posted") or "", "buyer" if m.get("posted_by") == "BUYER" else "you",
              "Buyer" if m.get("posted_by") == "BUYER" else "You", m.get("content", "")) for m in d.get("messages", [])]
    for ev in d.get("evidences", []):
        if ev.get("source") == "SUBMITTED_BY_SELLER":
            kind = EVIDENCE_KIND.get(ev.get("evidence_type"), str(ev.get("evidence_type", "evidence")).lower().replace("_", " "))
            items.append((ev.get("date") or "~", "proof", "You sent PayPal", kind))
    if not items:
        return ""
    rows = []
    for when, cls, who, text in sorted(items, key=lambda x: x[0]):
        t = _t(when)
        stamp = f", {t:%d %b, %H:%M}" if t else ""
        body = f"<q>{e(text)}</q>" if cls != "proof" else f"<span>{e(text)}</span>"
        rows.append(f'<li class="{cls}"><b>{e(who)}{stamp}</b>{body}</li>')
    return f'<h2>What\'s been said</h2><ol class="talk">{"".join(rows)}</ol>'


def case_page(dispute_id: str, flash: str = "") -> str:
    case = _case(dispute_id)
    d, r = case["dispute"], case["seller_records"]
    msg = next((m["content"] for m in d.get("messages", []) if m.get("posted_by") == "BUYER"), "")
    amt = d["dispute_amount"]
    demo = is_demo(dispute_id)
    practice = not demo and isinstance(_client(dispute_id), MockPayPal)
    today = DemoPayPal().today if demo else datetime.utcnow().date()
    q = "?shop=demo" if demo else ""
    buyer = ledger.buyer_of(d)
    card = (f'<p class="cardlink"><a href="/customer/{e(buyer)}{q}">This customer\'s record with you</a></p>'
            if buyer and not practice else "")
    nobody = "" if practice or d.get("status") == "RESOLVED" else f'<p class="nobody">{e(ledger.if_nobody_answers(d, today))}</p>'
    left = (f'<a class="back" href="/{"?practice=1" if practice else q}">All disputes</a>'
            f'{pill_for(d)}<p class="claim quote">{e(msg)}</p>'
            f'<p class="who">{e(REASON.get(d["reason"], d["reason"]))}. {e(amt["value"])} {e(amt["currency_code"])}'
            f'{", ".join([""] + [i["name"] for i in r.get("items", [])])}</p>{nobody}'
            f'{conversation(d)}{timeline(case)}<h2>What the evidence says</h2>{evidence(r)}{card}')
    costs = costs_block(r.get("costs"), r.get("buyer_history_counts"))
    banner = ""
    given = [ev for ev in d.get("evidences", []) if ev.get("source") == "SUBMITTED_BY_SELLER"]
    # You answered and PayPal holds your evidence: there is nothing to send until the buyer moves.
    # (A second message is refused by PayPal; evidence it already has adds nothing.) When the buyer
    # writes, the status changes and the review comes back by itself.
    nothing_to_do = d.get("status") == "WAITING_FOR_BUYER_RESPONSE" and bool(given)
    if nothing_to_do:
        banner = ('<div class="sent"><b>You\'ve answered. Nothing to do now.</b><br>Your evidence is with PayPal and '
                  'PayPal is waiting for the buyer. If they reply or escalate, this case comes back to you.</div>')
    elif d.get("status") == "WAITING_FOR_BUYER_RESPONSE":
        banner = ('<div class="sent"><b>Waiting for the buyer.</b><br>PayPal will tell you if they reply or escalate.</div>')
    elif d.get("status") == "UNDER_REVIEW":
        banner = '<div class="sent"><b>PayPal is reviewing this case.</b></div>'
    saved = _saved(dispute_id)
    if nothing_to_do and not saved:
        right = banner + costs
    elif not saved:
        # the dispute id goes in by replace(), not format(): the script below has braces of its own
        right = banner + costs + ('<form class="run" method="post" action="/d/DISPUTE_ID/review"><h2>Ten checks before you answer</h2>'
                 '<p>Second Look reads the dispute and the evidence, runs the ten checks a dispute specialist '
                 'would run, and recommends one answer. Nothing is sent until you approve.</p>'
                 '<button>Take a second look</button></form>'
                 '<script>document.querySelectorAll(".run").forEach(f=>f.addEventListener("submit",e=>{const b=e.target.querySelector("button");'
                 'b.disabled=true;b.textContent="Reading the dispute… about 30 seconds";}));</script>').replace("DISPUTE_ID", e(dispute_id))
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
        changes = _changes(dispute_id, case)
        done = f'<div class="sent"><b>Sent to PayPal.</b><br>{e(sent)}</div>' if sent else ""
        if changes:
            action_part = done + (f'<form class="run" method="post" action="/d/{e(dispute_id)}/review"><div class="stale">'
                           f'<b>This answer is out of date:</b> {e("; ".join(changes))}.</div>'
                           f'<button>Take a fresh look</button></form>'
                           '<script>document.querySelectorAll(".run").forEach(f=>f.addEventListener("submit",e=>{const b=e.target.'
                           'querySelector("button");b.disabled=true;b.textContent="Reading the dispute… about 30 seconds";}));</script>')
        elif sent:
            action_part = f'<div class="sent"><b>Sent to PayPal.</b><br>{e(sent)}</div>'
        elif nothing_to_do:
            action_part = ('<p class="conf">Kept for reference: nothing to send while PayPal waits for the buyer. '
                           'If they write again, Second Look marks this answer out of date.</p>')
        elif dec.action == "ASK_SELLER" and dec.overridden and j.action in ("REFUND", "PARTIAL_REFUND", "REPLACE"):
            # The reply was written for the money action your limits stopped: it promises that money.
            # Sending it as "a question" would make the promise without your approval.
            action_part = (f'<div class="stale"><b>The drafted reply promises a {e(ACTION.get(j.action, j.action).lower())}, '
                           'which your limits stopped.</b> Decide first. If you refund, do it in PayPal, then come back: '
                           'Second Look will see the change and draft a reply that matches.</div>'
                           f'<details class="draft"><summary>Read the draft anyway</summary><p>{e(j.draft_message)}</p></details>')
        elif dec.action == "ASK_SELLER" and j.draft_message:
            action_part = (f'<form class="send" method="post" action="/d/{e(dispute_id)}/approve">'
                           f'<label class="reply" for="reply">Before you decide, ask the buyer</label>'
                           f'<textarea id="reply" name="message">{e(j.draft_message)}</textarea>'
                           f'<input type="hidden" name="action" value="MESSAGE">'
                           f'<div class="approve"><button>Send this question</button>'
                           f'<span>Sends only this message. No money moves.</span></div>' + TEACH + '</form>' + LOCK)
        elif dec.action == "ASK_SELLER":
            action_part = '<p class="conf">Nothing to send: read the checks and decide.</p>'
        else:
            action_part = (f'<form class="send" method="post" action="/d/{e(dispute_id)}/approve">'
                           f'<label class="reply" for="reply">Your reply to the buyer</label>'
                           f'<textarea id="reply" name="message">{e(j.draft_message)}</textarea>'
                           f'<input type="hidden" name="action" value="{e(dec.action)}">'
                           f'<div class="approve"><button>Approve: {e(ACTION.get(dec.action, dec.action).lower())}</button>'
                           f'<span>Sends exactly this to PayPal.</span></div>' + TEACH + '</form>' + LOCK)
        right = f'{banner}{flash}{verdict}{action_part}{costs}<h2 style="margin-top:34px">The ten checks</h2>{checks(j)}'
    body = f'<div class="case"><section>{left}</section><section class="look">{right}</section></div>'
    return page(f"{msg[:40]} | Second Look", "Practice case" if practice else "PayPal sandbox", body, demo)


# ---------- one path for the page and for other systems ----------
# Approving through the API runs exactly the checks the page runs: same review, same limits, same
# "out of date" test, sent once. A connected system can only do what the seller could do here.

def notify(event: str, payload: dict) -> None:
    """Second Look -> other systems: POST a small JSON event to the address in SECONDLOOK_NOTIFY_URL
    (a helpdesk, a team chat, a CRM). Never blocks or breaks the seller's action; failures are logged."""
    import os
    from urllib import request as rq
    url = os.environ.get("SECONDLOOK_NOTIFY_URL")
    if not url:
        return
    body = json.dumps({"event": event, **payload}, ensure_ascii=False, default=str).encode()
    try:
        rq.urlopen(rq.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"}), timeout=5)
    except Exception as err:  # noqa: BLE001 - a notification must never stop the answer
        (ROOT / ".tmp").mkdir(exist_ok=True)
        with open(ROOT / ".tmp" / "notify.log", "a") as f:
            f.write(f"{datetime.utcnow():%Y-%m-%d %H:%M} {event} {payload.get('dispute_id')}: {err}\n")


def run_review(did: str) -> Decision:
    from .__main__ import review
    dec = review(_client(did), did, "claude")
    _save(did, dec, seen=_seen(_case(did)))
    notify("review.ready", {"dispute_id": did, "recommended": dec.action, "confidence": dec.judgment.confidence,
                            "limits_changed_it": dec.overridden})
    return dec


def approve(did: str, chosen: str, message: str | None, rule: str = "") -> tuple[int, str]:
    """Send the answer the seller chose. Returns (HTTP status, what happened)."""
    from .__main__ import execute
    saved = _saved(did)
    if saved and saved[1]:
        return 200, saved[1]  # already sent: a second approval sends nothing
    if not saved or not may_approve(saved[0].action, chosen, saved[0].judgment.action):
        return 409, "This answer changed since you saw it, or it can't be sent as it is. Look again."
    dec = saved[0]
    recommended = dec.action
    dec.action = chosen  # on "your call" the seller may send the drafted question
    if message is not None:
        dec.judgment.draft_message = message
    case = _case(did)
    if _changes(did, case):
        return 409, "Something changed since this review. Take a fresh look."
    seen = json.loads((REVIEWS / f"{did}.json").read_text()).get("seen")
    result = execute(_client(did), dec, case["dispute"], case["seller_records"])
    sent = {"DEFEND": "Evidence submitted and reply sent." if not str(result.get("message", "")).startswith("not sent")
            else "Evidence submitted. Reply not sent: PayPal is waiting for the buyer to answer your last message.",
            "MESSAGE": "Question sent." if recommended == "ASK_SELLER" else "Reply sent.",
            "REFUND": "Refund accepted and reply sent.", "PARTIAL_REFUND": "Partial refund offered.",
            "REPLACE": "Replacement offered."}.get(dec.action, "Done.")
    if is_demo(did):
        sent += " (Demo shop: logged, not sent to PayPal.)"
    elif isinstance(_client(did), MockPayPal):
        sent += " (Practice case: logged, not sent to PayPal.)"
    if suggest_rule(rule or "", did):
        sent += " Your rule suggestion waits on Your rules for review."
    dec.action = recommended  # the page keeps showing what was recommended
    _save(did, dec, sent, seen)
    notify("answer.sent", {"dispute_id": did, "action": chosen, "what_happened": sent})
    return 200, sent


def api_case(did: str) -> dict:
    """Other systems -> Second Look: one case as data, what the page shows."""
    case = _case(did)
    d, r = case["dispute"], case["seller_records"]
    saved = _saved(did)
    out = {"dispute_id": did, "reason": d.get("reason"), "status": d.get("status"),
           "stage": d.get("dispute_life_cycle_stage"), "amount": d.get("dispute_amount"),
           "buyer": ledger.buyer_of(d), "messages": d.get("messages", []),
           "evidence": {k: v for k, v in r.items() if k not in ("sources", "unavailable")},
           "sources": r.get("sources", {}), "review": None}
    if saved:
        dec, sent = saved
        out["review"] = {"recommended": dec.action, "ai_said": dec.judgment.action, "confidence": dec.judgment.confidence,
                         "limits_notes": dec.reasons, "reasoning": dec.judgment.reasoning,
                         "draft_reply": dec.judgment.draft_message, "checks": dec.judgment.checks,
                         "sent": sent, "out_of_date": _changes(did, case)}
    return out


def api_open(src: str) -> list:
    """Every open case in a shop, with its review if there is one."""
    if src == "demo":
        pp = DemoPayPal()
        items = [d for d in pp.disputes() if d.get("status") != "RESOLVED"]
    else:
        pp = MockPayPal(ROOT / "cases", ROOT / ".tmp" / "actions.jsonl") if src == "practice" else client_from_env(ROOT)
        items, seen = [], set()
        for state in (["REQUIRED_ACTION"] if src == "practice" else ["REQUIRED_ACTION", "REQUIRED_OTHER_PARTY_ACTION"]):
            for d in pp.list_disputes(state):
                if d["dispute_id"] not in seen:
                    seen.add(d["dispute_id"])
                    items.append(d if src == "practice" else pp.get_dispute(d["dispute_id"]))
    out = []
    for d in items:
        saved = _saved(d["dispute_id"])
        out.append({"dispute_id": d["dispute_id"], "reason": d.get("reason"), "status": d.get("status"),
                    "amount": d.get("dispute_amount"), "buyer": ledger.buyer_of(d),
                    "recommended": saved[0].action if saved else None, "sent": saved[1] if saved else None})
    return out


# ---------- server ----------

class Handler(BaseHTTPRequestHandler):
    _cookie = None

    def _send(self, body: str, code: int = 200):
        b = body.encode()
        self.send_response(code)
        if self._cookie:
            self.send_header("Set-Cookie", self._cookie)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _redirect(self, to: str):
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    def _json(self, data, code: int = 200):
        b = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _fail(self, err: Exception):
        self._send(page("Something went wrong", "",
                               body=f'<h1 class="page">That didn\'t work.</h1>'
                                    f'<p>{e(str(err))}</p><p><a href="/">Back to the disputes</a></p>'), 500)

    def do_GET(self):
        u = urlparse(self.path)
        try:
            if u.path == "/favicon.ico":
                return self._send("", 204)
            qs = parse_qs(u.query)
            # The shop you're in stays the same from page to page: an Overview of one shop next to the
            # disputes of another made no sense (Claudia, 21/10). Demo by default: it has a history.
            asked = (qs.get("shop") or [""])[0]
            if asked in ("demo", "live"):
                self._cookie = f"sl_shop={asked}; Path=/; SameSite=Lax"
            jar = dict(c.strip().split("=", 1) for c in (self.headers.get("Cookie") or "").split(";") if "=" in c)
            shop = asked if asked in ("demo", "live") else jar.get("sl_shop", "demo")
            src = "practice" if "practice" in qs else shop
            if u.path == "/":
                return self._send(inbox_page(src))
            if u.path == "/overview":
                return self._send(overview_page(src))
            if u.path.startswith("/customer/"):
                return self._send(customer_page(u.path[len("/customer/"):].strip("/"), src))
            if u.path.rstrip("/") == "/api/disputes":
                return self._json(api_open(src))
            if u.path.startswith("/api/disputes/"):
                return self._json(api_case(unquote(u.path[len("/api/disputes/"):].strip("/"))))
            if u.path.startswith("/api/customers/"):
                # the integration: a CRM or helpdesk asks for a customer's record by email or PayPal payer id
                cu = customer_json(unquote(u.path[len("/api/customers/"):].strip("/")), src)
                b = json.dumps(cu if cu else {"error": "unknown customer"}, ensure_ascii=False, default=str).encode()
                self.send_response(200 if cu else 404)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                return self.wfile.write(b)
            if u.path == "/rules":
                return self._send(rules_page(demo=shop == "demo"))
            if u.path.startswith("/d/"):
                return self._send(case_page(u.path[3:].strip("/")))
            self._send("Not found", 404)
        except Exception as err:  # show the reason on the page, never a blank screen
            self._fail(err)

    def do_POST(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        form = parse_qs(raw.decode()) if not self.path.startswith("/api/") else {}
        try:
            if parts == ["rules", "add"]:
                add_rule(form.get("rule", [""])[0])
                return self._redirect("/rules")
            if parts == ["rules", "accept"]:
                settle_suggestion(int(form.get("i", ["-1"])[0]), form.get("text", [""])[0])
                return self._redirect("/rules")
            if parts == ["rules", "discard"]:
                settle_suggestion(int(form.get("i", ["-1"])[0]), None)
                return self._redirect("/rules")
            if parts == ["rules", "remove"]:
                remove_rule(int(form.get("i", ["-1"])[0]))
                return self._redirect("/rules")
            if len(parts) == 3 and parts[0] == "d" and parts[2] == "review":
                run_review(parts[1])
                return self._redirect(f"/d/{parts[1]}")
            if len(parts) == 3 and parts[0] == "d" and parts[2] == "approve":
                code, text = approve(parts[1], form.get("action", [""])[0], form.get("message", [None])[0], form.get("rule", [""])[0])
                return self._redirect(f"/d/{parts[1]}") if code == 200 else self._send(text, code)
            # the API: the same review and the same approval, as JSON
            if len(parts) == 4 and parts[:2] == ["api", "disputes"] and parts[3] in ("review", "approve"):
                did = parts[2]
                if parts[3] == "review":
                    run_review(did)
                    return self._json(api_case(did))
                data = json.loads(raw or b"{}")
                code, text = approve(did, data.get("action", ""), data.get("message"), data.get("rule", ""))
                return self._json({"dispute_id": did, "result": text}, code)
            self._send("Not found", 404)
        except Exception as err:
            self._fail(err)

    def log_message(self, *args):  # quiet terminal
        pass


def serve(port: int = 8765) -> None:
    print(f"Second Look: http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
