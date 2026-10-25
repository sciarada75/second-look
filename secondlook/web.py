"""The seller's screen: a small local web app over the same judge, guard and PayPal client.

    python3 -m secondlook serve            http://127.0.0.1:8765

Inbox → a dispute as a case file (the buyer's words, a timeline to scale, the evidence with its
sources) → "Take a second look" runs the judge (one model call, about $0.05) → the ten checks, the
recommendation, the guard's notes, a reply you can edit → Approve sends exactly what you saw.

A review is cached in .tmp/reviews/ so reloading never pays twice, and Approve executes the cached
decision: the seller approves what is on the screen, not a fresh answer.

Without a key, nothing breaks: the demo shop's open cases start from the reviews Claude made of them, shipped
in demo/reviews/, and "Take a second look" runs the rules baseline (secondlook/judge.py `rules`) instead of
Claude, labelled as such on the page and in the API (`judge`). The guard runs after either judge.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import threading
from dataclasses import asdict, replace
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import timedelta
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from . import cases as cases_mod, evidence as evidence_mod, judge as judge_mod, ledger, sort as sort_mod, team as team_mod
from .demo import DemoPayPal, LABEL as DEMO_LABEL, is_demo
from .guard import apply_policy, may_approve, money_out, held_for_size_only, CHECKS, MONEY, QUESTION_STOPS, SIZE_STOPS, Decision, Judgment
from .paypal import MockPayPal, client_from_env

ROOT = Path(__file__).resolve().parent.parent
REVIEWS = ROOT / ".tmp" / "reviews"
# Claude's reviews of the demo shop's open cases, shipped with the repo so a fresh clone with no AI key shows
# them (a judge of the hackathon has no key). Read only, and only for a DEMO-* case with no review of its own
# in REVIEWS: a fresh look or an approval saves there, so a shipped file is never written. A shipped review
# goes out of date exactly as a cached one does: it carries what it saw (`seen`).
SHIPPED = ROOT / "demo" / "reviews"
_DEMO_ID = re.compile(r"DEMO-\d+")

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
    "order_no": "Order", "paid_with": "Paid with", "order_date": "Ordered", "items": "Items", "ship_to": "Ships to", "tracking": "Tracking",
    "handling_time_promised": "Your promise", "return_policy": "Your returns policy",
    "listing_text": "Your listing", "fulfilment_status": "Status", "planned_ship_date": "Planned shipping",
    "packing_slip_qty": "Packing slip says", "shipment_weight_g": "Parcel weighed (g)",
    "unit_weight_g": "One item weighs (g)", "envelope_weight_g": "Empty envelope weighs (g)",
    "buyer_history": "This buyer", "already_refunded": "Already refunded",
}

e = html.escape


# ---------- data ----------

def _client(dispute_id: str | None = None):
    if cases_mod.is_case_id(dispute_id):
        raise RuntimeError("A shop inquiry has no PayPal client: its answers go through Outbox.")
    if is_demo(dispute_id):
        return DemoPayPal()
    if dispute_id and (ROOT / "cases" / f"{dispute_id}.json").exists():
        return MockPayPal(ROOT / "cases", ROOT / ".tmp" / "actions.jsonl")
    return client_from_env(ROOT)


def _case(dispute_id: str) -> dict:
    if cases_mod.is_case_id(dispute_id):
        return inquiry_case(dispute_id)
    from .__main__ import load_case  # same loader as the CLI
    return _with_case_refund(dispute_id, load_case(_client(dispute_id), dispute_id))


def _review_file(dispute_id: str) -> Path | None:
    """Where this case's review is: its own (.tmp/reviews/), else for a demo case the shipped one, else none."""
    f = REVIEWS / f"{dispute_id}.json"
    if f.exists():
        return f
    if _DEMO_ID.fullmatch(dispute_id or "") and (SHIPPED / f"{dispute_id}.json").exists():
        return SHIPPED / f"{dispute_id}.json"
    return None


def _raw(dispute_id: str) -> dict | None:
    f = _review_file(dispute_id)
    try:
        return json.loads(f.read_text()) if f else None
    except (OSError, ValueError):
        return None


def is_shipped(dispute_id: str) -> bool:
    """The review on screen is one that ships with the demo, not one made on this machine."""
    f = _review_file(dispute_id)
    return bool(f) and f.parent == SHIPPED


def judge_of(dispute_id: str) -> str | None:
    """Which judge wrote the review: "claude" or "rules" (the baseline, when no ANTHROPIC_API_KEY is set).
    Reviews saved before this was recorded were all Claude's: the web ran no other judge."""
    raw = _raw(dispute_id)
    return (raw.get("judge") or "claude") if raw is not None else None


def has_ai_key() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _saved(dispute_id: str):
    f = _review_file(dispute_id)
    if not f:
        return None
    raw = json.loads(f.read_text())
    return Decision(action=raw["action"], reasons=raw["reasons"], judgment=Judgment(**raw["judgment"]),
                    overridden=raw["overridden"], stops=raw.get("stops", [])), raw.get("sent")


def review_mark(dispute_id: str) -> str:
    """A short fingerprint of the review a page or a system was shown: what was recommended, what the AI said,
    its amount and draft, and the case it saw. An approval that carries one is refused if the review changed."""
    raw = _raw(dispute_id)
    if raw is None:
        return ""
    j = raw.get("judgment") or {}
    basis = [raw.get("action"), j.get("action"), j.get("partial_amount"), j.get("draft_message"), raw.get("seen")]
    if raw.get("judge"):  # only when recorded: the marks of reviews saved before it stay as they were
        basis.append(raw["judge"])
    return hashlib.sha256(json.dumps(basis, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def _saved_by(dispute_id: str) -> dict:
    """Who sent the answer and when, as saved with it (empty before teams existed, or for a solo seller)."""
    raw = _raw(dispute_id)
    return {"by": raw.get("by"), "at": raw.get("at")} if raw is not None else {}


def _save(dispute_id: str, d: Decision, sent=None, seen=None, by=None, at=None, judge=None) -> None:
    REVIEWS.mkdir(parents=True, exist_ok=True)
    extra = {"judge": judge} if judge else {}
    (REVIEWS / f"{dispute_id}.json").write_text(json.dumps({**asdict(d), "sent": sent, "seen": seen,
                                                            "by": by, "at": at, **extra}, ensure_ascii=False))


# ---------- the team ----------
# The demo shop carries its own team (demo/shop.json); the live shop's lives in policy.json "team".
# Neither present = a team of one, and nothing about teams shows on screen.

def team_for(dispute_id: str | None) -> dict:
    if is_demo(dispute_id):
        return team_mod.of(DemoPayPal().shop.get("team"))
    if dispute_id and (ROOT / "cases" / f"{dispute_id}.json").exists():
        return team_mod.of(None)  # practice cases: always a team of one
    return team_mod.of(_policy().get("team"))


def team_for_src(src: str) -> dict:
    return team_for("DEMO-" if src == "demo" else None) if src != "practice" else team_mod.of(None)


def src_of_case(did: str, shop: str) -> str:
    """The shop a case belongs to, whatever shop the cookie remembers: its people are that shop's."""
    if is_demo(did):
        return "demo"
    if did and (ROOT / "cases" / f"{did}.json").exists():
        return "practice"
    return "live" if did else shop


def assignments_for(dispute_id: str | None) -> team_mod.Assignments:
    if is_demo(dispute_id):
        return team_mod.Assignments(ROOT / ".tmp" / "assignments-demo.json", seed=DemoPayPal().raw.get("assignments"))
    return team_mod.Assignments(ROOT / "records" / "assignments.json")


# One approval at a time per case. The server answers on several threads: two clicks (or a person and the
# API) at once must not both read "not sent yet" and both reach PayPal, or both hand the case on.
_CASE_LOCKS: dict = {}
_CASE_LOCKS_GUARD = threading.Lock()


def _case_lock(did: str) -> threading.Lock:
    with _CASE_LOCKS_GUARD:
        return _CASE_LOCKS.setdefault(did, threading.Lock())


def take(did: str, by: str | None) -> tuple[int, str]:
    """A person takes a case nobody has. 400 in a team of one (nothing to take) or with no known name;
    409 when someone has it already, a colleague's handoff included: taking never reroutes a case."""
    t = team_for(did)
    if t.get("solo"):
        return 400, "A team of one has nothing to take: every case is already yours."
    who = team_mod.person(t, by)
    if not who:
        return 400, "Say who you are: a person in this shop's team."
    if not _is_open_case(did):
        return 404, "No open case with that id in this shop."
    holder = []

    def claim(a):
        if a["to"]:
            holder.append(a["to"])
            return a
        return {**a, "to": who["id"]}
    with _case_lock(did):
        assignments_for(did).update(did, claim)
    if holder:
        p = team_mod.person(t, holder[0])
        return 409, f"{p['name'] if p else holder[0]} has this case already."
    return 200, f"{who['name']} took this case."


# PayPal's dispute ids: PP-R-ZOY-10193120 (live sandbox), PP-D-001 (practice cases).
_PAYPAL_ID = re.compile(r"PP-[A-Z]-[A-Z]{3}-\d+|PP-D-\d+")


def _is_open_case(did: str) -> bool:
    """A cheap check that an id is a case of this shop, so nobody fills the assignments file with made-up ids.
    Demo: an open dispute in the demo data. Live: a case reviewed here, or an id shaped like PayPal's (asking
    PayPal on every Take it would cost a call; an id of the right shape that isn't open only adds a stale row)."""
    if cases_mod.is_case_id(did):
        c = case_store(shop_of_case(did)).get(did)
        return bool(c) and c["status"] == "open" and not c.get("dispute_id")
    if is_demo(did):
        return any(d.get("dispute_id") == did and d.get("status") != "RESOLVED" for d in DemoPayPal().disputes())
    return (REVIEWS / f"{did}.json").exists() or bool(_PAYPAL_ID.fullmatch(did or ""))


def by_for_post(t: dict, by: str | None) -> tuple[bool, str | None]:
    """Who a form says it was shown to. In a team it must be a real person of the case's team, and a POST
    never falls back to the first person: each form names the person whose page it was. This is not
    authentication: anyone at this machine can pick any name in the picker (README, "Not built").
    A team of one needs no name."""
    if t.get("solo"):
        return True, None
    p = team_mod.person(t, by)
    return (True, p["id"]) if p else (False, None)


# ---------- cases: one customer, one order, one problem, every channel ----------
# Requests (email, web form) arrive through POST /api/requests, are sorted (secondlook/sort.py) and filed on
# their case (secondlook/cases.py). One case file per shop. The demo shop's starts with the requests in
# demo/shop.json, filed by the same code the first time it is read; the live shop's starts empty.
CASE_FILES = {"demo": ROOT / ".tmp" / "cases-demo.json", "live": ROOT / "records" / "cases-live.json"}
_SEEDING = threading.Lock()
REQUEST_CHANNELS = ("email", "form")   # phone calls arrive in a later step; PayPal disputes are read from PayPal


def shop_of_case(cid: str) -> str:
    return "demo" if is_demo(cid) else "live"


def shop_orders(src: str) -> list:
    """Every order the shop holds, as stored: PayPal's (the demo's data, or Transaction Search on the live
    sandbox) and, in the demo, the orders paid by card or bank. No PayPal keys: no live orders."""
    if src == "demo":
        pp = DemoPayPal()
        return pp.orders() + pp.other_orders()
    pp = client_from_env(ROOT)
    if isinstance(pp, MockPayPal):
        return []
    try:
        return evidence_mod._orders(pp, datetime.utcnow())
    except RuntimeError:
        return []


def shop_disputes(src: str) -> list:
    if src == "demo":
        return DemoPayPal().disputes()
    pp = client_from_env(ROOT)
    if isinstance(pp, MockPayPal):
        return []
    try:
        return evidence_mod.shop_disputes(pp, datetime.utcnow())
    except RuntimeError:
        return []


def _tx_of(d: dict) -> str | None:
    return ((d.get("disputed_transactions") or [{}])[0]).get("seller_transaction_id")


def _file_request(store, src: str, req: dict, ai) -> tuple:
    """Sort one request and put it on its case. A request already filed (same source id) is not sorted again,
    so a system that sends it twice never pays for a second look by the AI."""
    sid = req.get("source_id")
    if sid and store.by_source(sid):
        return store.get(store.by_source(sid)), "already_received"
    orders, disputes = shop_orders(src), shop_disputes(src)
    open_d = [d for d in disputes if d.get("status") != "RESOLVED"]
    busy = {_tx_of(d) for d in open_d} | {c["order_no"] for c in store.all() if c["status"] == "open" and c.get("order_no")}
    s = sort_mod.sort(req, orders, busy, ai=ai)
    dispute = None
    if s["settled"] and s["order_no"]:
        o = next((x for x in orders if sort_mod.order_no(x) == s["order_no"]), None)
        tx = o.get("transaction_id") if o else None
        dispute = next((d for d in open_d if tx and _tx_of(d) == tx), None)
    return store.file(req, s, dispute=dispute)


def case_store(src: str) -> cases_mod.CaseStore:
    path = CASE_FILES[src]
    store = cases_mod.CaseStore(path, prefix="DEMO-" if src == "demo" else "")
    if src == "demo":
        with _SEEDING:
            if not path.exists():
                for r in DemoPayPal().requests():   # they sort by rules alone (tests/test_demo_shop.py): no AI call
                    _file_request(store, "demo", r, ai=None)
    return store


def _num(x) -> float | None:
    """An amount from the shop's records as a number, or None when it isn't one ("n/a", "", missing)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def _logged_refund(c: dict | None) -> dict | None:
    """The refunds a case has logged (an inquiry's answer), summed, with the last one's date and who: None if none."""
    back = [m for m in (c or {}).get("money", []) if m.get("kind") in ("refund", "partial_refund")]
    if not back:
        return None
    when = _t(back[-1].get("at"))
    return {"case_id": c["id"], "amount": round(sum(_num(m.get("amount")) or 0 for m in back), 2),
            "on": f"{when:%d %b %Y}" if when else "", "by": back[-1].get("by") or ""}


def _money_case_for(did: str, dispute_of) -> dict | None:
    """The case of a PayPal dispute that has logged a refund, or None. Found by the dispute itself (a case it
    joined) or by its order (the dispute's transaction is the case's order number), whether or not anything
    has linked them yet: the inbox -> dispute -> approve path never opens the case page, where the link is made.
    Read only (a dispute page never writes the case file), and with no case that logged money, no further
    reading at all: `dispute_of()` (which may call PayPal) is asked only then."""
    path = CASE_FILES[shop_of_case(did)]
    if not path.exists():
        return None
    paid = [c for c in cases_mod.CaseStore(path).all() if _logged_refund(c)]
    if not paid:
        return None
    joined = [c for c in paid if c.get("dispute_id") == did]
    tx = None if joined else _tx_of(dispute_of() or {})
    on = joined or [c for c in paid if tx and c.get("order_no") == tx]
    return next((c for c in on if c["status"] == "open"), on[0] if on else None)


def _with_case_refund(did: str, case: dict) -> dict:
    """A PayPal dispute whose case already logged a refund (the shop answered the inquiry before PayPal had it):
    its records say so, for the judge, the page and the guard's rule 10. A dispute whose case logged no money
    is returned exactly as it was."""
    r = _logged_refund(_money_case_for(did, lambda: case["dispute"]))
    if not r:
        return case
    cur = case["dispute"]["dispute_amount"].get("currency_code", "EUR")
    said = f'{r["amount"]:.2f} {cur}' + (f' on {r["on"]}' if r["on"] else "") + (f' by {r["by"]}' if r["by"] else "")
    records = {**case["seller_records"], "refund_logged_on_case": r["case_id"], "refunded_so_far": r["amount"],
               "already_refunded": f'{said}, on case {r["case_id"]}',
               "sources": {**case["seller_records"].get("sources", {}), "already_refunded": "Your case record"}}
    return {**case, "seller_records": records}


def find_case_of_dispute(did: str) -> dict | None:
    """The case a PayPal dispute belongs to, if another channel joined it. Reads only: never starts a case file."""
    path = CASE_FILES[shop_of_case(did)]
    return cases_mod.CaseStore(path).by_dispute(did) if path.exists() else None


def receive(src: str, body) -> tuple:
    """Another system -> Second Look: one request (an email, a web form), checked, sorted and filed on its case.
    Returns (HTTP status, JSON): 201 filed, 200 already received (same source_id), 400 what is missing."""
    def bad(why):
        return 400, {"error": why}
    if not isinstance(body, dict):
        return bad("Send one JSON object.")
    if body.get("channel") not in REQUEST_CHANNELS:
        return bad('channel must be "email" or "form". Phone calls arrive in a later step; PayPal disputes are read from PayPal.')
    sender = body.get("from")
    if not isinstance(sender, dict) or not isinstance(sender.get("email"), str) or "@" not in sender["email"]:
        return bad("from.email: the address the request came from.")
    text = body.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 10000:
        return bad("text: what the customer wrote (at most 10,000 characters).")
    for k, most in (("subject", 300), ("source_id", 200), ("time", 40), ("order", 60)):
        v = body.get(k)
        if v is not None and (not isinstance(v, str) or len(v) > most):
            return bad(f"{k}: text of at most {most} characters.")
    name = sender.get("name")
    req = {"channel": body["channel"], "text": text.strip(), "time": body.get("time"), "subject": body.get("subject") or "",
           "source_id": body.get("source_id"), "order": body.get("order"),
           "from": {"name": name.strip() if isinstance(name, str) else None, "email": sender["email"].strip()}}
    c, how = _file_request(case_store(src), src, req, ai=sort_mod.read_with_ai if has_ai_key() else None)
    return (200 if how == "already_received" else 201), {"case_id": c["id"], "filed": how, "stage": c["stage"],
                                                          "sorted": c["sorted"], "dispute_id": c.get("dispute_id"),
                                                          "page": f"/c/{c['id']}"}


def case_view(cid: str) -> dict | None:
    """Everything the case page and the API show about one case, read once. None: no such case in its shop."""
    src = shop_of_case(cid)
    store = case_store(src)
    if store.get(cid) is None:
        return None
    orders, disputes = shop_orders(src), shop_disputes(src)
    by_no = {sort_mod.order_no(o): sort_mod.order_view(o) for o in orders}
    store.link_disputes(disputes, by_no)          # a PayPal dispute opened since on this order joins the case
    c = store.get(cid)
    d = next((x for x in disputes if x["dispute_id"] == c.get("dispute_id")), None)
    order = by_no.get(c.get("order_no"))
    decision = c.get("dispute_id") or cid          # whose review and whose assignment this case uses
    t = team_for(decision)
    a = None if t.get("solo") else assignments_for(decision).get(decision)
    holder = team_mod.person(t, a["to"]) if a and a["to"] else None
    at_stake = float(d["dispute_amount"]["value"]) if d else (_num((order or {}).get("amount")) or 0.0)
    return {"case": c, "dispute": d, "order": order, "src": src, "decision_id": decision, "team": t,
            "timeline": cases_mod.timeline(c, d), "channels": cases_mod.channels(c, d),
            "costs": cases_mod.costs_so_far(c, d, _policy()), "at_stake": at_stake,
            "currency": d["dispute_amount"].get("currency_code", "EUR") if d else (order or {}).get("currency") or "EUR",
            "assigned_to": {"id": holder["id"], "name": holder.get("name"), "role": holder.get("role")} if holder else None}


def pick_order(cid: str, order_no: str, by: str | None) -> tuple:
    """A person says which order an unsorted case is about ("none": a general question). Returns (status, text or case id)."""
    src = shop_of_case(cid)
    store = case_store(src)
    c = store.get(cid)
    if c is None:
        return 404, "No such case."
    none = (order_no or "").strip().lower() == "none"
    if c["sorted"]["by"] and (c.get("order_no") or none):
        return 409, ("This case is already a general question." if none and not c.get("order_no")
                     else "This case is already sorted.")
    t = team_for(cid)
    who = team_mod.person(t, by)
    if not who:
        return 400, "Say who you are: a person in this shop's team."
    if none:
        return 200, store.pick_order(cid, None, who["name"])
    orders = shop_orders(src)
    o = next((x for x in orders if (sort_mod.order_no(x) or "").lower() == (order_no or "").strip().lower()), None)
    if o is None:
        return 400, f"No order {order_no!r} in this shop."
    tx = o.get("transaction_id")
    d = next((x for x in shop_disputes(src) if x.get("status") != "RESOLVED" and tx and _tx_of(x) == tx), None)
    return 200, store.pick_order(cid, sort_mod.order_view(o), who["name"], dispute=d)


def api_case_of(cid: str, as_person: str | None = None) -> dict | None:
    """Other systems -> Second Look: one case as data, what its page shows. `review` and, with ?as=, `for_person`
    are the case's decision's (its PayPal dispute, else the inquiry), the same as GET /api/disputes/<decision_id>."""
    v = case_view(cid)
    if v is None:
        return None
    c = v["case"]
    decision = {}
    if c["sorted"]["by"]:
        full = api_case(v["decision_id"], as_person=as_person)
        decision = {k: full[k] for k in ("review", "for_person", "handoff") if k in full}
    return {**decision, "decision_id": v["decision_id"],
            "case_id": c["id"], "stage": c["stage"], "stage_label": cases_mod.STAGE_LABEL[c["stage"]],
            "status": c["status"], "outcome": c["outcome"], "problem": c["problem"],
            "customer": {**c["customer"], "role": "customer"}, "order": v["order"], "sorted": c["sorted"],
            "at_stake": {"value": v["at_stake"], "currency_code": v["currency"]}, "channels": v["channels"],
            "channel_labels": [cases_mod.CHANNEL_LABEL.get(ch, ch) for ch in v["channels"]],
            "dispute_id": c.get("dispute_id"), "assigned_to": v["assigned_to"],
            "timeline": [{**x, "by": _who(v["team"], x)[0], "role": _who(v["team"], x)[1]} for x in v["timeline"]],
            "costs_so_far": v["costs"], "page": f"/c/{c['id']}"}


# ---------- answering a shop inquiry: the same review, the same limits, the same approval ----------
# An inquiry is reviewed, guarded and approved by the code PayPal disputes use (run_review, apply_policy,
# page_offer, approve). inquiry_case() gives it the shape that code reads; Outbox is where an approved answer
# goes. In this step nothing leaves Second Look: the reply is recorded on the case, signed, on the channel the
# customer used, and the helpdesk hears answer.sent. Money is logged only (paying back by card, bank or
# PayPal's refund API comes in a later step).
OUTBOX_LOGS = {"demo": ROOT / ".tmp" / "actions-demo.jsonl", "live": ROOT / "records" / "actions-inquiries.jsonl"}
OUT_WORDS = {"email": "by email", "form": "by email, to the address on the web form", "call": "by email"}


def reply_channel(c: dict) -> str:
    """The channel an answer goes out on: the one the customer last wrote on."""
    last = [x["channel"] for x in c.get("timeline", []) if x["direction"] == "in" and x["channel"] in OUT_WORDS]
    return last[-1] if last else "email"


def _live_shop() -> dict:
    f = ROOT / "shop.json"
    return json.loads(f.read_text()) if f.exists() else {}


def inquiry_case(cid: str) -> dict:
    """An inquiry as the review and the approval read a case: a "dispute" (the guard's input: the amount at stake
    and the customer's messages, which the guard reads for hidden instructions), its "seller_records" (the order,
    the courier, the shop's terms, each with its source) and the "inquiry" the inquiry judge reads."""
    v = case_view(cid)
    if v is None:
        raise KeyError(f"No case {cid} in this shop.")
    c, o = v["case"], v["order"] or {}
    talk = [x for x in c["timeline"] if x["direction"] in ("in", "out")]
    # What has already gone back on this order: the amount at stake is what is left of it, so a second refund
    # finds nothing (the guard's rule 9) and a partial refund is capped at the rest.
    back = [m for m in c.get("money", []) if m.get("kind") in ("refund", "partial_refund")]
    refunded = round(sum(float(m.get("amount") or 0) for m in back), 2)
    left = max(0.0, round(v["at_stake"] - refunded, 2))
    # The case's real stage: once PayPal has it, the inquiry's review is out of date (and refused: see _inquiry_refusal)
    stage = "SHOP_INQUIRY" if c["stage"] == "inquiry" else c["stage"].upper()
    dispute = {"dispute_id": cid, "reason": "SHOP_INQUIRY", "status": "WAITING_FOR_SELLER_RESPONSE",
               "dispute_life_cycle_stage": stage, "create_time": c["opened"],
               "dispute_amount": {"value": f"{left:.2f}", "currency_code": v["currency"]},
               "messages": [{"posted_by": "BUYER" if x["direction"] == "in" else "SELLER", "content": x["text"],
                             "time_posted": x["at"]} for x in talk]}
    records, sources = {}, {}
    if o:
        records.update(order_no=o["order_no"], order_date=o.get("time") or o.get("date"), paid_with=o["paid_with"],
                       items=[{"name": i["name"], "qty": i["qty"], **({"size": i["size"]} if i.get("size") else {})}
                              for i in o["items"]],
                       ship_to=", ".join(x for x in (o.get("name"), o.get("ship_to")) if x) or None, tracking=o.get("tracking"))
        for k in ("order_no", "order_date", "items", "paid_with", "ship_to"):
            sources[k] = "Your orders"
        sources["tracking"] = "Courier tracking" if o.get("tracking") else "Courier tracking (none on record)"
    evidence_mod.add_shop_terms(records, sources, DemoPayPal().shop if v["src"] == "demo" else _live_shop())
    # the shop's own order amount: only inquiries carry it, so the guard's rule 9 never touches a PayPal dispute
    records["order_amount"] = _num(o.get("amount")) if o else None     # unreadable: no order with an amount
    records["refunded_so_far"] = refunded
    if back:
        when = _t(back[-1].get("at"))
        records["already_refunded"] = (f"{refunded:.2f} {v['currency']}" + (f" on {when:%d %b %Y}" if when else "")
                                       + (f" by {back[-1]['by']}" if back[-1].get("by") else ""))
        sources["already_refunded"] = "Your case record"
    records["sources"] = sources
    ins = [x for x in talk if x["direction"] == "in"]
    first = next((x.get("source_id") for x in c["timeline"] if x.get("source_id")), None)
    inquiry = {"case_id": cid, "channel": reply_channel(c), "customer": c["customer"].get("name"),
               "problem_kind": c["problem"]["kind"], "summary": c["problem"]["summary"],
               "messages": [{"at": x["at"], "channel": x["channel"], "from": x["by"], "direction": x["direction"],
                             "text": x["text"]} for x in talk],
               "last_message_at": ins[-1]["at"] if ins else None, "amount": v["at_stake"], "currency": v["currency"],
               "dispute_id": c.get("dispute_id"),
               # whose case this is: a review is never inherited by another customer, order or request
               "identity": f'{(c["customer"].get("email") or "").strip().lower()}|{c.get("order_no") or ""}|{first or ""}'}
    return {"dispute": dispute, "seller_records": records, "inquiry": inquiry}


def _inquiry_refusal(cid: str) -> str | None:
    """Why an inquiry can't be reviewed or answered as an inquiry right now, or None. Read through case_view,
    so a PayPal dispute opened since on its order is seen first."""
    v = case_view(cid)
    if v is None:
        return "No such case."
    c = v["case"]
    if not c["sorted"]["by"]:
        return "Pick the order first: an unsorted request has no evidence to check."
    if c.get("dispute_id"):
        return f"This case is a PayPal dispute now: answer it on {c['dispute_id']}."
    return None


def review_inquiry(cid: str, judge: str) -> Decision:
    """Second Look's AI (or, with no key, the rules baseline) on an inquiry, then the guard, unchanged."""
    no = _inquiry_refusal(cid)
    if no:
        raise ValueError(no)
    case = _case(cid)
    policy = _policy()
    case["seller_preferences"] = policy.get("seller_preferences", [])
    j = judge_mod.INQUIRY_BACKENDS[judge](case)
    if j.action == "DEFEND":  # there is no claim to defend in an inquiry: the guard routes an answer it doesn't know
        j = replace(j, action="DEFEND_IS_FOR_PAYPAL_DISPUTES")
    return apply_policy(j, policy, case["dispute"], case["seller_records"])


class Outbox:
    """The approved answer to an inquiry, recorded: a signed "out" entry on the case's timeline, on the channel
    the customer used, any money as a logged entry on the case, and one line in the action log. The same
    interface as the PayPal clients, so execute() runs it unchanged. Nothing is sent from here in this step."""

    def __init__(self, cid: str, by: str, ai: bool, amount: float):
        self.cid, self.by, self.ai, self.amount = cid, by, ai, amount
        self.src = shop_of_case(cid)

    def _out(self, action: str, text: str, money: dict | None = None) -> dict:
        store = case_store(self.src)
        ch = reply_channel(store.get(self.cid))

        def change(c):
            c["timeline"].append(cases_mod.entry(None, ch, "out", text, self.by, ai=self.ai, action=action))
            if money:
                c["money"].append({**money, "at": cases_mod.minute(None), "by": self.by})
        store.update(self.cid, change)
        log = OUTBOX_LOGS[self.src]
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": cases_mod.minute(None), "case_id": self.cid, "action": action, "channel": ch,
                                "by": self.by, "text": text, **({"money": money} if money else {})},
                               ensure_ascii=False) + "\n")
        return {"status": "LOGGED", "channel": ch}

    def message(self, did, text):
        return self._out("reply", text)

    def refund(self, did, note):
        return self._out("refund", note, {"kind": "refund", "amount": self.amount})

    def partial_refund(self, did, amount, currency, note):
        return self._out("partial_refund", note, {"kind": "partial_refund", "amount": float(amount)})

    def replace(self, did, note):
        return self._out("replace", note)

    def defend(self, did, note, tracking=None):
        raise RuntimeError("An inquiry has no PayPal evidence to submit: nothing was sent.")


def review_with_case_refund(did: str, judge: str) -> Decision:
    """A PayPal dispute whose case already logged a refund: the same review, reading the records that say so."""
    case = _case(did)
    policy = _policy()
    case["seller_preferences"] = policy.get("seller_preferences", [])
    j = judge_mod.BACKENDS[judge](case)
    return apply_policy(j, policy, case["dispute"], case["seller_records"])


def _about(did: str) -> dict:
    """What a notification is about, so a helpdesk can put it on the right ticket: the case, and the channel
    its answer uses. A PayPal dispute keeps its dispute_id, as before."""
    if cases_mod.is_case_id(did):
        c = case_store(shop_of_case(did)).get(did) or {}
        return {"case_id": did, "channel": reply_channel(c)}
    c = find_case_of_dispute(did)
    return {"dispute_id": did, "case_id": c["id"] if c else None, "channel": "paypal"}


CLOSE_OUTCOMES = {"solved": "Solved before any dispute", "refunded": "Refunded", "replaced": "Replaced or exchanged",
                  "withdrawn": "The customer withdrew"}


def close_case(cid: str, outcome: str, by: str | None) -> tuple:
    """A person closes an inquiry with its outcome. A case with a PayPal dispute is closed by PayPal, not here."""
    if not cases_mod.is_case_id(cid):
        return 404, "No such case."
    store = case_store(shop_of_case(cid))
    c = store.get(cid)
    if c is None:
        return 404, "No such case."
    if c.get("dispute_id"):
        return 409, "This case is a PayPal dispute: PayPal closes it."
    if c["status"] != "open":
        return 409, "This case is closed already."
    if outcome not in CLOSE_OUTCOMES:
        return 400, f"Outcome must be one of: {', '.join(CLOSE_OUTCOMES)}."
    who = team_mod.person(team_for(cid), by)
    if not who:
        return 400, "Say who you are: a person in this shop's team."

    def close(x):
        x["status"], x["outcome"] = "closed", outcome
        x["timeline"].append(cases_mod.entry(None, reply_channel(x), "note",
                                             f"Closed by {who['name']}: {CLOSE_OUTCOMES[outcome].lower()}.", who["name"]))
    store.update(cid, close)
    return 200, f"Closed: {CLOSE_OUTCOMES[outcome].lower()}."


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
# A "Pass to" button sends nothing to PayPal: its busy label must not say so.
PASS_LOCK = LOCK.replace("Sending to PayPal…", "Passing it on…")

TEACH = ('<details class="teach"><summary>Suggest a rule for later (nothing changes now)</summary>'
         '<label for="rule">Write it down while it is fresh. It waits on Your rules, next to this case, '
         'until you read it there with your other rules and accept it.</label>'
         '<input id="rule" name="rule" maxlength="300" '
         'placeholder="For example: never promise a delivery date, only a shipping date."></details>')


def rules_page(flash: str = "", demo: bool = False, me: str | None = None) -> str:
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
    st = cases_mod.staff_time(pol)
    limits.append(f'A case\'s staff time is estimated at {st["hourly_cost"]:g} {cur} an hour; each written answer counts '
                  f'{st["reply_minutes"]:g} minutes, a call its own length.')
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
    return page("Your rules | Second Look", "", body, demo, me=me, here="rules")

# What a review was based on. If any of it changes, the review is out of date and Approve is withdrawn:
# the seller must never approve an answer to a situation that no longer exists.
CHANGED = {"buyer_messages": "the buyer wrote again", "stage": "PayPal moved the case to another stage",
           "amount": "the amount in dispute changed", "tracking": "tracking was added or changed",
           "ship_to": "PayPal now shows the buyer's address",
           "case_refund": "a refund was logged on this order's case"}


# The same, for a shop inquiry, in its own words; "who" is whose case it is (customer, order, first request).
CHANGED_INQUIRY = {"buyer_messages": "the customer wrote again", "stage": "the case became a PayPal dispute",
                   "amount": "the amount at stake changed (a refund was logged, or the order changed)",
                   "tracking": "the courier's tracking changed", "ship_to": "the delivery address changed",
                   "who": "the case is now about another customer or order"}


def _seen(case: dict) -> dict:
    d, r = case["dispute"], case["seller_records"]
    seen = {"buyer_messages": sum(1 for m in d.get("messages", []) if m.get("posted_by") == "BUYER"),
            "stage": d.get("dispute_life_cycle_stage"), "amount": d["dispute_amount"]["value"],
            "tracking": (r.get("tracking") or {}).get("tracking_number"), "ship_to": bool(r.get("ship_to"))}
    if case.get("inquiry"):
        seen["who"] = case["inquiry"].get("identity")
    if r.get("refund_logged_on_case"):   # only then: a dispute whose case logged no money sees exactly what it saw
        seen["case_refund"] = r.get("refunded_so_far")
    return seen


def _changes(dispute_id: str, case: dict) -> list:
    raw = _raw(dispute_id)  # a shipped demo review is judged by what it saw, like any other
    seen = raw.get("seen") if raw is not None else None
    if seen is None:
        return ["this review was saved before Second Look tracked changes"]
    now = _seen(case)
    words = CHANGED_INQUIRY if cases_mod.is_case_id(dispute_id) else CHANGED
    return [words[k] for k in words if seen.get(k) != now.get(k)]


def _t(iso):
    try:
        return datetime.strptime(str(iso)[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        pass
    try:
        return datetime.strptime(str(iso)[:16], "%Y-%m-%dT%H:%M")  # how Second Look saves who sent what, when
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
    marks, prev, rows = [], None, ([], [], [], [])
    for label, t in points:
        x = 3 + 94 * (t - t0).total_seconds() / span
        level = label_row(x, rows)
        rows[level].append(x)
        lift = ["", " lift", " lift2", " low"][level]
        gap = f'<span class="gap">{e(_gap(prev, t))}</span>' if prev and label == "Dispute opened" else ""
        when = f"{t:%d %b}" if (t.hour, t.minute) == (0, 0) else f"{t:%d %b, %H:%M}"
        marks.append(f'<li class="mark{lift}{" hot" if gap else ""}" style="left:{x:.2f}%">'
                     f'<span class="lab"><b>{e(label)}</b><time>{when}</time>{gap}</span></li>')
        prev = t
    deep = " deep" if rows[3] else ""  # a fourth row, under the first: the ruler makes room for it
    return f'<ol class="ruler{deep}" aria-label="Timeline">{"".join(marks)}</ol>'


# A label is about 130 px wide on a ruler about 600 px wide: two labels closer than this (in % of the
# ruler) would touch. Checking only the previous mark let a third label land on the first one's row
# (DEMO-031: "Paid" and "Delivered" ran together).
LABEL_ROOM = 24.0


def label_row(x: float, rows: tuple) -> int:
    """The first row (0 below the line, 1 above it, 2 higher above, 3 lower below) with no label within
    LABEL_ROOM of x.
    When every row is taken, the row whose nearest label is furthest away."""
    def room(row):
        return min((abs(x - other) for other in row), default=float("inf"))
    for level, row in enumerate(rows):
        if room(row) >= LABEL_ROOM:
            return level
    return max(range(len(rows)), key=lambda level: room(rows[level]))


def evidence(r: dict, inquiry: bool = False) -> str:
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
                 + (f', {v["delivered_to"]}' if v.get("delivered_to") else "") if v else "none registered yet")
        elif k == "order_date":
            t = _t(v)
            v = f"{t:%d %b %Y, %H:%M}" if t else v
        tag = src.get(k, "practice case")
        tag = {"PayPal Transaction Search": "PayPal order", "seller's notes": "Your notes",
               "PayPal disputes and Transaction Search": "PayPal history"}.get(tag, tag)
        tag = "Your shop terms" if tag.startswith("shop.json") else tag
        tag = "PayPal tracking" if tag.startswith("PayPal tracking") else tag
        # the tag's look says how much the fact can be relied on: PayPal's records, your published terms, your word
        kind = "paypal" if tag.startswith("PayPal") else "shop" if tag in ("Your shop terms", "Your orders", "Your case record") or \
            tag.startswith("Courier tracking") else \
               "notes" if tag == "Your notes" else "practice"
        rows.append(f'<div class="ev"><dt>{e(label)}</dt><dd>{e(str(v))}</dd>'
                    f'<dd class="tag"><span class="src {kind}">{e(tag)}</span></dd></div>')
    for k, why in (r.get("unavailable") or {}).items():
        rows.append(f'<div class="ev missing"><dt>{e(EVIDENCE_LABEL.get(k, k))}</dt><dd>{e(why)}</dd></div>')
    legend = ('<p class="legend"><span class="src paypal">PayPal</span> PayPal\'s own records '
              '<span class="src shop">Your shop terms</span> what you published '
              '<span class="src notes">Your notes</span> your word only</p>')
    if inquiry:   # a shop inquiry: only the kinds of source it shows (often no PayPal record at all)
        shown = set(re.findall(r'class="src (\w+)"', "".join(rows)))
        parts = [("paypal", "PayPal", "PayPal's own records"),
                 ("shop", "Your records", "your orders, the courier and what you published"),
                 ("notes", "Your notes", "your word only")]
        legend = ('<p class="legend">' + " ".join(f'<span class="src {k}">{t}</span> {e(says)}' for k, t, says in parts
                                                  if k in shown) + '</p>') if shown else ""
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


def checks(j: Judgment, labels: dict = CHECKS) -> str:
    out = []
    for result, title, cls in GROUPS:
        rows = [f'<li class="check {cls}"><b>{e(labels.get(c["id"], c["id"]))}</b><q>{e(c["finding"])}</q></li>'
                for c in j.checks if _bucket(c) == result]
        if rows:
            out.append(f'<section class="group {cls}"><h4>{e(title)} <span>{len(rows)}</span></h4>'
                       f'<ul class="checks">{"".join(rows)}</ul></section>')
    na = [labels.get(c["id"], c["id"]).lower() for c in j.checks if _bucket(c) == "NOT_APPLICABLE"]
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
.person summary{{flex-wrap:wrap;row-gap:0}} .person summary small{{flex-basis:100%;color:var(--soft);font-size:13px;font-weight:400}}
.mono{{display:inline-grid;place-items:center;width:34px;height:34px;border-radius:50%;color:#fff;font:700 13px "Schibsted Grotesk",sans-serif;letter-spacing:.5px}}
.mode{{font-size:14px;font-weight:500;padding:3px 10px;border-left:3px solid var(--ctx);background:#fff;color:var(--ink)}}
.count{{display:inline-block;margin-left:6px;padding:0 8px;border-radius:10px;background:var(--incon);color:#fff;font-size:12px;font-weight:700;text-decoration:none}}
.pill{{display:inline-block;padding:2px 10px;border-radius:12px;font-size:13px;font-weight:700;margin-right:6px;vertical-align:1px}}
.pill.you{{background:#F6E6C8;color:#7A4E0C}} .pill.buyer{{background:#DDEBE1;color:var(--pass)}}
.pill.paypal{{background:#E4E7EA;color:var(--soft)}} .pill.onclaim{{background:#EEDDE9;color:var(--fail)}}
.filters{{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:6px 0 10px}}
.tabs{{display:flex;gap:6px;margin:4px 0 14px}} .tabs a{{padding:7px 14px;border:1px solid var(--rule);text-decoration:none;font-size:15px}}
.tabs a[aria-current]{{background:var(--ink);color:#fff;border-color:var(--ink)}} .tabs b{{font-variant-numeric:tabular-nums;margin-left:4px}}
.owner{{margin-left:10px;padding:2px 8px;border:1px solid var(--rule);font-size:13px;color:var(--soft)}}
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
.mark.lift .lab{{top:auto;bottom:16px}} .mark.lift2 .lab{{top:auto;bottom:56px}} .mark.low .lab{{top:92px}}
.ruler.deep{{height:265px}}
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
.owner-line{{margin:0 0 16px;color:var(--soft)}} button.link{{background:none;border:0;padding:0;color:var(--ink);text-decoration:underline;font:inherit;cursor:pointer}}
.sent b{{font-size:20px}}
.talk{{list-style:none;padding:0;margin:0 0 28px;max-width:640px}} .talk li{{padding:10px 0 10px 16px;border-left:4px solid var(--rule);margin-bottom:8px}}
.talk b{{display:block;font-size:14px;font-weight:500;color:var(--soft)}} .talk q{{quotes:none;font-family:Newsreader,Georgia,serif;font-style:italic;font-size:19px}}
.talk li.buyer{{border-color:var(--fail)}} .talk li.you{{border-color:var(--ink)}} .talk li.proof{{border-color:var(--pass)}}
.stale{{padding:14px 18px;background:#FBF3E4;border-left:4px solid var(--incon);margin:0 0 14px}}
.judged{{padding:14px 18px;background:#ECEEEF;border-left:4px solid var(--unclear);margin:0 0 18px;font-size:16px}}
.judged b{{display:block;margin-bottom:4px}} .judged form{{margin-top:10px}}
.judged button{{font:700 15px "Schibsted Grotesk",sans-serif;padding:8px 16px;border:0;background:var(--ink);color:var(--paper);cursor:pointer}}
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
.check-sender{{border-left:4px solid var(--incon);background:#fff;padding:8px 12px;margin:12px 0}}
.pill.shop{{background:var(--kraft-bg);color:#6E4F27}} .chan{{display:inline-block;min-width:24px}}
.ai-tag{{display:inline-block;margin-left:8px;padding:0 6px;font-size:12px;font-weight:500;border:1px solid var(--kraft);color:#6E4F27;background:#fff}}
.talk .t-sub{{display:block}} .pick input{{width:100%;font:400 16px "Schibsted Grotesk",sans-serif;padding:10px 12px;border:1px solid var(--rule);background:#fff}}
.pick label{{display:block;font-weight:700;margin:12px 0 6px}}
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


# The request being answered, for the person switch: its links keep the rest of the address (?view=mine).
_REQUEST = threading.local()


def person_badge(t: dict, me: str | None, qs: dict | None = None, currency: str = "") -> str:
    """Who you are in a team, and the switch to a colleague. Nothing for a team of one, or for a team
    file that lists nobody usable."""
    if t.get("solo"):
        return ""
    p = team_mod.person(t, me) or team_mod.first(t)
    if not p:
        return ""
    qs = getattr(_REQUEST, "qs", {}) if qs is None else qs
    keep = [(k, v) for k, vs in qs.items() if k != "as" for v in vs]
    cap = team_mod.limit(t, p["id"])
    may = ("sends any amount the limits hand to a person" if cap is None
           else f"sends refunds up to {cap:.0f}" + (f" {currency}" if currency else ""))
    menu = "".join(f'<a href="?{e(urlencode(keep + [("as", o["id"])]))}"><span>{e(str(o.get("name") or o["id"]))}'
                   f'<small>{e(str(o.get("role") or ""))}</small></span></a>'
                   for o in team_mod.people(t) if o["id"] != p["id"])
    return (f'<details class="shop person"><summary>You are <b>{e(str(p.get("name") or p["id"]))}</b>'
            f'<small>{e(str(p.get("role") or ""))} · {e(may)}</small><span class="switch">Switch</span></summary>'
            f'<div class="shop-menu">{menu}</div></details>')


MARK = ('<svg class="mark-logo" width="30" height="22" viewBox="0 0 30 22" aria-hidden="true">'
        '<circle cx="11" cy="11" r="9" fill="#B5874F"/><circle cx="19" cy="11" r="9" fill="none" stroke="#1E2935" stroke-width="3"/></svg>')


def _shop_currency(t: dict, demo: bool) -> str:
    """The currency a role's limit is in: the team block's own, else the demo shop's disputes'. None known: none shown."""
    if isinstance(t.get("currency"), str):
        return t["currency"]
    if demo:
        ds = DemoPayPal().disputes()
        return ds[0]["dispute_amount"].get("currency_code", "") if ds else ""
    return ""


def page(title: str, mode: str, body: str, demo: bool = False, me: str | None = None, here: str = "disputes") -> str:
    """`here`: the section the page belongs to ("disputes", "overview" or "rules"), said by the page itself.
    It used to be guessed from the title and the body's first characters, and a list page whose intro says
    "customer care" was marked Overview."""
    q = "?shop=demo" if demo else ""
    waiting = len(suggestions())
    rules = f'Your rules<span class="count">{waiting} to review</span>' if waiting else "Your rules"
    context = "demo" if demo else "practice" if mode.startswith("Practice") else "live"
    cur = lambda k: ' aria-current="page"' if here == k else ""  # noqa: E731
    nav = (f'<nav><a href="/{q}"{cur("disputes")}>Disputes</a><a href="/overview"{cur("overview")}>Overview</a>'
           f'<a href="/rules"{cur("rules")}>{rules}</a>'
           f'<span class="mode {context}">{e(DEMO_LABEL if demo else mode or "PayPal sandbox")}</span></nav>')
    t = team_for("DEMO-" if demo else None) if context != "practice" else team_mod.of(None)
    who = person_badge(t, me, currency=_shop_currency(t, demo)) if not t.get("solo") else ""
    return PAGE.format(title=title, nav=nav, body=body, context=context, shop=shop_badge(context) + who, mark=MARK)


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


def in_view(view: str, a: dict, me: str | None) -> bool:
    return view == "all" or (view == "mine" and a["to"] == me) or (view == "unassigned" and not a["to"])


def owner_tag(t: dict, a: dict) -> str:
    if not a["to"]:
        return "Unassigned"
    who = team_mod.person(t, a["to"])
    name = who["name"] if who else a["to"]
    hand = a.get("handoff")
    return name + (f' · passed by {hand.get("from_name")}' if isinstance(hand, dict) and hand.get("from_name") else "")


def inbox_page(src: str, me: str | None = None, view: str = "") -> str:
    practice, demo = src == "practice", src == "demo"
    pp = DemoPayPal() if demo else MockPayPal(ROOT / "cases", ROOT / ".tmp" / "actions.jsonl") if practice else client_from_env(ROOT)
    t = team_for_src(src)
    # In a team: who has which case, read once for the whole list (a team of one has no owners or tabs).
    assigned = None if t.get("solo") else assignments_for("DEMO-" if demo else None).all()
    owner_of = lambda did: assigned.get(did, {"to": None, "handoff": None})  # noqa: E731
    view = view if view in ("mine", "unassigned", "all") else "all"
    today = pp.today if demo else datetime.utcnow().date()
    items = []
    for state in (["REQUIRED_ACTION"] if practice else ["REQUIRED_ACTION", "REQUIRED_OTHER_PARTY_ACTION"]):
        items += pp.list_disputes(state)
    seen, rows = set(), []
    for d in items:
        if d["dispute_id"] in seen:
            continue
        seen.add(d["dispute_id"])
        a = owner_of(d["dispute_id"]) if assigned is not None else None
        if a is not None and not in_view(view, a, me):
            continue
        owner = f' <span class="owner">{e(owner_tag(t, a))}</span>' if a is not None else ""
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
                     f'<span class="meta">{pill_for(full)} {e(REASON.get(full.get("reason"), full.get("reason", "")))}.{e(claim)} {e(waiting)}{owner}</span></a></li>'))
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
    tabs = ""
    if assigned is not None:  # counts over every open case, whichever view is showing
        counts = {v: sum(1 for did in seen if in_view(v, owner_of(did), me)) for v in ("mine", "unassigned", "all")}
        tabs = '<p class="tabs">' + "".join(
            f'<a href="?view={v}"{" aria-current=page" if v == view else ""}>{label} <b>{counts[v]}</b></a>'
            for v, label in (("mine", "Mine"), ("unassigned", "Unassigned"), ("all", "Everyone"))) + "</p>"
    body = (f'<h1 class="page">{e(title)}</h1>{about}<p class="who">{other}</p>{whatnow}{tabs}'
            + ('<div class="filters" role="search"><input id="q" type="search" placeholder="Search what the buyer said, reason, amount" '
               'aria-label="Search disputes"></div><script>addEventListener("DOMContentLoaded",()=>{const q=document.getElementById("q"),rows=[...document.querySelectorAll(".inbox li")];'
               'q.addEventListener("input",()=>rows.forEach(r=>r.hidden=!!q.value&&!r.textContent.toLowerCase().includes(q.value.toLowerCase())))});</script>'
               if len(rows) > 3 else "")
            + (f'<ul class="inbox">{"".join(rows)}</ul>' if rows else
               '<p class="empty">No open disputes. When a buyer opens one, it appears here.</p>')
            + requests_block(src, me, view, t))
    return page("Second Look", "Practice cases" if practice else "PayPal sandbox", body, demo, me=me)


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


def overview_page(src: str, me: str | None = None) -> str:
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
    return page("Overview | Second Look", "PayPal sandbox", body, demo, me=me, here="overview")


def customer_page(key: str, src: str, me: str | None = None) -> str:
    demo = src == "demo"
    pp, disputes, orders, today = _shop(src)
    handled = (pp.raw.get("handled_by") or {}) if src == "demo" else {}
    cu = ledger.customer(key, disputes, orders, today)
    q = "?shop=demo" if demo else ""
    if not cu:
        return page("Customer | Second Look", "PayPal sandbox", '<h1 class="page">No customer with that id or email.</h1>', demo,
                    me=me, here="overview")
    rate = (f'{len(cu["disputes"])} disputes in {cu["orders"]} orders ({cu["dispute_rate"]:.0%}). '
            f'Your shop: {cu["shop_dispute_rate"]:.1%}.' if cu["dispute_rate"] is not None else "")
    if cu["times_shop_rate"]:
        rate += f' {cu["times_shop_rate"]:.0f}× your usual rate.' if cu["times_shop_rate"] >= 2 else " About your usual rate."
    rows = "".join(f'<tr><td>{e(x["opened"])}</td><td><a href="/d/{e(x["dispute_id"])}">{e(x["reason"])}</a></td>'
                   f'<td>{x["amount"]:.2f}</td><td>{"PayPal claim" if x["escalated"] else "Inquiry"}</td>'
                   f'<td>{e(x["outcome"])}{(" · " + e(handled[x["dispute_id"]])) if x["dispute_id"] in handled else ""}</td></tr>'
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
    return page(f"{cu['name'] or 'Customer'} | Second Look", "PayPal sandbox", body, demo, me=me, here="overview")


def customer_json(key: str, src: str) -> dict | None:
    _, disputes, orders, today = _shop(src)
    return ledger.customer(key, disputes, orders, today)


# ---------- the case page: one customer, one order, one problem, every channel ----------

def _role_of(t: dict, x: dict) -> str:
    """Every name carries its role. Whoever wrote in is the customer, under any name or address they used
    (no name, "Sophie" for "Sophie Durand", a second address a person joined to the case); a colleague
    carries their role from the team; PayPal and "the shop" are names that say what they are."""
    if x.get("direction") == "in":
        return "customer"
    p = next((y for y in team_mod.people(t) if y.get("name") and y.get("name") == x.get("by")), None)
    return str(p.get("role") or "") if p else ""


def _who(t: dict, x: dict) -> tuple:
    """(name, role) of one timeline entry: unsigned text Second Look's AI wrote is the AI's."""
    name = str(x.get("by") or "")
    if not name and x.get("ai"):
        return "Second Look's AI", ""
    return name, _role_of(t, x)


def _channel(ch: str, capital: bool = False) -> str:
    """A channel's icon and name, as HTML: "✉️ email"; PayPal, whose icon is its name, said once. Brand
    names keep their own capitals ("PayPal", never "Paypal")."""
    icon, label = cases_mod.CHANNEL_ICON.get(ch, ch), cases_mod.CHANNEL_LABEL.get(ch, ch)
    shown = label[:1].upper() + label[1:] if capital else label
    return e(icon) if icon.lower() == label.lower() else f"{e(icon)} {e(shown)}"


def _when(at: str) -> str:
    t = _t(at)
    return f"{t:%d %b, %H:%M}" if t else ""


def timeline_block(v: dict) -> str:
    """Every contact in time order: channel, in or out, who (with their role), and whether Second Look's AI wrote it."""
    c, t = v["case"], v["team"]
    rows = []
    for x in v["timeline"]:
        icon, label = cases_mod.CHANNEL_ICON.get(x["channel"], x["channel"]), cases_mod.CHANNEL_LABEL.get(x["channel"], x["channel"])
        what = {"in": "in", "out": "out", "note": ""}[x["direction"]]
        name, role = _who(t, x)
        who = e(name) + (f", <i>{e(role)}</i>" if role else "")
        ai = '<span class="ai-tag">Second Look\'s AI</span>' if x.get("ai") else ""
        # the channel's name after its icon, unless the icon is the name (PayPal): "✉️ Email in", "PayPal in"
        said = " ".join(w for w in ("" if icon.lower() == label.lower() else label[:1].upper() + label[1:], what) if w)
        head = (f'<b><span class="chan" title="{e(label)}">{e(icon)}</span>{" " + e(said) if said else ""} · {who} · '
                f'{e(_when(x["at"]))}{ai}</b>')
        subject = f'<span class="t-sub">{e(x["subject"])}</span>' if x.get("subject") else ""
        body = f'<q>{e(x.get("text") or "")}</q>' if x["direction"] != "note" else f'<span>{e(x.get("text") or "")}</span>'
        srt = x.get("sorted") or {}
        sort_line = (f'<span class="t-sub">{e(srt["how"])}'
                     + ('<span class="ai-tag">Second Look\'s AI</span>' if srt.get("by") == "ai" else "") + '</span>'
                     if srt.get("how") else "")
        cls = {"in": "buyer", "out": "you", "note": "proof"}[x["direction"]]
        rows.append(f'<li class="{cls}">{head}{subject}{body}{sort_line}</li>')
    return f'<h2>Everything said, every channel</h2><ol class="talk">{"".join(rows)}</ol>'


def case_costs_block(v: dict) -> str:
    k, cur = v["costs"], v["currency"]
    m = lambda x: f"{x:,.2f} {cur}"  # noqa: E731
    by = {}
    for x in v["timeline"]:
        if x["direction"] in ("in", "out"):
            by[x["channel"]] = by.get(x["channel"], 0) + 1
    split = ", ".join(f"{n} by {cases_mod.CHANNEL_LABEL.get(ch, ch)}" for ch, n in by.items())
    how = (f"{k['replies']} written answer{'s' if k['replies'] != 1 else ''} × {k['reply_minutes']:g} minutes"
           + (f", calls {k['minutes'] - k['replies'] * k['reply_minutes']:g} minutes" if k["calls"] else "")
           + f", at {k['hourly_cost']:g} {cur} an hour (your rules)")
    rows = [("Contacts", f"{k['contacts']}" + (f" ({split})" if split else "")),
            ("Staff time", f"{k['minutes']:g} minutes, about {m(k['staff_cost'])}. Estimated: {how}."),
            ("Fees", m(k["fees"])), ("Money moved", m(k["money_moved"]))]
    trs = "".join(f'<tr><th scope="row">{e(a)}</th><td>{e(b)}</td></tr>' for a, b in rows)
    return f'<section class="costs"><h2>Cost so far <span class="t-sub">estimated</span></h2><table>{trs}</table></section>'


def case_summary(c: dict) -> str:
    """The case's one line, as plain text. Written by Second Look's AI (it sorted the case): shown as its reading
    of the customer's message, never as something the shop says. Otherwise the customer's own subject or words."""
    line = c["problem"]["summary"] or cases_mod.KIND_LABEL[c["problem"]["kind"]]
    return f"Second Look's AI reads this as: {line}" if c["sorted"].get("by") == "ai" else line


def _pick_form(cid: str, me: str | None, how: str, question: bool = False) -> str:
    """Which order an unsorted case is about; for a case sorted as a question (no order), the order it turns out
    to be about after all."""
    by = f'<input type="hidden" name="by" value="{e(me)}">' if me else ""
    none = ("" if question else
            '<button class="quiet" name="order" value="none">A general question: no order</button>')
    return (f'<form class="pick" method="post" action="/c/{e(cid)}/order">'
            f'<h2>{"Is it about an order?" if question else "Which order is it about?"}</h2>'
            f'<p class="who">{e(how)}</p>{by}<label for="order">Order number</label>'
            '<input id="order" name="order" maxlength="60" placeholder="For example LP-90001">'
            f'<div class="approve"><button>This order</button>{none}</div></form>')


def _close_form(cid: str, me: str | None) -> str:
    by = f'<input type="hidden" name="by" value="{e(me)}">' if me else ""
    opts = "".join(f'<option value="{e(k)}">{e(v)}</option>' for k, v in CLOSE_OUTCOMES.items())
    return (f'<form class="pick" method="post" action="/c/{e(cid)}/close"><label for="outcome">Close this case</label>'
            f'{by}<select id="outcome" name="outcome">{opts}</select><div class="approve"><button class="quiet">Close it</button>'
            '<span>Only when it is settled: a new message from the customer opens a new case.</span></div></form>')


def case_file_page(cid: str, me: str | None = None, flash: str = "") -> str:
    v = case_view(cid)
    demo = v is not None and v["src"] == "demo"
    if v is None:
        return page("No such case | Second Look", "", '<h1 class="page">No case with that id in this shop.</h1>', is_demo(cid), me=me)
    c, d, o = v["case"], v["dispute"], v["order"]
    cur = v["currency"]
    stage = f'<span class="pill {"shop" if c["stage"] == "inquiry" else "onclaim" if c["stage"] == "paypal_claim" else "paypal"}">' \
            f'{e(cases_mod.STAGE_LABEL[c["stage"]])}</span>'
    if c["status"] != "open":
        stage += f'<span class="pill buyer">Closed: {e(str(c["outcome"] or ""))}</span>'
    cust = c["customer"]
    items = ", ".join(f'{i["name"]} × {i["qty"]}' + (f' (size {i["size"]})' if i.get("size") else "") for i in (o or {}).get("items", []))
    paid = {"paypal": "PayPal", "card": "card", "bank": "bank transfer"}.get((o or {}).get("paid_with"), (o or {}).get("paid_with"))
    amt = _num(o.get("amount")) if o else None
    order_line = (f'Order {e(o["order_no"])}: {e(items)}, '
                  f'{f"{amt:.2f} {e(cur)}" if amt is not None else "amount not on record"}, paid by {e(str(paid))}.' if o else
                  "No order: a general question." if c["sorted"]["by"] else "Order not known yet.")
    came = " · ".join(_channel(ch) for ch in v["channels"])
    holder = v["assigned_to"]
    senders = []
    for x in c["timeline"]:
        sender = (x.get("from") or {}).get("email")
        if (x["direction"] == "in" and sender and c.get("order_no") and sender not in senders
                and sender.strip().lower() != (cust.get("email") or "").strip().lower()):
            senders.append(sender)
    check = "".join(f'<p class="check-sender">This order belongs to {e(cust.get("name") or cust.get("email") or "")}, '
                    f'not to the sender {e(s)}: check before answering.</p>' for s in senders)
    owner = ("" if v["team"].get("solo") else
             f'<p class="owner-line">{e(holder["name"])}, <i>{e(holder["role"] or "")}</i>, has this case.</p>' if holder
             else '<p class="owner-line">Nobody has this case yet.</p>')
    left = (f'<a class="back" href="/{"?shop=demo" if demo else ""}">All disputes and requests</a>{stage}'
            f'<p class="claim{"" if c["sorted"].get("by") == "ai" else " quote"}">{e(case_summary(c))}</p>'
            f'<p class="who">{e(cust.get("name") or cust.get("email") or "")}, <i>customer</i> · {e(cust.get("email") or "")}<br>'
            f'{order_line} At stake: {v["at_stake"]:.2f} {e(cur)}.<br>Came in by: {came}</p>{check}{owner}'
            f'{timeline_block(v)}')
    if d:
        # A PayPal dispute now: PayPal's rules, and the dispute's own review and buttons, right here.
        right = (f'<div class="judged"><b>This case is a PayPal dispute now: {e(d["dispute_id"])}.</b> PayPal\'s rules '
                 f'apply, and the answer goes to PayPal. <a href="/d/{e(d["dispute_id"])}">The dispute\'s own page</a>.</div>'
                 + review_column(d["dispute_id"], _case(d["dispute_id"]), me, plain_owner=False))
    elif not c["sorted"]["by"]:
        right = _pick_form(cid, me, c["sorted"]["how"] or "")
    else:
        case = _case(cid)
        left += f'<h2>What the evidence says</h2>{evidence(case["seller_records"], inquiry=True)}' if o else ""
        right = (review_column(cid, case, me, plain_owner=False)
                 + (_close_form(cid, me) if c["status"] == "open" else ""))
        if not c.get("order_no"):
            right += _pick_form(cid, me, "Sorted as a question with no order. If it is about one, say which.", question=True)
    body = (f'<div class="case"><section>{flash}{left}</section><section class="look">{right}{case_costs_block(v)}'
            f'<p class="cardlink"><a href="/api/cases/{e(cid)}">This case as data (API)</a></p></section></div>')
    # the tab's name: the customer's own words, or the case id when the line is Second Look's AI's reading
    title = (f"Case {c['id']}" if c["sorted"].get("by") == "ai" else c["problem"]["summary"][:40]
             or cases_mod.KIND_LABEL.get(c["problem"]["kind"]) or f"Case {c['id']}")
    return page(f"{e(title)} | Second Look", "PayPal sandbox", body, demo, me=me)


def requests_block(src: str, me: str | None, view: str, t: dict) -> str:
    """The open cases that came in by email or web form and have no PayPal dispute, under the disputes list."""
    if src == "practice":
        return ""
    store = case_store(src)
    rows = []
    for c in store.all():
        if c["status"] != "open" or c.get("dispute_id"):
            continue
        a = None if t.get("solo") else assignments_for(c["id"]).get(c["id"])
        if a is not None and not in_view(view, a, me):
            continue
        icons = " ".join(cases_mod.CHANNEL_ICON[x["channel"]] for x in c["timeline"] if x["direction"] == "in")
        owner = f' <span class="owner case-owner">{e(owner_tag(t, a))}</span>' if a is not None else ""
        sorted_ = "" if c["sorted"]["by"] else " · Unsorted: pick the order"
        rows.append(f'<li><a href="/c/{e(c["id"])}"><blockquote>{e(case_summary(c))}</blockquote>'
                    f'<span class="meta"><span class="pill shop">Shop inquiry</span> {e(icons)} '
                    f'{e(c["customer"].get("name") or c["customer"].get("email") or "")}, customer · '
                    f'{e(cases_mod.KIND_LABEL[c["problem"]["kind"]])}{e(sorted_)}{owner}</span></a></li>')
    if not rows:
        return ""
    return (f'<h2 style="margin-top:40px">Requests by email and web form <span class="t-sub">{len(rows)} open</span></h2>'
            f'<ul class="inbox">{"".join(rows)}</ul>')


EVIDENCE_KIND = {"PROOF_OF_FULFILLMENT": "proof of shipment or delivery", "PROOF_OF_REFUND": "proof of refund",
                 "PROOF_OF_RETURN": "proof of return"}


def conversation(d: dict, signed: dict | None = None) -> str:
    """Everything said and sent on this case, in order: a seller must see whether they already answered.
    In a team, `signed` ({"by", "at", "text"}) names who sent the answer from here."""
    items = [(m.get("time_posted") or "", "buyer" if m.get("posted_by") == "BUYER" else "you",
              "Buyer" if m.get("posted_by") == "BUYER" else "You", m.get("content", "")) for m in d.get("messages", [])]
    if signed and signed.get("by"):
        who = f"Sent by {signed['by']}"
        mine = [i for i, it in enumerate(items) if it[1] == "you" and it[3] == signed.get("text")]
        if mine:  # PayPal already shows the message: sign it
            items[mine[-1]] = items[mine[-1]][:2] + (who,) + items[mine[-1]][3:]
        else:     # not in PayPal's record (yet, or a practice/demo case): show what was sent
            items.append((signed.get("at") or "~", "you", who, signed.get("text") or ""))
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


def _send_form(did: str, label: str, draft: str, action: str, button: str, says: str, me: str | None,
               passing: bool, teach: str = "") -> str:
    """An approve form. It carries who it was shown to (`by`), so the POST acts as that person."""
    by = f'<input type="hidden" name="by" value="{e(me)}">' if me else ""
    mark = review_mark(did)
    by += f'<input type="hidden" name="review" value="{e(mark)}">' if mark else ""
    return (f'<form class="send" method="post" action="/d/{e(did)}/approve">'
            f'<label class="reply" for="reply">{label}</label>'
            f'<textarea id="reply" name="message">{e(draft)}</textarea>'
            f'<input type="hidden" name="action" value="{e(action)}">{by}'
            f'<div class="approve"><button>{e(button)}</button><span>{e(says)}</span></div>' + teach + '</form>'
            + (PASS_LOCK if passing else LOCK.replace("Sending to PayPal…", _words(did)["sending"])))


def _size_only(dec: Decision) -> bool:
    """The AI's own answer was held back for its size alone, and a person may take it."""
    j = dec.judgment
    return (dec.action == "ASK_SELLER" and held_for_size_only(dec.stops)
            and may_approve(dec.action, j.action, j.action, dec.stops))


def _pass_says(chosen: str, dec: Decision, d: dict, name: str, t: dict | None = None, me: str | None = None) -> str:
    """Why this person passes the case on: the money over their limit (both numbers), or the shop's always-ask line."""
    sends = money_out(chosen, dec.judgment, d)
    if sends >= required(chosen, dec, d):
        cap = team_mod.limit(t, me) if t is not None and me else None
        if cap is not None:
            cur = d["dispute_amount"].get("currency_code", "EUR")
            return (f"{ACTION.get(chosen, chosen)} of {sends:.2f} {cur} is over your {cap:.2f} {cur} limit. "
                    f"{name} decides; nothing is sent now.")
        return f"Over your limit. {name} decides; nothing is sent now."
    return f"Cases over your shop's always-ask line are decided by {name}."


def _held_offer(dec: Decision, d: dict, t: dict, me: str | None) -> dict | None:
    """An answer the limits held back only for its size: the person who may send it gets the button,
    anyone else passes it on. None when it was held back for trust (the page then says: decide in PayPal)."""
    j = dec.judgment
    if not _size_only(dec):
        return None
    kind, to = outcome(dec, j.action, d, t, team_mod.person(t, me))
    if kind == "refused":
        return None
    amount = money_out(j.action, j, d)
    cur = d["dispute_amount"].get("currency_code", "EUR")
    if kind == "pass":
        button, says = f"Pass to {to['name']}", _pass_says(j.action, dec, d, to["name"], t, me)
    else:
        button = f"Approve: {ACTION.get(j.action, j.action).lower()}" + (f" ({amount:.2f} {cur})" if amount else "")
        says = "Your limits held this back for its size only. You decide: this sends it."
    return {"outcome": kind, "action": j.action, "amount": amount, "to": to["name"] if kind == "pass" else None,
            "says": says, "button": button, "label": _words(d.get("dispute_id"))["reply"], "draft": j.draft_message,
            "_via": "form", "_teach": False}


def held_action(did: str, dec: Decision, d: dict, t: dict, me: str | None) -> str:
    o = _held_offer(dec, d, t, me)
    if not o:
        return ""
    return _send_form(did, o["label"], o["draft"], o["action"], o["button"], o["says"], me, o["outcome"] == "pass")


def page_offer(did: str, me: str | None, case: dict | None = None) -> dict:
    """What the case page offers this person, as data: the one decision behind the page's buttons AND the
    API's `for_person`, so a connected system shows exactly what the page would.
    outcome: not_reviewed · out_of_date · sent · nothing_to_send · waiting (`to` = who has the case) ·
    send · pass (`to` = the colleague who decides) · refused. `action` is what the button sends, `amount` the
    money it moves, `says` the page's own sentence, `draft` the reply the page puts in the box."""
    case = case if case is not None else _case(did)
    d = case["dispute"]
    w = _words(did)
    saved = _saved(did)
    t = team_for(did)
    a = None if t.get("solo") else assignments_for(did).get(did)
    hand = a.get("handoff") if a else None
    hand = hand if isinstance(hand, dict) and not (saved and saved[1]) else None
    given = [ev for ev in d.get("evidences", []) if ev.get("source") == "SUBMITTED_BY_SELLER"]
    # You answered and PayPal holds your evidence: there is nothing to send until the buyer moves.
    nothing_to_do = d.get("status") == "WAITING_FOR_BUYER_RESPONSE" and bool(given)

    def offer(kind: str, says: str, via: str, **kw) -> dict:
        return {"outcome": kind, "action": None, "amount": None, "to": None, "says": says, "draft": None,
                "_via": via, **kw}
    if not saved:
        if nothing_to_do:
            return offer("nothing_to_send", "You've answered. Nothing to do now. Your evidence is with PayPal and PayPal "
                         "is waiting for the buyer. If they reply or escalate, this case comes back to you.", "none")
        return offer("not_reviewed", "Not reviewed yet. Take a second look before anyone answers.", "none")
    dec, sent = saved
    j = dec.judgment
    who = team_mod.person(t, me)
    offered = j.action if dec.overridden and _size_only(dec) else "MESSAGE" if dec.action == "ASK_SELLER" else dec.action
    draft = j.draft_message
    if hand and me == a["to"] and hand.get("action") == offered and hand.get("message") is not None:
        draft = hand["message"]  # the colleague's edited reply is what this person sends
    changes = _changes(did, case)
    if changes:
        return offer("out_of_date", f"This answer is out of date: {'; '.join(changes)}.", "stale", reasons=changes)
    if sent:
        return offer("sent", sent, "sent")
    if nothing_to_do:
        return offer("nothing_to_send", "Kept for reference: nothing to send while PayPal waits for the buyer. "
                     "If they write again, Second Look marks this answer out of date.", "kept")
    if hand and me != a["to"]:
        # While a handoff waits, only the person it waits for gets a form: the page must not invite two
        # people to approve the same case at once.
        holder = team_mod.person(t, a["to"])
        name = holder["name"] if holder else a["to"]
        return offer("waiting", f"Waiting for {name}: they decide this one. Nothing to send from here.", "waiting", to=name)

    def form(kind, to, action, says, button, label, teach):
        return offer(kind, says, "form", action=action, amount=money_out(action, j, d),
                     to=to["name"] if kind == "pass" else None, button=button, label=label, draft=draft, _teach=teach)
    held = _held_offer(dec, d, t, me) if dec.overridden else None
    if held:
        return {**held, "draft": draft}
    if dec.action == "ASK_SELLER" and dec.overridden and j.action in MONEY:
        # The reply was written for the money action your limits stopped: it promises that money.
        # Sending it as "a question" would make the promise without your approval.
        what = w["action"].get(j.action, j.action).lower()
        return offer("refused", f"The drafted reply promises a {what}, which your limits stopped. Decide first. If you "
                     f"refund, do it {w['refund_where']}, then come back: Second Look will see the change and draft a reply "
                     "that matches.", "promise", draft=draft)
    if dec.action == "ASK_SELLER" and draft:
        # The drafted question, by the same decision approve() takes: never a button it would refuse.
        kind, to = outcome(dec, "MESSAGE", d, t, who)
        if kind == "refused":
            return offer("refused", to, "draft_refused", draft=draft)
        if kind == "pass":
            return form("pass", to, "MESSAGE", _pass_says("MESSAGE", dec, d, to["name"], t, me),
                        f"Pass to {to['name']}", w["ask"], False)
        return form("send", None, "MESSAGE", "Sends only this message. No money moves.", "Send this question",
                    w["ask"], True)
    if dec.action == "ASK_SELLER":
        return offer("nothing_to_send", "Nothing to send: read the checks and decide.", "no_draft")
    kind, to = outcome(dec, dec.action, d, t, who)
    if kind == "refused":
        return offer("refused", to, "refused")
    if kind == "pass":
        return form("pass", to, dec.action, _pass_says(dec.action, dec, d, to["name"], t, me),
                    f"Pass to {to['name']}", w["reply"], False)
    return form("send", None, dec.action, f"Sends exactly this {w['to']}.",
                f"Approve: {w['action'].get(dec.action, dec.action).lower()}", w["reply"], True)


# No ANTHROPIC_API_KEY: the page says so before the review and on it, and never passes the rules off as the AI.
HOW_TO_KEY = ('To have Claude review it, put an Anthropic API key in <code>.env</code> as ANTHROPIC_API_KEY '
              '(README, "Try it") and start Second Look again.')
# What the rules baseline (judge.rules) reads: nothing else.
RULES_LOOK = "the dispute reason, the tracking status and whether the buyer sent photos"
NO_KEY_RUN = ('<p><b>No AI key is set,</b> so this runs the rules baseline, not Claude: the simple rules the eval '
              f'measures Claude against. It looks only at {RULES_LOOK}, and runs none of the '
              'ten checks. Your limits still apply after it, as they do for Claude. Nothing is sent until you approve. '
              + HOW_TO_KEY + '</p><button>Take a second look (rules baseline)</button>')


# The few words that differ between a PayPal dispute and a shop inquiry, on the same page and the same buttons.
INQUIRY_ACTION = {**ACTION, "REPLACE": "Exchange or replace"}
INQUIRY_SAYS = {
    "REFUND": "The refund is logged for your payment provider and the reply goes to the customer.",
    "PARTIAL_REFUND": "The amount below is logged as a refund and the reply goes to the customer.",
    "REPLACE": "The exchange or replacement is logged for your orders and the reply goes to the customer.",
    "MESSAGE": "Only the reply is sent. No money moves.",
    "ASK_SELLER": "Nothing is sent until you choose. Start with what doesn't add up.",
}
RULES_LOOK_INQUIRY = "the problem the request describes, the courier's status and your shop's return window"


def _words(did: str | None) -> dict:
    if cases_mod.is_case_id(did):
        return {"to": "to the customer", "decide": "Decide yourself, outside Second Look.", "first": "",
                "refund_where": "in your payment provider", "reply": "Your reply to the customer",
                "ask": "Before you decide, ask the customer", "sending": "Sending…", "sent": "Sent.",
                "reading": "Reading the request… about 30 seconds", "action": INQUIRY_ACTION, "says": INQUIRY_SAYS,
                "checks": judge_mod.INQUIRY_CHECKS, "rules_look": RULES_LOOK_INQUIRY,
                "intro": "Second Look's AI reads the request and the evidence, runs the ten checks against your shop's "
                         "own terms (no PayPal rules apply yet), and recommends one answer. Nothing is sent until you approve."}
    return {"to": "to PayPal", "decide": "Decide in PayPal.", "first": ", in PayPal", "refund_where": "in PayPal",
            "reply": "Your reply to the buyer", "ask": "Before you decide, ask the buyer",
            "sending": "Sending to PayPal…", "sent": "Sent to PayPal.", "reading": "Reading the dispute… about 30 seconds",
            "action": ACTION, "says": ACTION_SAYS, "checks": CHECKS, "rules_look": RULES_LOOK,
            "intro": "Second Look reads the dispute and the evidence, runs the ten checks a dispute specialist would run, "
                     "and recommends one answer. Nothing is sent until you approve."}


def _no_key_run(w: dict) -> str:
    if w["rules_look"] == RULES_LOOK:
        return NO_KEY_RUN
    return NO_KEY_RUN.replace(RULES_LOOK, w["rules_look"])


def page_of(did: str) -> str:
    return f"/c/{did}" if cases_mod.is_case_id(did) else f"/d/{did}"


def judged_note(did: str, judged: str | None, sent: bool) -> str:
    """Who wrote the review on screen, when it isn't a review Claude made on this machine."""
    if judged == "rules":
        why = ("This review ran without an Anthropic API key." if has_ai_key()
               else "No AI key is set, so Second Look ran its rules baseline instead of Claude.")
        again = (f'<form method="post" action="/d/{e(did)}/review"><button>Take a second look with Claude</button></form>'
                 if has_ai_key() and not sent else "" if has_ai_key() else f"<span>{HOW_TO_KEY}</span>")
        return (f'<div class="judged"><b>Rules baseline, not the AI.</b>{e(why)} It looks only at {_words(did)["rules_look"]}, '
                f'the way a simple automation would. Your limits were applied after it, as '
                f'they are for Claude. {again}</div>')
    if judged and is_shipped(did):
        return ('<p class="conf">Reviewed by Claude ahead of time: this review ships with the demo shop, so it shows '
                'without an AI key. It goes out of date like any other if the case changes.</p>')
    return ""


def case_refund_note(r: dict) -> str:
    """On a PayPal dispute's page: a refund the shop already logged on this order's case, before PayPal had it."""
    if not r.get("refund_logged_on_case"):
        return ""
    said, _, cid = r["already_refunded"].rpartition(", on case ")
    amount, _, rest = said.partition(" on ")
    return (f'<p class="check-sender">A refund of {e(amount)} was already logged on case '
            f'<a href="/c/{e(cid)}">{e(cid)}</a>{" on " + e(rest) if rest else ""}. '
            'Check it before you answer PayPal: paying twice, or defending a refund you promised, is never right.</p>')


def part_of_case(did: str) -> str:
    """On a dispute's page: the case it belongs to when another channel joined it (Pablo's email + DEMO-034)."""
    c = None if did.startswith("PP-D-") else find_case_of_dispute(did)
    if not c:
        return ""
    came = " + ".join(cases_mod.CHANNEL_LABEL[ch] for ch in cases_mod.channels(c, {"dispute_id": did, "messages": []}))
    return f'<p class="owner-line">One case, every channel: <a href="/c/{e(c["id"])}">{e(c["id"])}</a> ({e(came)}).</p>'


def case_page(dispute_id: str, flash: str = "", me: str | None = None) -> str:
    case = _case(dispute_id)
    d, r = case["dispute"], case["seller_records"]
    msg = next((m["content"] for m in d.get("messages", []) if m.get("posted_by") == "BUYER"), "")
    amt = d["dispute_amount"]
    demo = is_demo(dispute_id)
    practice = not demo and isinstance(_client(dispute_id), MockPayPal)
    today = DemoPayPal().today if demo else datetime.utcnow().date()
    q = "?shop=demo" if demo else ""
    buyer = ledger.buyer_of(d)
    saved = _saved(dispute_id)
    t = team_for(dispute_id)
    a = None if t.get("solo") else assignments_for(dispute_id).get(dispute_id)
    signed = None
    if a is not None and saved and saved[1]:
        sb = _saved_by(dispute_id)
        signed = {"by": sb.get("by"), "at": sb.get("at"), "text": saved[0].judgment.draft_message or saved[1]}
    card = (f'<p class="cardlink"><a href="/customer/{e(buyer)}{q}">This customer\'s record with you</a></p>'
            if buyer and not practice else "")
    nobody = "" if practice or d.get("status") == "RESOLVED" else f'<p class="nobody">{e(ledger.if_nobody_answers(d, today))}</p>'
    left = (f'<a class="back" href="/{"?practice=1" if practice else q}">All disputes</a>'
            f'{pill_for(d)}{part_of_case(dispute_id)}{case_refund_note(r)}<p class="claim quote">{e(msg)}</p>'
            f'<p class="who">{e(REASON.get(d["reason"], d["reason"]))}. {e(amt["value"])} {e(amt["currency_code"])}'
            f'{", ".join([""] + [i["name"] for i in r.get("items", [])])}</p>{nobody}'
            f'{conversation(d, signed)}{timeline(case)}<h2>What the evidence says</h2>{evidence(r)}{card}')
    body = (f'<div class="case"><section>{left}</section>'
            f'<section class="look">{review_column(dispute_id, case, me, flash)}</section></div>')
    return page(f"{msg[:40]} | Second Look", "Practice case" if practice else "PayPal sandbox", body, demo, me=me)


def review_column(did: str, case: dict, me: str | None, flash: str = "", plain_owner: bool = True) -> str:
    """The right-hand side of a case: whose it is, the review, the one button the limits allow, the costs and
    the ten checks. The same for a PayPal dispute (/d/) and a shop inquiry (/c/): only a few words differ.
    plain_owner=False: the page already says whose case it is (the case page's header, with the role)."""
    w = _words(did)
    d, r = case["dispute"], case["seller_records"]
    amt = d["dispute_amount"]
    saved = _saved(did)
    # In a team: whose case it is, and a colleague's handoff waiting on it (until the answer is sent).
    t = team_for(did)
    a = None if t.get("solo") else assignments_for(did).get(did)
    hand = a.get("handoff") if a else None
    hand = hand if isinstance(hand, dict) and not (saved and saved[1]) else None
    owner = ""
    if a is not None:
        holder = team_mod.person(t, a["to"])
        holder_name = holder["name"] if holder else a["to"]
        if hand:
            what = w["action"].get(hand.get("action"), str(hand.get("action"))).lower()
            try:
                much = f' ({float(hand.get("amount")):.2f} {amt.get("currency_code", "EUR")})'
            except (TypeError, ValueError):
                much = ""
            frm = hand.get("from_name") or "A colleague"
            owner = (f'<div class="guard"><b>{e(frm)} suggests: {e(what)}{e(much)}.</b> Over {e(frm)}\'s limit, '
                     f'so it waits for {e(holder_name)}. Nothing has been sent.</div>')
        elif a["to"]:
            owner = f'<p class="owner-line">{e(holder_name)}\'s case.</p>' if plain_owner else ""
        else:
            by = f'<input type="hidden" name="by" value="{e(me)}">' if me else ""
            owner = (f'<form class="owner-line" method="post" action="/d/{e(did)}/take">'
                     f'{"Nobody has this case yet. " if plain_owner else ""}{by}<button class="link">Take it</button></form>')
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
    busy = ('<script>document.querySelectorAll(".run").forEach(f=>f.addEventListener("submit",e=>{const b=e.target.'
            'querySelector("button");b.disabled=true;b.textContent="' + w["reading"] + '";}));</script>')
    if nothing_to_do and not saved:
        return owner + banner + costs
    if not saved:
        intro = (f'<p>{w["intro"]}</p><button>Take a second look</button>') if has_ai_key() else _no_key_run(w)
        return (owner + banner + costs + f'<form class="run" method="post" action="/d/{e(did)}/review">'
                f'<h2>Ten checks before you answer</h2>{intro}</form>{busy}')
    dec, sent = saved
    j = dec.judgment
    o = page_offer(did, me, case)  # the same decision the API gives other systems
    via = o["_via"]
    guard = ""
    if dec.reasons:
        guard = (f'<div class="guard"><b>Your limits changed the answer'
                 f'{" from " + e(w["action"].get(j.action, j.action)) if dec.overridden else ""}:</b>'
                 f'<ul>{"".join(f"<li>{e(plain(n))}</li>" for n in dec.reasons)}</ul></div>')
    amount = f' ({e(j.partial_amount)})' if dec.action == "PARTIAL_REFUND" and j.partial_amount else ""
    lead, rest = first_sentences(j.reasoning)
    judged = judge_of(did)
    conf = (f"Confidence {j.confidence:.0%}." if judged != "rules"
            else f"A fixed rule, not a measured confidence ({j.confidence:.0%}).")
    verdict = (judged_note(did, judged, bool(sent))
               + f'<section class="verdict"><h3>{e(w["action"].get(dec.action, dec.action))}{amount}</h3>'
               f'<p class="conf">{e(conf)} {e(w["says"].get(dec.action, ""))}</p>'
               f'<p>{e(lead)}</p>'
               + (f'<details><summary>Full reasoning</summary><p>{e(rest)}</p></details>' if rest else "")
               + f'{guard}</section>')
    done = f'<div class="sent"><b>{e(w["sent"])}</b><br>{e(sent)}</div>' if sent else ""
    if via == "stale":
        action_part = done + (f'<form class="run" method="post" action="/d/{e(did)}/review"><div class="stale">'
                              f'<b>This answer is out of date:</b> {e("; ".join(o["reasons"]))}.</div>'
                              f'<button>Take a fresh look{"" if has_ai_key() else " (rules baseline: no AI key is set)"}</button></form>'
                              + busy)
    elif via == "sent":
        action_part = done
    elif via in ("kept", "waiting", "no_draft", "refused"):
        action_part = f'<p class="conf">{e(o["says"])}</p>'
    elif via == "form":
        action_part = _send_form(did, o["label"], o["draft"], o["action"], o["button"], o["says"], me,
                                 o["outcome"] == "pass", TEACH if o["_teach"] and o["outcome"] != "pass" else "")
    elif via == "promise":
        action_part = (f'<div class="stale"><b>The drafted reply promises a {e(w["action"].get(j.action, j.action).lower())}, '
                       f'which your limits stopped.</b> Decide first. If you refund, do it {w["refund_where"]}, then come back: '
                       'Second Look will see the change and draft a reply that matches.</div>'
                       f'<details class="draft"><summary>Read the draft anyway</summary><p>{e(o["draft"])}</p></details>')
    elif via == "draft_refused":
        action_part = (f'<div class="stale"><b>{e(o["says"])}</b></div>'
                       f'<details class="draft"><summary>Read the draft anyway</summary><p>{e(o["draft"])}</p></details>')
    else:
        action_part = ""
    ten = checks(j, w["checks"]) or (f'<p class="na-line">The rules baseline runs none of the ten checks: it looks only at '
                                     f'{w["rules_look"]}. Claude runs them.</p>' if judged == "rules" else "")
    return f'{owner}{banner}{flash}{verdict}{action_part}{costs}<h2 style="margin-top:34px">The ten checks</h2>{ten}'


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
    saved = _saved(did)
    if saved and saved[1] and not _changes(did, _case(did)):
        return saved[0]  # answered, and nothing new since: keep the record (and don't pay for a review)
    # No key: the rules baseline instead of an error page. Saved as "rules", and labelled so on every screen.
    judge = "claude" if has_ai_key() else "rules"
    if cases_mod.is_case_id(did):
        dec = review_inquiry(did, judge)
    elif _money_case_for(did, lambda: _client(did).get_dispute(did)):
        dec = review_with_case_refund(did, judge)
    else:
        dec = review(_client(did), did, judge)       # every other dispute: exactly as before
    with _case_lock(did):  # never between an approval's read and its save
        case, saved = _case(did), _saved(did)
        if saved and saved[1] and not _changes(did, case):
            return saved[0]  # sent while the judge was reading: the sent record stays
        _save(did, dec, seen=_seen(case), judge=judge)
        t = team_for(did)
        if not t.get("solo") and assignments_for(did).get(did)["handoff"]:
            # A colleague's note was about the old review: the case stays theirs, the note goes.
            assignments_for(did).update(did, lambda a: {**a, "handoff": None})
    notify("review.ready", {**_about(did), "recommended": dec.action, "confidence": dec.judgment.confidence,
                            "limits_changed_it": dec.overridden, "judge": judge})
    return dec


# Why the guard held an answer back, in the words the person reads when they try to send it anyway.
STOP_SAYS = {
    "injection": "hidden instructions in the buyer's message",
    "inconsistent": "evidence that doesn't add up",
    "confidence": "low confidence",
    "repeat_buyer": "a buyer who disputes far more than usual",
    "paypal_allowed": "PayPal doesn't allow it at this stage",
    "message_not_allowed": "PayPal doesn't take a message at this stage",
    "unknown_action": "an answer Second Look doesn't recognise",
    "partial_amount": "an amount it couldn't read",
    "no_order": "there is no order with an amount on this case",
    "already_refunded": "the order is already refunded in full",
    "refund_logged_on_case": "a refund already logged on this order's case",
}


def _refused(dec: Decision | None, chosen: str, w: dict | None = None) -> str:
    """Why may_approve refused. The guard's reasons only where they are the reason: for the AI's own answer,
    or for the drafted question on "your call" (PayPal's rules, an unrecognised answer, a promised refund)."""
    w = w or _words(None)
    if dec and dec.action == "ASK_SELLER" and chosen == "MESSAGE":
        why = [STOP_SAYS[s] for s in ("message_not_allowed", "unknown_action", "refund_logged_on_case") if s in dec.stops]
        if why:
            return (f"This message was held back: {', '.join(why)}. "
                    f"It can't be sent from here, by anyone. {w['decide']}")
        if dec.judgment.action in MONEY:
            return (f"The drafted reply promises a {ACTION.get(dec.judgment.action, dec.judgment.action).lower()}, "
                    f"which your limits stopped. Decide first{w['first']}.")
    held = [STOP_SAYS.get(s, s) for s in (dec.stops if dec else []) if s not in SIZE_STOPS | QUESTION_STOPS]
    if dec and chosen == dec.judgment.action and held:
        return (f"This answer was held back: {', '.join(held)}. "
                f"It can't be sent from here, by anyone. {w['decide']}")
    return "This answer changed since you saw it, or it can't be sent as it is. Look again."


def outcome(dec: Decision, chosen: str, dispute: dict, t: dict, who: dict | None) -> tuple:
    """What approving `chosen` does for this person. The one decision behind approve() AND every button on the
    case page, so a button never promises what approve won't do.
    ("refused", why) · ("pass", colleague) over their limit · ("send", None)."""
    w = _words(dispute.get("dispute_id"))
    if not may_approve(dec.action, chosen, dec.judgment.action, dec.stops):
        return "refused", _refused(dec, chosen, w)
    need = required(chosen, dec, dispute)
    me = who["id"] if who else None
    if need and not team_mod.covers(t, me, need):
        to = team_mod.handoff_to(t, need, exclude=me)
        if not to:
            cur = dispute["dispute_amount"].get("currency_code", "EUR")
            return "refused", f"Nobody in the team may approve {need:.2f} {cur} from here. {w['decide']}"
        return "pass", to
    return "send", None


def required(chosen: str, dec: Decision, dispute: dict) -> float:
    """How much this approval asks the person to cover: the money the chosen answer sends, or, on a case the
    limits held back for being big ("always_ask"), the whole dispute, whatever the answer. A big case is the
    manager's even to defend it or ask a question: the shop asked for a person with that authority."""
    whole = float(dispute["dispute_amount"]["value"]) if "always_ask" in dec.stops else 0.0
    return max(money_out(chosen, dec.judgment, dispute), whole)


# Actions whose text reaches the buyer or PayPal: an emptied box must not fall back to the AI's draft or reasoning.
_WORDS_NEEDED = ("MESSAGE", "REFUND", "PARTIAL_REFUND", "REPLACE")


def approve(did: str, chosen: str, message: str | None, rule: str = "", by: str | None = None,
            review: str | None = None) -> tuple[int, str]:
    """Send the answer a person chose. Returns (HTTP status, what happened).
    200 sent · 202 passed to a colleague (nothing sent) · 400 nobody named or no words · 409 changed or not allowed.
    `review`: the review_mark of the review they were shown; when given, a different review is refused."""
    from .__main__ import execute
    t = team_for(did)
    who = team_mod.person(t, by)
    if not who:
        return 400, "Say who is approving: a person in this shop's team."
    with _case_lock(did):  # from reading the review to saving what was sent, or the handoff
        return _approve(did, chosen, message, rule, t, who, execute, review)


def _approve(did, chosen, message, rule, t, who, execute, review=None) -> tuple[int, str]:
    saved = _saved(did)
    if cases_mod.is_case_id(did) and not (saved and saved[1]):
        no = _inquiry_refusal(did)      # unsorted, or PayPal has it now: never answered as an inquiry
        if no:
            return 409, no
    if saved and saved[1]:
        return 200, saved[1]  # already sent: a second approval sends nothing
    if not saved:
        return 409, _refused(None, chosen)
    if review and review != review_mark(did):
        return 409, "This answer changed since you saw it. Look again."
    if chosen in _WORDS_NEEDED and message is not None and not message.strip():
        return 400, "Write a message first."
    dec = saved[0]
    case = _case(did)
    if _changes(did, case):
        return 409, "Something changed since this review. Take a fresh look."
    kind, to = outcome(dec, chosen, case["dispute"], t, who)
    if kind == "refused":
        return 409, to
    cur = case["dispute"]["dispute_amount"].get("currency_code", "EUR")
    amount = money_out(chosen, dec.judgment, case["dispute"])
    need = required(chosen, dec, case["dispute"])
    now = datetime.now()
    if kind == "pass":
        # Over this person's limit: nothing goes to PayPal. The case passes to a colleague who may send it.
        handoff = {"from": who["id"], "from_name": who["name"], "action": chosen, "amount": need,
                   "message": message, "at": now.isoformat(timespec="minutes")}
        assignments_for(did).update(did, lambda a: {"to": to["id"], "handoff": handoff})
        notify("case.handed_off", {**_about(did), "action": chosen, "amount": need,
                                   "from": who["name"], "to": to["name"]})
        cap = team_mod.limit(t, who["id"]) or 0.0
        what = (f"{ACTION.get(chosen, chosen).lower()} of {amount:.2f} {cur}" if amount >= need
                else f"{ACTION.get(chosen, chosen).lower()} on a {need:.2f} {cur} dispute")
        return 202, f"Passed to {to['name']}: {what} is over your {cap:.2f} {cur} limit. Nothing was sent."
    if message is None and not t.get("solo"):
        # No message given (the API): the colleague who passed this case on edited the reply; send theirs.
        hand = assignments_for(did).get(did)["handoff"]
        if isinstance(hand, dict) and hand.get("action") == chosen and hand.get("message") is not None:
            message = hand["message"]
    recommended = dec.action
    dec.action = chosen  # "your call": a question, or the answer held back only for its size
    if message is not None:
        dec.judgment.draft_message = message
    raw = _raw(did) or {}  # the case's own review, or the shipped demo one it starts from
    seen, judged = raw.get("seen"), raw.get("judge")
    inquiry = cases_mod.is_case_id(did)
    client = (Outbox(did, by=who["name"], ai=judged == "claude", amount=float(case["dispute"]["dispute_amount"]["value"]))
              if inquiry else _client(did))
    result = execute(client, dec, case["dispute"], case["seller_records"])
    how = OUT_WORDS.get(result.get("channel"), "by email") if inquiry else ""
    sent = {"MESSAGE": ("Question" if recommended == "ASK_SELLER" else "Reply") + f" sent {how}.",
            "REFUND": f"Refund of {amount:.2f} {cur} logged and reply sent {how}.",
            "PARTIAL_REFUND": f"Partial refund of {amount:.2f} {cur} logged and reply sent {how}.",
            "REPLACE": f"Exchange or replacement logged and reply sent {how}."}.get(dec.action, "Done.") if inquiry else {"DEFEND": "Evidence submitted and reply sent." if not str(result.get("message", "")).startswith("not sent")
            else "Evidence submitted. Reply not sent: PayPal is waiting for the buyer to answer your last message.",
            "MESSAGE": "Question sent." if recommended == "ASK_SELLER" else "Reply sent.",
            "REFUND": "Refund accepted and reply sent.", "PARTIAL_REFUND": "Partial refund offered.",
            "REPLACE": "Replacement offered."}.get(dec.action, "Done.")
    if not t.get("solo"):
        sent += f" Sent by {who['name']}, {now:%H:%M}."
    if inquiry:
        sent += (" (Demo shop: logged; no email or money sent.)" if is_demo(did) else
                 " (Logged in Second Look: your helpdesk sends the email; money is not moved from here yet.)")
    elif is_demo(did):
        sent += " (Demo shop: logged, not sent to PayPal.)"
    elif isinstance(_client(did), MockPayPal):
        sent += " (Practice case: logged, not sent to PayPal.)"
    if suggest_rule(rule or "", did):
        sent += " Your rule suggestion waits on Your rules for review."
    dec.action = recommended  # the page keeps showing what was recommended
    by_name = None if t.get("solo") else who["name"]
    if inquiry and seen and chosen in ("REFUND", "PARTIAL_REFUND"):   # what was sent (dec.action is the recommendation again)
        # What this approval itself logged (a refund lowers what is left) is part of what the review saw; only
        # something new (the customer writing again) makes it out of date. Only this send's own change is added:
        # a message that lands while it is sent was never seen (re-reading the case here would count it).
        seen = {**seen, "amount": f"{max(0.0, float(seen['amount']) - amount):.2f}"}
    _save(did, dec, sent, seen, by=by_name, at=now.isoformat(timespec="minutes"), judge=judged)
    if not t.get("solo"):
        # Sent by them: the case is theirs, and any handoff waiting on it is done.
        assignments_for(did).update(did, lambda a: {"to": who["id"], "handoff": None})
    notify("answer.sent", {**_about(did), "action": chosen, "what_happened": sent, "by": by_name})
    return 200, sent


def api_case(did: str, as_person: str | None = None) -> dict:
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
                         "limits_notes": dec.reasons, "held_back_for": dec.stops, "reasoning": dec.judgment.reasoning,
                         "draft_reply": dec.judgment.draft_message,
                         # each check with the page's group (what it means for the answer) and its plain label
                         "checks": [{**c, "group": _bucket(c), "label": _words(did)["checks"].get(c.get("id"), c.get("id"))}
                                    for c in dec.judgment.checks if isinstance(c, dict) and "id" in c and "result" in c],
                         "sent": sent, "by": _saved_by(did).get("by"), "out_of_date": _changes(did, case),
                         "mark": review_mark(did),
                         # "claude", or "rules": the baseline that runs when no ANTHROPIC_API_KEY is set
                         "judge": judge_of(did), "shipped_with_demo": is_shipped(did)}
    if not team_for(did).get("solo"):
        a = assignments_for(did).get(did)
        out["assigned_to"], out["handoff"] = a["to"], a["handoff"]
    if as_person is not None:
        # What the case page offers this person: the same page_offer() behind its buttons.
        t = team_for(did)
        who = team_mod.person(t, as_person)
        if not who:
            out["for_person"] = {"outcome": "unknown_person"}
        else:
            o = page_offer(did, None if t.get("solo") else who["id"], case)
            out["for_person"] = {"person": who["name"], **{k: v for k, v in o.items() if not k.startswith("_")},
                                 "why": o["says"] if o["outcome"] == "refused" else None}
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
    # One shop, one team, one read of who has which case: not once per row.
    solo = team_for_src(src).get("solo")
    assigned = {} if solo else assignments_for("DEMO-" if src == "demo" else None).all()
    out = []
    for d in items:
        saved = _saved(d["dispute_id"])
        row = {"dispute_id": d["dispute_id"], "reason": d.get("reason"), "status": d.get("status"),
               "amount": d.get("dispute_amount"), "buyer": ledger.buyer_of(d),
               "recommended": saved[0].action if saved else None, "sent": saved[1] if saved else None}
        if not solo:
            row["assigned_to"] = assigned.get(d["dispute_id"], {}).get("to")
        out.append(row)
    return out


# ---------- server ----------

def api_body(raw: bytes, approving: bool) -> tuple:
    """A review or an approval through the API: (one JSON object, None), or (None, the 400's message).
    An empty body is {}; anything else must be one object, its fields text (never a crash, never a 500)."""
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return None, ('Send one JSON object: {"action": ..., "by": "<person id>", "message": ..., "review": ...}.'
                      if approving else "Send one JSON object, or nothing.")
    if approving:
        for k in ("action", "by", "message", "rule", "review"):
            if data.get(k) is not None and not isinstance(data[k], str):
                return None, f"{k} must be text, in one JSON object."
    return data, None


# The most a POST may carry: a form, or one request of at most 10,000 characters, is a few kilobytes.
MAX_BODY = 1_000_000


class Handler(BaseHTTPRequestHandler):
    timeout = 30            # a client that stops sending in the middle of a request frees its thread
    _cookie = None
    _person = None
    _film = False
    _raw = b""

    def _jar(self) -> dict:
        return dict(c.strip().split("=", 1) for c in (self.headers.get("Cookie") or "").split(";") if "=" in c)

    def _who(self, qs: dict, src: str) -> str | None:
        """Who is acting: ?as=<id> switches and is remembered (cookie sl_person_<shop>); else the
        remembered one; else the first person in the team. Nobody in a team of one."""
        t = team_for_src(src)
        if t.get("solo"):
            return None
        asked = (qs.get("as") or [""])[0]
        key = f"sl_person_{src}"
        if team_mod.person(t, asked):
            self._person = f"{key}={asked}; Path=/; SameSite=Lax"
            return asked
        kept = self._jar().get(key)
        if team_mod.person(t, kept):
            return kept
        first = team_mod.first(t)  # for display only: a POST must name its person itself (by_for_post)
        return first["id"] if first else None

    def _send(self, body: str, code: int = 200):
        if self._film:
            body = body.replace("</style>", "*{animation:none!important;transition:none!important}</style>", 1)
        b = body.encode()
        self.send_response(code)
        if self._cookie:
            self.send_header("Set-Cookie", self._cookie)
        if self._person:
            self.send_header("Set-Cookie", self._person)
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
            _REQUEST.qs = qs
            # The shop you're in stays the same from page to page: an Overview of one shop next to the
            # disputes of another made no sense (Claudia, 21/10). Demo by default: it has a history.
            asked = (qs.get("shop") or [""])[0]
            if asked in ("demo", "live"):
                self._cookie = f"sl_shop={asked}; Path=/; SameSite=Lax"
            jar = self._jar()
            shop = asked if asked in ("demo", "live") else jar.get("sl_shop", "demo")
            src = "practice" if "practice" in qs else shop
            if u.path.startswith(("/d/", "/c/")):
                src = src_of_case(u.path[3:].strip("/"), src)  # a case's people are its own shop's
            me = self._who(qs, src)
            self._film = "film" in qs  # the demo film loads pages live: no fade-ins half-way through a frame
            if u.path == "/":
                return self._send(inbox_page(src, me, (qs.get("view") or [""])[0]))
            if u.path == "/overview":
                return self._send(overview_page(src, me=me))
            if u.path.startswith("/customer/"):
                return self._send(customer_page(u.path[len("/customer/"):].strip("/"), src, me=me))
            if u.path.rstrip("/") == "/api/disputes":
                return self._json(api_open(src))
            if u.path.startswith("/api/disputes/"):
                return self._json(api_case(unquote(u.path[len("/api/disputes/"):].strip("/")),
                                           as_person=(qs.get("as") or [None])[0]))
            if u.path.startswith("/api/cases/"):
                cv = api_case_of(unquote(u.path[len("/api/cases/"):].strip("/")), as_person=(qs.get("as") or [None])[0])
                return self._json(cv if cv else {"error": "unknown case"}, 200 if cv else 404)
            if u.path.startswith("/c/"):
                return self._send(case_file_page(u.path[3:].strip("/"), me=me))
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
                return self._send(rules_page(demo=shop == "demo", me=me))
            if u.path.startswith("/d/"):
                did = u.path[3:].strip("/")
                if cases_mod.is_case_id(did):
                    return self._redirect(f"/c/{did}")    # a shop inquiry has its case page
                return self._send(case_page(did, me=me))
            self._send("Not found", 404)
        except Exception as err:  # show the reason on the page, never a blank screen
            self._fail(err)
        finally:
            _REQUEST.qs = {}

    def _case_api(self, cid: str, what: str, raw: bytes):
        """POST /api/cases/<id>/review and /approve: the case's decision (its PayPal dispute, else the inquiry
        itself) through the same run_review() and approve() as the page."""
        c = case_store(shop_of_case(cid)).get(cid) if cases_mod.is_case_id(cid) else None
        if c is None:
            return self._json({"error": "unknown case"}, 404)
        decision = c.get("dispute_id") or cid
        data, bad = api_body(raw, approving=what == "approve")
        if bad:
            return self._json({"case_id": cid, "error": bad}, 400)
        if what == "review":
            try:
                run_review(decision)
            except ValueError as err:
                return self._json({"case_id": cid, "error": str(err)}, 409)
            return self._json(api_case_of(cid))
        code, text = approve(decision, data.get("action", ""), data.get("message"), data.get("rule", ""),
                             by=data.get("by"), review=data.get("review"))
        return self._json({"case_id": cid, "decision_id": decision, "result": text}, code)

    def _same_site(self) -> bool:
        """A browser page elsewhere must not post into Second Look: when a request says where it comes from
        (Origin, else Referer), it must be this server. Systems posting from their own server (Ticketbook,
        curl) send neither, and still work. The same check as Ticketbook's own forms (helpdesk/app.py)."""
        port = self.server.server_address[1]
        here = (f"127.0.0.1:{port}", f"localhost:{port}")
        for name in ("Origin", "Referer"):
            v = self.headers.get(name)
            if v and urlparse(v).netloc not in here:
                return False
        return True

    def _request(self):
        """POST /api/requests: one email or web form from another system (a helpdesk), filed on its case."""
        if not self._same_site():
            return self._json({"error": "Requests come from your own systems, not from a web page elsewhere."}, 403)
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return self._json({"error": "Send JSON (Content-Type: application/json)."}, 415)
        try:
            data = json.loads(self._raw or b"null")
        except ValueError:
            return self._json({"error": "Not JSON."}, 400)
        q = parse_qs(urlparse(self.path).query)
        shop = (q.get("shop") or [""])[0] or self._jar().get("sl_shop", "demo")
        code, out = receive("live" if shop == "live" else "demo", data)
        return self._json(out, code)

    def do_POST(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        length = self.headers.get("Content-Length", "0").strip()
        if not length.isdigit():                 # "abc", "-5", "": no way to know where the body ends
            self.close_connection = True
            return self._send("Content-Length must be a number of bytes.", 400)
        # Every post changes something: from a browser, only from Second Look's own pages (see _same_site).
        # Checked before the body is read, so a page elsewhere can't make the server read anything.
        if not self._same_site():
            self.close_connection = True
            return self._request() if parts == ["api", "requests"] else self._send(
                "This can only be sent from Second Look's own pages.", 403)
        if int(length) > MAX_BODY:
            self.close_connection = True
            return self._send(f"At most {MAX_BODY // 1_000_000} MB in one request.", 413)
        raw = self.rfile.read(int(length))
        self._raw = raw
        # keep_blank_values: an emptied reply box arrives empty, never as "use the AI's draft"
        form = parse_qs(raw.decode(), keep_blank_values=True) if not self.path.startswith("/api/") else {}
        try:
            me = None
            if parts == ["api", "requests"]:
                return self._request()
            if len(parts) == 3 and parts[0] == "c" and parts[2] == "order":
                ok, me = by_for_post(team_for(parts[1]), form.get("by", [""])[0])
                if not ok:
                    return self._send("Choose who you are at the top of the page.", 400)
                code, out = pick_order(parts[1], form.get("order", [""])[0], me)
                # the answer repeats what was typed: as text, never as page code
                return self._redirect(f"/c/{out}") if code == 200 else self._send(e(out), code)
            if len(parts) == 3 and parts[0] == "d" and parts[2] in ("approve", "take"):
                # The form says who it was shown to; it must be a real person of the case's own team.
                ok, me = by_for_post(team_for(parts[1]), form.get("by", [""])[0])
                if not ok:
                    return self._send("Choose who you are at the top of the page.", 400)
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
                try:
                    run_review(parts[1])
                except ValueError as err:          # an unsorted request: a person picks its order first
                    return self._send(str(err), 409)
                return self._redirect(page_of(parts[1]))
            if len(parts) == 3 and parts[0] == "d" and parts[2] == "approve":
                code, text = approve(parts[1], form.get("action", [""])[0], form.get("message", [None])[0],
                                     form.get("rule", [""])[0], by=me, review=form.get("review", [None])[0])
                return self._redirect(page_of(parts[1])) if code in (200, 202) else self._send(text, code)
            if len(parts) == 3 and parts[0] == "d" and parts[2] == "take":
                code, text = take(parts[1], me)
                return self._redirect(page_of(parts[1])) if code == 200 else self._send(text, code)
            if len(parts) == 3 and parts[0] == "c" and parts[2] == "close":
                ok, me = by_for_post(team_for(parts[1]), form.get("by", [""])[0])
                if not ok:
                    return self._send("Choose who you are at the top of the page.", 400)
                code, text = close_case(parts[1], form.get("outcome", [""])[0], me)
                return self._redirect(f"/c/{parts[1]}") if code == 200 else self._send(text, code)
            if len(parts) == 4 and parts[:2] == ["api", "cases"] and parts[3] in ("review", "approve"):
                return self._case_api(parts[2], parts[3], raw)
            # the API: the same review and the same approval, as JSON
            if len(parts) == 4 and parts[:2] == ["api", "disputes"] and parts[3] in ("review", "approve"):
                did = parts[2]
                data, bad = api_body(raw, approving=parts[3] == "approve")
                if bad:
                    return self._json({"dispute_id": did, "error": bad}, 400)
                if parts[3] == "review":
                    run_review(did)
                    return self._json(api_case(did))
                # a connected system must say who approves ("by": a person id) in a team shop
                code, text = approve(did, data.get("action", ""), data.get("message"), data.get("rule", ""),
                                     by=data.get("by"), review=data.get("review"))
                return self._json({"dispute_id": did, "result": text}, code)
            self._send("Not found", 404)
        except Exception as err:
            self._fail(err)

    def log_message(self, *args):  # quiet terminal
        pass


def serve(port: int = 8765) -> None:
    print(f"Second Look: http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
