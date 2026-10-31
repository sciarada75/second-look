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
import sys
import threading
import time
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import timedelta, timezone
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from . import autopilot as autopilot_mod, books as books_mod, calls as calls_mod, cases as cases_mod, evidence as evidence_mod, judge as judge_mod, ledger, moves as moves_mod, sort as sort_mod, state as state_mod, team as team_mod, today as today_mod
from .demo import DemoPayPal, LABEL as DEMO_LABEL, is_demo
from .guard import apply_policy, may_approve, money_out, held_for_size_only, CHECKS, MONEY, QUESTION_STOPS, SIZE_STOPS, Decision, Judgment
from .paypal import MockPayPal, client_from_env

ROOT = Path(__file__).resolve().parent.parent
REVIEWS = ROOT / ".tmp" / "reviews"
# Claude's reviews of the demo shop's open cases, shipped with the repo so a fresh clone with no AI key shows
# them (a judge of the hackathon has no key). Read only, and only for a DEMO-* case with no review of its own
# in REVIEWS: a fresh look or an approval saves there, so a shipped file is never written. A shipped review
# goes out of date exactly as a cached one does: it carries what it saw (`seen`). The demo's open inquiries
# (DEMO-C001...) ship theirs too; its read-only history cases (DEMO-H...) are never reviewed.
SHIPPED = ROOT / "demo" / "reviews"
_DEMO_ID = re.compile(r"DEMO-C?\d+")

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
    "buyer_history": "This buyer", "already_refunded": "Already refunded", "already_replaced": "Already replaced",
    "return": "Return",
    "exchange_counts": "Toward your limit",
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
    return _mark(_raw(dispute_id))


def _saved_marked(dispute_id: str) -> tuple:
    """(decision, what was sent, its review_mark), from one reading of the review: Second Look's AI approves with the
    mark of the very review it checked, so one replaced since is refused, never sent unchecked."""
    raw = _raw(dispute_id) or {}
    dec = Decision(action=raw["action"], reasons=raw["reasons"], judgment=Judgment(**raw["judgment"]),
                   overridden=raw["overridden"], stops=raw.get("stops", []))
    return dec, raw.get("sent"), _mark(raw)


def _mark(raw: dict | None) -> str:
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


def _save(dispute_id: str, d: Decision, sent=None, seen=None, by=None, at=None, judge=None, chosen=None,
          amount=None, due=None) -> None:
    REVIEWS.mkdir(parents=True, exist_ok=True)
    extra = {"judge": judge} if judge else {}
    if chosen:      # what went out, the money it sent, and PayPal's answer-by date it went against (state.of: an
        extra.update(chosen=chosen, amount=amount, due=due)   # answer stops counting when PayPal asks again)
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
REQUEST_CHANNELS = ("email", "form")   # calls come from the call box; PayPal disputes are read from PayPal
# The call box: where the phone system leaves recorded calls (secondlook/calls.py). The demo's ships in the repo;
# a live shop sets SECONDLOOK_CALL_BOX. No call box: the morning screen says the phone isn't connected.
CALL_BOXES = {"demo": ROOT / "demo" / "calls", "live": Path(os.environ["SECONDLOOK_CALL_BOX"])
              if os.environ.get("SECONDLOOK_CALL_BOX") else None}
# How a recording becomes words: local whisper (calls.whisper). A setting, so a test never runs a model.
TRANSCRIBE = calls_mod.whisper


def shop_of_case(cid: str) -> str:
    return "demo" if is_demo(cid) else "live"


# The live shop's orders and disputes, read from PayPal (several calls each): kept LIVE_TTL seconds, so one page
# view, and the views right after it, read them once. The demo's are a file, read once already (demo._read).
LIVE_TTL = 60.0
_LIVE: dict = {}
_LIVE_LOCK = threading.Lock()


def _live_cached(key: str, read):
    now = time.monotonic()
    with _LIVE_LOCK:
        hit = _LIVE.get(key)
    if hit and now - hit[0] < LIVE_TTL:
        return hit[1]
    value = read()
    with _LIVE_LOCK:
        _LIVE[key] = (now, value)
    return value


def _live_forget() -> None:
    """Something was just sent to PayPal: the next page reads the live shop afresh."""
    with _LIVE_LOCK:
        _LIVE.clear()


def _live_read(key: str, pp):
    """The live shop's orders or disputes from PayPal (cached a minute); RuntimeError when PayPal can't be read."""
    fetch = {"orders": evidence_mod._orders, "disputes": evidence_mod.shop_disputes}[key]
    return _live_cached(key, lambda: fetch(pp, datetime.utcnow()))


def paypal_now(src: str) -> tuple | None:
    """(disputes, orders) for a decision that must not take "PayPal couldn't be read" for "nothing there" (an answered
    request closing itself); None when PayPal can't be read. shop_disputes and shop_orders read [] then, as before."""
    if src == "demo":
        return shop_disputes(src), shop_orders(src)
    pp = client_from_env(ROOT)
    if isinstance(pp, MockPayPal):
        return [], []                     # no PayPal keys: no live PayPal, so no dispute to wait for
    try:
        return _live_read("disputes", pp), _live_read("orders", pp)
    except RuntimeError:
        return None


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
        return _live_read("orders", pp)
    except RuntimeError:
        return []


def shop_disputes(src: str) -> list:
    if src == "demo":
        return DemoPayPal().disputes()
    pp = client_from_env(ROOT)
    if isinstance(pp, MockPayPal):
        return []
    try:
        return _live_read("disputes", pp)
    except RuntimeError:
        return []


def _tx_of(d: dict) -> str | None:
    return ((d.get("disputed_transactions") or [{}])[0]).get("seller_transaction_id")


def _file_request(store, src: str, req: dict, ai, later: list | None = None) -> tuple:
    """Sort one request and put it on its case. A request already filed (same source id) is not sorted again,
    so a system that sends it twice never pays for a second look by the AI. A request filed now: Second Look's AI
    takes its look (autopilot_after), or, with `later` (the demo's first morning, filed in one go), it is added there
    for a look once everything is filed."""
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
    c, how = store.file(req, s, dispute=dispute)
    if how != "already_received":
        if later is not None:
            later.append(c["id"])
        else:
            autopilot_after(src, c)
    return c, how


def transcriber_on() -> bool:
    """Is there a way to turn a recording into words here: local whisper installed, or a stand-in set by a test."""
    return TRANSCRIBE is not None and (TRANSCRIBE is not calls_mod.whisper or calls_mod.WHISPER_PYTHON.is_file())


def _transcripts(src: str):
    """What local whisper made of each recording, once: {source id: {mtime, status "done"/"failed", text}}. Kept
    beside the shop's case file (.tmp/ for the demo, records/ for the live shop)."""
    return team_mod.JsonFile(CASE_FILES[src].with_name(f"call-transcripts-{src}.json"))


def _wav_time(rec: dict) -> float | None:
    """The recording's file time; None when it is gone (removed between the box's listing and now): skipped."""
    try:
        return rec["wav"].stat().st_mtime
    except OSError:
        return None


def _whispered(rec: dict, done: dict) -> dict | None:
    """This recording's entry, if it was made from this very file (a recording replaced since is new)."""
    x = done.get(rec["source_id"])
    t = _wav_time(rec)
    return x if t is not None and isinstance(x, dict) and x.get("mtime") == t else None


def transcribe_calls(src: str) -> int:
    """The server's background work, never a page's or an API request's: local whisper on each recording of the
    call box it hasn't heard yet, once. Its words, or "failed", are kept, so a recording is never transcribed twice
    (a recording replaced in the box is new). Returns how many recordings it heard."""
    if not transcriber_on() or not CALL_BOXES.get(src):
        return 0
    n = 0
    store = _transcripts(src)
    for rec in calls_mod.recordings(CALL_BOXES.get(src)):
        t = _wav_time(rec)
        if t is None or _whispered(rec, store.snapshot()):
            continue
        text = TRANSCRIBE(rec["wav"])
        entry = {"mtime": t, "status": "done" if text else "failed", "text": text or None}
        store.transact(lambda d, k=rec["source_id"], v=entry: d.update({k: v}))
        n += 1
    return n


def file_calls(store, src: str, later: list | None = None) -> int:
    """Every recording in the shop's call box not filed yet becomes a request on the channel "call", sorted by the
    caller's number like an email by its address (rules only: no AI call). It never runs a model: it files the
    words local whisper already made in the background (transcribe_calls), else the transcript shipped beside the
    recording; a call with neither waits. A call filed with its shipped words takes whisper's once they are
    ready. Returns how many were filed."""
    n = 0
    done = _transcripts(src).snapshot()
    for rec in calls_mod.recordings(CALL_BOXES.get(src)):
        if _wav_time(rec) is None:
            continue                                  # gone since the box was listed
        w = _whispered(rec, done)
        heard = w["text"] if w and w.get("status") == "done" and w.get("text") else None
        cid = store.by_source(rec["source_id"])
        if cid:
            if heard:
                _take_whisper_s_words(store, cid, rec["source_id"], heard)
            continue
        req = calls_mod.as_request(rec, lambda wav, t=heard: t)
        if req:
            _file_request(store, src, req, ai=None, later=later)
            n += 1
    return n


def _take_whisper_s_words(store, cid: str, sid: str, text: str) -> None:
    """The call's entry, filed with the shipped words, takes local whisper's (and says so). Written once."""
    c = store.get(cid) or {}
    if not any(x.get("source_id") == sid and x.get("transcript") == calls_mod.SHIPPED for x in c.get("timeline", [])):
        return

    def take(x):
        for e_ in x["timeline"]:
            if e_.get("source_id") == sid and e_.get("transcript") == calls_mod.SHIPPED:
                e_["text"], e_["transcript"] = text[:calls_mod.MAX_TEXT], calls_mod.WHISPERED
    store.update(cid, take)


def calls_waiting(store, src: str) -> int:
    """Recordings in the box with no words yet: local whisper is on it (or failed, with nothing shipped beside)."""
    done = _transcripts(src).snapshot()
    return sum(1 for rec in calls_mod.recordings(CALL_BOXES.get(src))
               if _wav_time(rec) is not None and not store.by_source(rec["source_id"]) and not _whispered(rec, done))


def calls_failed(store, src: str) -> list:
    """Recordings local whisper couldn't hear, with no transcript shipped beside them: never filed as words nobody
    heard, and never lost either: the morning screen names each one, for a person to listen to."""
    done = _transcripts(src).snapshot()
    out = []
    for rec in calls_mod.recordings(CALL_BOXES.get(src)):
        w = _whispered(rec, done)
        if w and w.get("status") == "failed" and not store.by_source(rec["source_id"]) \
                and calls_mod.as_request(rec, lambda wav: None) is None:
            out.append(rec["wav"].name)
    return out


# The demo's first load, per case file: set once Second Look's AI's looks at the morning are done. Every other caller
# waits for it (at most 10 s), so no page shows the morning half looked at; a look itself never waits (_IN_A_LOOK).
_FIRST_LOOKS: dict = {}
_IN_A_LOOK = threading.local()


def case_store(src: str) -> cases_mod.CaseStore:
    path = CASE_FILES[src]
    store = cases_mod.CaseStore(path, prefix="DEMO-" if src == "demo" else "")
    if src == "demo":
        filed, mine = [], None
        with _SEEDING:
            if not path.exists():
                mine = _FIRST_LOOKS[str(path)] = threading.Event()
                try:
                    _forget_old_morning()
                    # the morning in the order it happened: Sophie's call (08:31) before her email (08:52) joins it
                    file_calls(store, "demo", later=filed)
                    for r in DemoPayPal().requests():   # they sort by rules alone (tests/test_demo_shop.py): no AI call
                        _file_request(store, "demo", r, ai=None, later=filed)
                except BaseException:
                    mine.set()
                    raise
        if mine is None:
            first = _FIRST_LOOKS.get(str(path))
            if first is not None and not getattr(_IN_A_LOOK, "on", False):
                first.wait(10)
            return store
        # Second Look's AI looks at the morning once it is all filed (one look per case, after the lock: its approval
        # reads this store again). The first load waits for it, at most 10 s: the demo's review of the one request it
        # handles ships with the demo, so no model is called, and the first page already shows it handled.
        # ... on the demo morning's own clock: a minute after the last request came in (Margot's, 07:40 on 20 Oct)
        heard = [x["at"] for c in store.all() for x in c["timeline"] if x.get("direction") == "in" and x.get("at")]
        morning = ((datetime.strptime(max(heard), "%Y-%m-%dT%H:%M") + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M")
                   if heard else None)
        try:
            with cases_mod.clock(morning):
                for th in [autopilot_after("demo", store.get(cid)) for cid in dict.fromkeys(filed)]:
                    if th is not None:
                        th.join(10)
        finally:
            mine.set()
    return store


def _forget_old_morning() -> None:
    """The demo's morning is about to be filed anew (no case file). What .tmp/ still says about its cases (DEMO-C…)
    was about the old morning's, and would mislead the new one: their assignments go back to the shop's own, the
    reviews made of them here go, and Second Look's AI's record forgets them. The PayPal disputes' state stays."""
    seed = {d: a for d, a in (DemoPayPal().raw.get("assignments") or {}).items() if cases_mod.is_case_id(d)}
    asg = assignments_for("DEMO-C001")
    if {d: a for d, a in asg.all().items() if cases_mod.is_case_id(d)} != seed:
        def reset(data):
            for d in [d for d in data if cases_mod.is_case_id(d)]:
                del data[d]
            data.update(json.loads(json.dumps(seed)))
        asg.transact(reset)
    for f in REVIEWS.glob("DEMO-C*.json") if REVIEWS.exists() else []:
        f.unlink()

    def forget(data):
        for d in [d for d in data["cases"] if cases_mod.is_case_id(d)]:
            del data["cases"][d]
    if any(cases_mod.is_case_id(d) for d in autopilot_store("demo").view()["cases"]):
        autopilot_store("demo").change(forget)


def autopilot_store(src: str) -> autopilot_mod.Record:
    """Second Look's AI's record in this shop (autopilot.py), beside the shop's case file: .tmp/autopilot-demo.json,
    seeded from demo/shop.json; records/autopilot-live.json for the live shop, empty (nothing on) until people decide.
    Beside the case file, so every test bench that moves the case file moves this too."""
    return autopilot_mod.Record(CASE_FILES[src].with_name(f"autopilot-{src}.json"),
                                seed=DemoPayPal().raw.get("autopilot") if src == "demo" else None,
                                fp=autopilot_mod.fingerprint(_policy()))


def _num(x) -> float | None:
    """An amount from the shop's records as a number, or None when it isn't one ("n/a", "", missing)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def _logged_refund(c: dict | None) -> dict | None:
    """The refunds a case has logged (an inquiry's answer), summed, with the last one's date and who: None if none."""
    back = [m for m in (c or {}).get("money", []) if m.get("kind") in ("refund", "partial_refund")
            and m.get("status") != "cancelled"]       # a refund a person cancelled never went out
    if not back:
        return None
    when = _t(back[-1].get("at"))
    return {"case_id": c["id"], "amount": round(sum(_num(m.get("amount")) or 0 for m in back), 2),
            "on": f"{when:%d %b %Y}" if when else "", "by": back[-1].get("by") or ""}


def _logged_goods(c: dict | None) -> dict | None:
    """The replacements a case has logged (goods that went out), summed, like _logged_refund: None if none."""
    out = [m for m in (c or {}).get("money", []) if m.get("kind") == "replace"]
    if not out:
        return None
    when = _t(out[-1].get("at"))
    return {"case_id": c["id"], "amount": round(sum(_num(m.get("amount")) or 0 for m in out), 2),
            "on": f"{when:%d %b %Y}" if when else "", "by": out[-1].get("by") or ""}


def _said(r: dict, cur: str) -> str:
    """One logged refund in words: "10.00 EUR on 25 Oct 2026 by Giulia"."""
    return f'{r["amount"]:.2f} {cur}' + (f' on {r["on"]}' if r["on"] else "") + (f' by {r["by"]}' if r["by"] else "")


def refunds_on_order(src: str, order_no: str | None) -> list:
    """Every refund logged on this order, by case (_logged_refund), from every case on it, closed ones too: a
    closed case's refund is still money that went back. One order, one total, whichever case logged it."""
    path = CASE_FILES[src]
    if not order_no or not path.exists():
        return []
    return [r for r in (_logged_refund(c) for c in cases_mod.CaseStore(path).all() if c.get("order_no") == order_no) if r]


def replacements_on_order(src: str, order_no: str | None, c: dict | None = None) -> list:
    """Every replacement or exchange logged on this order, from every case on it ({case_id, amount}): goods that
    went out, counted with the refunds against the order's value. No order: the case's own."""
    path = CASE_FILES[src]
    cases = ([x for x in cases_mod.CaseStore(path).all() if x.get("order_no") == order_no]
             if order_no and path.exists() else [c] if c else [])
    return [{"case_id": x["id"], "amount": _num(m.get("amount")) or 0.0, "at": m.get("at"), "by": m.get("by")}
            for x in cases for m in x.get("money", []) if m.get("kind") == "replace"]


def paypal_refunded(pp, cap: dict) -> float | None:
    """What PayPal already refunded on a capture, or None when it can't be told (never taken as nothing).
    A capture carries no refunded total of its own (Payments v2: that is on a refund, seller_payable_breakdown), so:
    a total the capture does carry, if ever; else the refunds its links lead to (its order's payments.refunds, each
    naming its capture, or a refund itself), read one by one, PENDING ones counted; with none found, nothing when
    the capture is COMPLETED, and not known otherwise. A link that can't be read: not known."""
    given = ((cap.get("seller_receivable_breakdown") or {}).get("total_refunded_amount") or {}).get("value")
    if given is not None:
        return _num(given)
    # its links are followed even when it is COMPLETED: a refund still PENDING (an eCheck, an unfunded balance) may
    # leave the capture COMPLETED. Nothing found where nothing could be: 0; partly refunded and nothing found: unknown
    total, found = 0.0, False
    for link in cap.get("links") or []:
        if (link.get("method") or "GET").upper() != "GET" or not link.get("href") or link.get("rel") not in (
                "up", "refund", "refunds"):
            continue
        try:
            doc = pp.get_link(link["href"]) or {}
        except Exception:  # noqa: BLE001 - unreadable: not known
            return None
        refunds = ([doc] if link.get("rel") != "up" and doc.get("amount") else
                   [r for pu in doc.get("purchase_units") or [] for r in ((pu.get("payments") or {}).get("refunds") or [])])
        for r in refunds:
            ups = [x.get("href") or "" for x in r.get("links") or [] if x.get("rel") == "up"]
            if ups and not any(h.rstrip("/").endswith(f"/captures/{cap.get('id')}") for h in ups):
                continue                                    # another capture's refund
            if r.get("status") not in (None, "COMPLETED", "PENDING"):
                continue
            v = _num((r.get("amount") or {}).get("value"))
            if v is None:
                return None
            total, found = total + v, True
    if found:
        return round(total, 2)
    return 0.0 if cap.get("status") == "COMPLETED" else None


def _cases_on_order(src: str, order_no: str | None) -> list:
    path = CASE_FILES[src]
    return [c for c in cases_mod.CaseStore(path).all() if c.get("order_no") == order_no] if order_no and path.exists() else []


def paypal_refunds_recorded(src: str, order_no: str | None) -> float:
    """What Second Look itself sent to PayPal's refund API on this order (any case), with the refunds PayPal didn't
    confirm: what PayPal may rightly show as refunded."""
    cases = _cases_on_order(src, order_no)
    sent = sum(_num(m.get("amount")) or 0 for c in cases for m in c.get("money", [])
               if m.get("via") == "PayPal refund API" and m.get("status") != "cancelled")
    return round(sent + sum(_num(x.get("amount")) or 0 for c in cases for x in c.get("unconfirmed", [])), 2)


def _marks(cases: list, cur: str = "EUR") -> list:
    """The refunds PayPal didn't confirm, on these cases: {case_id, request_id, amount, currency, on, by}."""
    out = []
    for c in cases:
        for x in c.get("unconfirmed", []):
            when = _t(x.get("at"))
            out.append({"case_id": c["id"], "request_id": x.get("request_id"), "amount": _num(x.get("amount")) or 0.0,
                        "currency": x.get("currency") or cur, "on": f"{when:%d %b %Y}" if when else "", "by": x.get("by") or ""})
    return out


def _marks_said(marks: list, here: str | None = None) -> str:
    return "; ".join(f'{m["amount"]:.2f} {m["currency"]}' + (f' on {m["on"]}' if m["on"] else "")
                     + (f' by {m["by"]}' if m["by"] else "") + ("" if m["case_id"] == here else f', on case {m["case_id"]}')
                     for m in marks)


def _money_cases_for(did: str, dispute_of) -> list:
    """The cases that logged a refund on a PayPal dispute's order: the case it joined, and every case on its order
    (the dispute's transaction is the order's transaction id), whether or not anything has linked them yet: the
    inbox -> dispute -> approve path never opens the case page, where the link is made. Read only (a dispute
    page never writes the case file), and with no case that logged money, no further reading at all:
    `dispute_of()` (which may call PayPal) and the shop's orders are read only then."""
    src = shop_of_case(did)
    path = CASE_FILES[src]
    if not path.exists():
        return []
    paid = [c for c in cases_mod.CaseStore(path).all() if _logged_refund(c) or _logged_goods(c) or c.get("unconfirmed")]
    if not paid:
        return []
    joined = [c for c in paid if c.get("dispute_id") == did]
    tx = _tx_of(dispute_of() or {})
    on = []
    # a PayPal order's number is its transaction id: only a case on that number can be this dispute's, and only
    # then are the shop's orders read (on the live shop, a Transaction Search) to check it is that transaction
    if tx and any(c.get("order_no") == tx for c in paid if c not in joined):
        # only a case whose order IS that PayPal transaction: a card or bank order's number never matches one
        by_no = {sort_mod.order_no(o): o for o in shop_orders(src)}
        on = [c for c in paid if c not in joined and c.get("order_no") == tx
              and (by_no.get(c["order_no"]) or {}).get("transaction_id") == tx]
    return joined + on


def _with_case_refund(did: str, case: dict) -> dict:
    """A PayPal dispute on an order whose cases already logged refunds (the shop answered by email before PayPal
    had it): its records say so, with the total and each case, for the judge, the page and the guard's rule 10.
    A dispute whose order has no logged refund is returned exactly as it was."""
    found = _money_cases_for(did, lambda: case["dispute"])
    rs = [r for r in (_logged_refund(c) for c in found) if r]
    gs = [g for g in (_logged_goods(c) for c in found) if g]       # replacements, listed apart from refunds
    cur = case["dispute"]["dispute_amount"].get("currency_code", "EUR")
    ms = _marks(found, cur)                                         # refunds PayPal didn't confirm
    if not rs and not gs and not ms:
        return case
    records = {**case["seller_records"], "sources": dict(case["seller_records"].get("sources", {}))}
    if ms:
        records.update(refund_unconfirmed=_marks_said(ms), unconfirmed_logged=ms)
        records["sources"]["refund_unconfirmed"] = "Your case record"
    if rs:
        total = round(sum(r["amount"] for r in rs), 2)
        each = "; ".join(f'{_said(r, cur)}, on case {r["case_id"]}' for r in rs)
        # every logged refund marked paid: proof the shop answered (guard rule 10 then lets a defence through)
        paid = all(m.get("status") == "paid" for c in found for m in c.get("money", [])
                   if m.get("kind") in ("refund", "partial_refund") and m.get("status") != "cancelled")
        # and only when what was paid covers what the dispute is about: 5 EUR paid is no proof against 89
        covers = total >= (_num(case["dispute"]["dispute_amount"].get("value")) or 0.0) - 0.005
        if paid and covers:
            records["refund_paid"] = True
            records["sources"]["refund_paid"] = "Your case record"
        records.update(refund_logged_on_case=", ".join(r["case_id"] for r in rs), refunded_so_far=total,
                       already_refunded=each if len(rs) == 1 else f"{total:.2f} {cur} in all: {each}",
                       refunds_logged=[{**r, "currency": cur} for r in rs])
        records["sources"]["already_refunded"] = "Your case record"
    if gs:
        total = round(sum(g["amount"] for g in gs), 2)
        each = "; ".join(f'{_said(g, cur).replace(f" {cur}", f" {cur} of goods", 1)}, on case {g["case_id"]}' for g in gs)
        records.update(replacement_logged_on_case=", ".join(g["case_id"] for g in gs), replaced_so_far=total,
                       already_replaced=each if len(gs) == 1 else f"{total:.2f} {cur} of goods in all: {each}",
                       replacements_logged=[{**g, "currency": cur} for g in gs])
        records["sources"]["already_replaced"] = "Your case record"
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
        return bad('channel must be "email" or "form". Phone calls come in through the call box; PayPal disputes are '
                   'read from PayPal.')
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
    joined = []
    store.link_disputes(disputes, by_no, joined)  # a PayPal dispute opened since on this order joins the case
    for _, d_ in joined:
        if d_.get("status") != "RESOLVED":
            autopilot_soon(src, "paypal", d_.get("reason"), d_["dispute_id"])
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
    close_quiet(shop_of_case(cid)) if cases_mod.is_case_id(cid) else None
    v = case_view(cid)
    if v is None:
        return None
    c = v["case"]
    decision, state = {}, None
    if c["sorted"]["by"]:
        full = api_case(v["decision_id"], as_person=as_person)
        decision = {k: full[k] for k in ("review", "for_person", "handoff") if k in full}
        state = full["state"]
    if state is None:
        st = case_state(v["decision_id"], v["dispute"], c)
        state = {**st, "until": st["until"].isoformat() if st["until"] else None}
    return {**decision, "decision_id": v["decision_id"],
            "state": state,
            "case_id": c["id"], "stage": c["stage"], "stage_label": cases_mod.STAGE_LABEL[c["stage"]],
            "status": c["status"], "outcome": c["outcome"], "problem": c["problem"],
            "customer": {**c["customer"], "role": "customer"}, "order": v["order"], "sorted": c["sorted"],
            "at_stake": {"value": v["at_stake"], "currency_code": v["currency"]}, "channels": v["channels"],
            "channel_labels": [cases_mod.CHANNEL_LABEL.get(ch, ch) for ch in v["channels"]],
            "earlier_case": c.get("earlier_case"), "later_cases": c.get("later_cases", []),
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
    back = refunds_on_order(v["src"], c.get("order_no")) if c.get("order_no") else \
        [r for r in (_logged_refund(c),) if r]
    refunded = round(sum(r["amount"] for r in back), 2)
    goods = replacements_on_order(v["src"], c.get("order_no"), c)
    replaced = round(sum(g["amount"] for g in goods), 2)
    left = max(0.0, round(v["at_stake"] - refunded - replaced, 2))
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
    # Decision 8: an exchange counts the new parcel's postage once the returned item is back at the shop (the
    # courier's record of the return, or the shop's own); until then, and with no postage on record, full price.
    # Only for this case's own exchange (review 25/10): a wrong size, a return tied to this case (recorded against
    # it, or sent or received from the day it opened), delivered to the shop, and not yet used by a replacement.
    ret = (o.get("return") or {}) if o else {}
    to_shop = not ret.get("delivered_to") or "shop" in str(ret["delivered_to"]).lower()
    returned = (ret.get("status") == "DELIVERED" and to_shop) or bool(ret.get("received_at_shop"))
    when = str(ret.get("shipped_date") or ret.get("received_at_shop") or ret.get("last_update") or "")[:10]
    tied = (ret.get("case_id") == cid or ret.get("source_id") in {x.get("source_id") for x in c["timeline"] if x.get("source_id")}
            or bool(when) and when >= str(c["opened"])[:10])
    shop = DemoPayPal().shop if v["src"] == "demo" else _live_shop()
    postage = _num((shop.get("costs") or {}).get("postage"))
    if ret:
        # the day it came back: the shop's terms count their refund days from it. Both records: the earlier one,
        # so a receipt the shop logged late never stretches the days the customer is owed.
        back_on = min((str(d)[:10] for d in (ret.get("received_at_shop"),
                                             ret.get("last_update") if ret.get("status") == "DELIVERED" else None) if d),
                      default="")
        records["return"] = (f'{ret.get("carrier") or "Courier"} {ret.get("tracking_number") or ""}'.strip()
                             + ((", back at the shop" + (f" (on {back_on})" if back_on else "")) if returned
                                else f', {str(ret.get("status") or "on its way").lower()}'))
        sources["return"] = "Courier tracking"
    if returned and tied and not goods and c["problem"]["kind"] == "wrong_size" and postage is not None:
        dispute["exchange_cost"] = min(postage, left)
        records["exchange_counts"] = (f'An exchange counts {min(postage, left):.2f} {v["currency"]}, the postage of the '
                                      "new parcel: the returned item is back at the shop. A refund counts in full.")
        sources["exchange_counts"] = "Your shop terms"
    # the shop's own order amount: only inquiries carry it, so the guard's rule 9 never touches a PayPal dispute
    records["order_amount"] = _num(o.get("amount")) if o else None     # unreadable: no order with an amount
    records["refunded_so_far"] = refunded
    ms = _marks(_cases_on_order(v["src"], c.get("order_no")) if c.get("order_no") else [c], v["currency"])
    if ms:
        records["refund_unconfirmed"] = _marks_said(ms, cid)
        sources["refund_unconfirmed"] = "Your case record"
    records["replaced_so_far"] = replaced
    if goods:
        records["already_replaced"] = "; ".join(
            f'{g["amount"]:.2f} {v["currency"]} in goods' + (f' by {g["by"]}' if g.get("by") else "")
            + ("" if g["case_id"] == cid else f', on case {g["case_id"]}') for g in goods)
        sources["already_replaced"] = "Your case record"
    if back:
        each = "; ".join(_said(r, v["currency"]) + ("" if r["case_id"] == cid else f', on case {r["case_id"]}')
                         for r in back)
        records["already_refunded"] = each if len(back) == 1 else f"{refunded:.2f} {v['currency']} in all: {each}"
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
    if c["status"] != "open":
        return (f"This case is closed: {cases_mod.outcome_says(c, CLOSE_OUTCOMES)}. "
                "A new message from the customer opens a new case.")
    if c.get("dispute_id"):
        return f"This case is a PayPal dispute now: answer it on {c['dispute_id']}."
    return None


def review_inquiry(cid: str, judge: str) -> Decision:
    """Second Look's AI (or, with no key, the rules baseline) on an inquiry, then the guard, unchanged."""
    no = _inquiry_refusal(cid)
    if no:
        raise ValueError(no)
    from .__main__ import review_inquiry_case  # the eval runs this same path
    return review_inquiry_case(_case(cid), judge, _policy())


class RefundNotConfirmed(Exception):
    """PayPal didn't confirm a refund (an error, a timeout): no money is recorded and the review is not sent. When the
    refund itself was asked for (`attempted`), PayPal may still have made it: the case keeps a "not confirmed" mark."""
    def __init__(self, msg: str, attempted: bool = False, amount: float = 0.0, currency: str = "EUR"):
        super().__init__(msg)
        self.attempted, self.amount, self.currency = attempted, amount, currency


class RefundRefused(Exception):
    """PayPal's record of the payment says it can't be refunded from here (not completed, nothing left)."""


class Outbox:
    """The approved answer to an inquiry, recorded: a signed "out" entry on the case's timeline, on the channel
    the customer used, any money as a logged entry on the case, and one line in the action log. The same
    interface as the PayPal clients, so execute() runs it unchanged. A refund on an order paid through PayPal goes to
    PayPal's refund API; nothing else is sent from here."""

    def __init__(self, cid: str, by: str, ai: bool, amount: float, request_id: str | None = None,
                 autopilot: bool = False):
        self.cid, self.by, self.ai, self.amount = cid, by, ai, amount
        self.autopilot = autopilot        # Second Look's AI approved it on its own: no person wrote or sent it
        self.request_id = request_id      # PayPal-Request-Id: the same for a retry of the same approval
        self.src = shop_of_case(cid)

    def _out(self, action: str, text: str, money: dict | None = None) -> dict:
        store = case_store(self.src)
        c0 = store.get(self.cid)
        ch = reply_channel(c0)
        sent = {}
        if money and money["kind"] in ("refund", "partial_refund"):
            # Paid through PayPal (the order is a captured PayPal payment): PayPal refunds it, before anything is
            # recorded, so a refused refund is never logged as done. Paid by card or bank: logged for the shop's
            # payment provider, which Second Look doesn't reach (the person marks it paid when it is).
            o = _raw_order(self.src, c0.get("order_no"))
            capture = (o or {}).get("transaction_id")
            if capture:
                pp = paypal_for(self.src)
                cur, amount = (o or {}).get("currency") or "EUR", float(money["amount"])
                if not isinstance(pp, MockPayPal):
                    # a live payment: PayPal's own record first (its status, its currency, what is left to refund)
                    try:
                        cap = pp.get_capture(capture) or {}
                    except Exception as err:  # noqa: BLE001 - nothing recorded, nothing sent
                        raise RefundNotConfirmed(str(err)) from err
                    if cap.get("status") not in ("COMPLETED", "PARTIALLY_REFUNDED"):
                        raise RefundRefused(f"PayPal shows this payment as {cap.get('status') or 'unknown'}: it can't be "
                                            "refunded from here. Check it in PayPal.")
                    total = _num((cap.get("amount") or {}).get("value")) or 0.0
                    cur = (cap.get("amount") or {}).get("currency_code") or cur
                    done = paypal_refunded(pp, cap)
                    if done is None:          # never guessed as nothing: a refund on top of an unknown one
                        raise RefundRefused("Second Look couldn't read what PayPal already refunded on this payment: "
                                            "check it in PayPal.")
                    ours = paypal_refunds_recorded(self.src, c0.get("order_no"))
                    if done > ours + 0.005:
                        raise RefundRefused(f"PayPal shows {done - ours:.2f} {cur} refunded that Second Look didn't record: "
                                            "check in PayPal.")
                    amount = min(amount, round(total - done, 2))
                    if amount <= 0:
                        raise RefundRefused("PayPal shows nothing left to refund on this payment.")
                try:
                    r = pp.refund_capture(capture, f"{amount:.2f}", cur, text, request_id=self.request_id)
                except Exception as err:  # noqa: BLE001 - not confirmed: no money recorded, the review not sent
                    raise RefundNotConfirmed(str(err), attempted=True, amount=amount, currency=cur) from err
                money = {**money, "amount": amount}
                sent = {"via": "PayPal refund API", "status": "sent to PayPal", "refund_id": r.get("id"),
                        "currency": cur}
            else:
                sent = {"via": "for your payment provider (not connected)"}
        index = len(c0.get("money", []))

        def change(c):
            c["timeline"].append(cases_mod.entry(None, ch, "out", text, self.by, ai=self.ai, action=action,
                                                 **({"autopilot": True} if self.autopilot else {})))
            if money:
                c["money"].append({**money, **sent, "at": cases_mod.minute(None), "by": self.by})
            if self.request_id:       # a retry PayPal confirmed: its "not confirmed" mark is answered
                c["unconfirmed"] = [x for x in c.get("unconfirmed", []) if x.get("request_id") != self.request_id]
        store.update(self.cid, change)
        if money:
            _book_case_entry(self.src, self.cid, index)
        log = OUTBOX_LOGS[self.src]
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": cases_mod.minute(None), "case_id": self.cid, "action": action, "channel": ch,
                                "by": self.by, "text": text, **({"money": money} if money else {})},
                               ensure_ascii=False) + "\n")
        return {"status": "LOGGED", "channel": ch,
                **({"via": "paypal", "amount": money["amount"], "currency": sent.get("currency")} if sent.get("refund_id") else {})}

    def message(self, did, text):
        return self._out("reply", text)

    def refund(self, did, note):
        return self._out("refund", note, {"kind": "refund", "amount": self.amount})

    def partial_refund(self, did, amount, currency, note):
        return self._out("partial_refund", note, {"kind": "partial_refund", "amount": float(amount)})

    def replace(self, did, note):
        # goods going out: their value (what is left of the order) is logged, so a second one is seen (rule 9)
        return self._out("replace", note, {"kind": "replace", "amount": self.amount})

    def defend(self, did, note, tracking=None):
        raise RuntimeError("An inquiry has no PayPal evidence to submit: nothing was sent.")


def paypal_for(src: str):
    """The PayPal client a shop's refunds go through: the demo's (logged, never sent) or the live shop's."""
    return DemoPayPal() if src == "demo" else client_from_env(ROOT)


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
    with _case_lock(cid):   # never between an approval's read and its send: closing waits for it
        return _close(store, cid, outcome, who)


def _close(store, cid: str, outcome: str, who: dict) -> tuple:
    if (store.get(cid) or {}).get("status") != "open":
        return 409, "This case is closed already."

    def close(x):
        x["status"], x["outcome"], x["closed_at"] = "closed", outcome, cases_mod.minute(None)
        x["timeline"].append(cases_mod.entry(None, reply_channel(x), "note",
                                             f"Closed by {who['name']}: {CLOSE_OUTCOMES[outcome].lower()}.", who["name"]))
    store.update(cid, close)
    return 200, f"Closed: {CLOSE_OUTCOMES[outcome].lower()}."


def shop_today(src: str):
    """The shop's today: the demo's is fixed (20 Oct 2026); a live shop's is the computer's, in UTC."""
    return DemoPayPal().today if src == "demo" else datetime.utcnow().date()


def quiet_days() -> int:
    """policy.json "close_answered_after_days": an answered request closes itself after this many days with no word
    from the customer. 3 when it isn't a whole number of 1 or more."""
    v = _policy().get("close_answered_after_days")
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else 3


def _handoff_waits(c: dict) -> bool:
    """A colleague passed this case to someone and it waits for them: it never closes on its own meanwhile."""
    a = None if team_for(c["id"]).get("solo") else assignments_for(c["id"]).get(c["id"])
    return isinstance((a or {}).get("handoff"), dict)


def close_quiet(src: str) -> list:
    """Every answered request whose customer stayed quiet for the shop's days closes itself, as solved before any
    dispute, signed (cases.closes_on), and stamped on the day it was due: a late look never moves it to another week.
    Code, not AI. Run at each look at the shop's cases, against the shop's today: no timer.
    Never one a customer may have spoken on since: the call box is filed first, and nothing closes while a recording
    is still being transcribed. Never one a PayPal dispute is on, even before anything linked it (today.links reads
    that without writing), and nothing at all when PayPal can't be read; nor one a handoff waits on. Checked again
    under the case's lock, and once more inside the write: a customer who just wrote keeps it open."""
    if src not in CASE_FILES:
        return []
    days, today, store, done = quiet_days(), shop_today(src), case_store(src), []
    if CALL_BOXES.get(src):
        file_calls(store, src)
        if transcriber_on() and calls_waiting(store, src) > 0:
            return []                   # a call whose words aren't in yet may be the customer speaking again
    cases = store.all()

    def due(c) -> bool:
        on = cases_mod.closes_on(c, days) if c else None
        return on is not None and on <= today
    if not any(due(c) for c in cases):
        return []
    read = paypal_now(src)
    if read is None:
        return []                       # PayPal couldn't be read: a dispute may be open on any of them
    disputed = {c["id"] for c in today_mod.links(cases, *read).values()}
    for c in cases:
        if not due(c) or c["id"] in disputed:
            continue
        with _case_lock(c["id"]):
            if not due(store.get(c["id"])) or _handoff_waits(c):
                continue
            closed = []

            def close(y):
                if not due(y):             # the customer's message was filed in between: it stays theirs
                    return
                at = f"{cases_mod.closes_on(y, days).isoformat()}T00:00"
                y["status"], y["outcome"], y["closed_at"], y["closed_by"] = "closed", "solved", at, "Second Look"
                # stamped on the day it was due, appended after whatever was filed since (the page reads it in time)
                y["timeline"].append(cases_mod.entry(at, reply_channel(y), "note",
                                                     f"Closed by Second Look: no reply in {days} days.", "Second Look"))
                closed.append(y["id"])
            store.update(c["id"], close)
            done += closed
    return done


def _closes_words(c: dict | None) -> str:
    """"Answered · closes on 23 Oct if Margot doesn't write", or "" when it won't: the case doesn't close itself, a
    handoff waits on it, or its day came and something held it open (every look closes what is due first)."""
    on = cases_mod.closes_on(c, quiet_days()) if c else None
    if on is None or _handoff_waits(c) or on <= shop_today(shop_of_case(c["id"])):
        return ""
    first = ((c.get("customer") or {}).get("name") or "").split(" ")[0] or "the customer"
    return f"Answered · closes on {on.day} {on:%b} if {first} doesn't write"


# Money PayPal pays out at once. A partial refund on a dispute is an offer the buyer must accept first: until then
# the case waits for the customer (code review of Task 1, 30/10).
REFUNDS = ("REFUND",)


def _sent_refund(raw: dict | None) -> bool:
    """The answer that went out sent money back. A review sent before 30/10 doesn't say what was chosen: its own
    sentence does ("Refund accepted…", "Refund of 64.00 EUR logged…")."""
    raw = raw or {}
    if not raw.get("sent"):
        return False
    if raw.get("chosen"):
        return raw["chosen"] in REFUNDS
    return str(raw["sent"]).startswith("Refund")


_CONFIRM_LOCK = threading.Lock()


def _confirmed_file() -> Path:
    # beside the reviews: every test bench that moves them moves this too
    return REVIEWS.parent / "paypal-demo-confirmed.json"


def demo_confirmed() -> dict:
    """The demo shop's PayPal confirmations of refunds sent from Second Look: {dispute id: when}. Simulated, and every
    page that shows one says so (spec 2026-10-30, Part 4). Only the demo's disputes (DEMO-031…) are ever here."""
    try:
        return json.loads(_confirmed_file().read_text())
    except (OSError, ValueError):
        return {}


def confirm_demo_refunds() -> list:
    """The look after a refund in the demo shop: its PayPal "confirms" it, as a real one would within minutes, so the
    film can show a case reach Done. Nothing in the demo reaches PayPal, so without this a refunded case waited for
    PayPal forever. Never on the sandbox or a live shop. Returns the ids confirmed now."""
    with _CONFIRM_LOCK:
        done, new = demo_confirmed(), []
        for f in sorted(REVIEWS.glob("DEMO-*.json")) if REVIEWS.exists() else []:
            raw = _raw(f.stem) if re.fullmatch(r"DEMO-\d+", f.stem) else None
            if not _sent_refund(raw):
                continue
            # a confirmation belongs to the answer it confirmed: refunded again after a fresh review, it confirms again
            sent_at = _utc_minute(raw["at"]) if raw.get("at") else ""
            if f.stem not in done or done[f.stem] < sent_at:
                done[f.stem] = cases_mod.minute(None)
                new.append(f.stem)
        if new:
            target = _confirmed_file()
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_text(json.dumps(done))
            os.replace(tmp, target)
        return new


# case_state's "this dispute has no shop case, don't look for one": Today knows it already and must not re-read the
# case file for every open dispute (None means "look it up").
NO_CASE: dict = {}


def case_state(did: str, dispute: dict | None = None, c: dict | None = None, out_of_date: bool = False,
               today=None) -> dict:
    """The one state of a case (state.of), from what Second Look holds: the review and what was sent, who has the case,
    its shop case and its PayPal dispute. `did`: the decision id (the PayPal dispute's, else the shop case's).
    `dispute`, `c`: when the caller has them already (Today reads every case once). `out_of_date`: the case page's own
    finding (_changes); Today doesn't ask. Returns state.of's dict plus "decision_id"."""
    if cases_mod.is_case_id(did):
        if c is NO_CASE:
            c = None            # the sentinel is for disputes; an empty dict must never be read as a closed case
        src = shop_of_case(did)
        c = c if c is not None else case_store(src).get(did)
        if c is not None and c.get("dispute_id"):
            return case_state(c["dispute_id"], dispute, c, out_of_date, today)   # a dispute on it: PayPal's rules
    else:
        src = src_of_case(did, "live")
        if dispute is None:
            dispute = _case(did)["dispute"]
        if c is NO_CASE:
            c = None
        elif c is None and src in CASE_FILES:
            c = find_case_of_dispute(did)
    raw = _raw(did) or {}
    seen = raw.get("seen") or {}
    answered_at = None
    if raw.get("sent"):
        if raw.get("at"):
            answered_at = _utc_minute(raw["at"])
        elif dispute:
            # sent before `at` was recorded: the answer counts only while the buyer hasn't written beyond what the
            # review saw (no time to compare, so the message count stands in for it)
            n = sum(1 for m in dispute.get("messages", []) if m.get("posted_by") == "BUYER")
            answered_at = "9999-12-31T23:59" if n <= seen.get("buyer_messages", 0) else "0000-01-01T00:00"
        else:
            answered_at = "9999-12-31T23:59"    # a shop case: its closes_on decides
    t = team_for(did)
    a = None if t.get("solo") else assignments_for(did).get(did)
    hand = (a or {}).get("handoff") if isinstance((a or {}).get("handoff"), dict) and not raw.get("sent") else None
    frm = None
    if hand:
        p = team_mod.person(t, hand.get("from"))
        frm = (p or {}).get("name") or hand.get("from_name") or "a colleague"
    closes = cases_mod.closes_on(c, quiet_days()) if c is not None and dispute is None and not hand else None
    confirmed = demo_confirmed().get(did) if is_demo(did) and not cases_mod.is_case_id(did) else None
    if confirmed and not (_sent_refund(raw) and answered_at and confirmed >= answered_at):
        confirmed = None    # a confirmation belongs to the answer it confirmed, not to a later review of the case
    st = state_mod.of(c, dispute, today or shop_today(src if src in ("demo", "live") else "live"),
                      answered_at=answered_at, answered_stage=seen.get("stage") if dispute else None,
                      answered_due=raw.get("due"), money_sent=_sent_refund(raw), out_of_date=out_of_date,
                      holder=(a or {}).get("to"), handoff_from=frm, closes_on=closes, confirmed_at=confirmed)
    return {**st, "decision_id": did}


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
    limits.append(f'An answered request closes itself, as solved before any dispute, after {quiet_days()} days with no '
                  'word from the customer. Not one with money or goods logged on it: a person closes those.')
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
            f'<ul class="limits">{"".join(f"<li>{e(x)}</li>" for x in limits)}</ul></section>'
            + autopilot_block("demo" if demo else "live", me))
    return page("Your rules | Second Look", "", body, demo, me=me, here="rules")


# A kind of case in plain words: "Shop inquiry · Says it never arrived · Reply only".
STAGE_SAYS = {"inquiry": "Shop inquiry", "paypal": "PayPal dispute or claim"}


def kind_words(kind: str) -> str:
    stage, problem, action = autopilot_mod.split_kind(kind)
    what = cases_mod.KIND_LABEL.get(problem) if stage == "inquiry" else REASON.get(problem)
    act = (INQUIRY_ACTION if stage == "inquiry" else ACTION).get(action, action)
    return f"{STAGE_SAYS.get(stage, stage)} · {what or problem} · {act}"


def _named(people: list) -> str:
    return " or ".join(f"{p['name']}, {p['role'].lower()}" if p.get("role") else p["name"] for p in people) or "nobody here"


def autopilot_block(src: str, me: str | None) -> str:
    """The Rules page's "Second Look's AI on its own": each kind with its record, ready / on / off, the switch (the head
    of customer care only), and the shop's four numbers in plain words."""
    t = team_for_src(src)
    s, rec = autopilot_mod.settings(t), autopilot_store(src).view()
    cur = _shop_currency(t, src == "demo") or _policy().get("currency", "")
    heads = _named(autopilot_mod.heads(t))
    can = autopilot_mod.may_switch(t, me)
    numbers = [f"A kind of case is ready once people approved its advice unchanged on the last {s['window']} cases of "
               f"that kind. Ready is not on: {heads} switches it on, and off.",
               f"It answers on its own only when it is at least {s['min_confidence']:.0%} sure (a person's approval "
               f"needs {_policy()['min_confidence']:.0%}), and steps back to a person whenever your limits raise anything.",
               f"At most {s['per_day']} cases of one kind a day.",
               f"It gives back money on its own up to {s['refund_up_to']:.2f} {cur}. Over that it passes the case to a "
               "person, as a colleague over their limit does, and sends nothing."]
    by = (f'<input type="hidden" name="by" value="{e(me)}">' if me else "") + \
        f'<input type="hidden" name="shop" value="{e(src)}">'
    rows = []
    for kind, k in sorted(rec["kinds"].items()):
        n, sw, off = autopilot_mod.streak(k), k.get("switched") or {}, k.get("off") or {}
        ready = n >= s["window"]
        record = (f"{s['window']} of the last {s['window']} approved as advised" if ready
                  else f"{n} approved as advised in a row: it needs {s['window']}")
        later = autopilot_mod.split_kind(kind)[0] not in autopilot_mod.SWITCHABLE
        state = (autopilot_mod.NOT_YET if later
                 else f"On, switched on by {sw.get('by')} on {_when(sw.get('at') or '')}" if k.get("on")
                 else "Ready: off until it is switched on" if ready
                 else "Off" + (f": {off['why']}" if off.get("why") else ""))
        switch = (f'<form method="post" action="/autopilot/switch"><input type="hidden" name="kind" value="{e(kind)}">'
                  f'<input type="hidden" name="on" value="{"off" if k.get("on") else "on"}">{by}'
                  f'<button{" class=quiet" if k.get("on") else ""}>{"Switch off" if k.get("on") else "Switch on"}</button></form>'
                  if can and (k.get("on") or (ready and not later)) else "")
        rows.append(f'<li><span><b>{e(kind_words(kind))}</b><span class="t-sub">{e(record)} · {e(state)}</span></span>'
                    f'{switch}</li>')
    restarted = rec.get("restarted") or {}
    return ('<section class="rules"><h2>Second Look\'s AI on its own</h2>'
            '<p class="who">In this shop. Second Look\'s AI may answer a kind of case on its own (the stage, the problem '
            'and its answer) once your people trusted it there. Everything it sends is signed. Only your people\'s '
            'decisions count, never its own.</p>'
            + (f'<p class="check-sender">{e(restarted["why"])}</p>' if restarted.get("why") else "")
            + f'<ul class="rulelist">{"".join(rows) or "<li><span>No decisions on its advice yet.</span></li>"}</ul>'
            + ("" if can else f'<p class="who">Only {e(heads)} switches a kind on or off.</p>')
            + f'<ul class="limits">{"".join(f"<li>{e(x)}</li>" for x in numbers)}</ul></section>')


def autopilot_switch(src: str, kind: str, on: bool, by: str | None) -> tuple:
    """The head of customer care switches a ready kind on, or a kind off (the Rules page). Nobody else can."""
    t = team_for_src(src)
    who = team_mod.person(t, by)
    if not who:
        return 400, "Say who you are: a person in this shop's team."
    if not autopilot_mod.may_switch(t, who["id"]):
        return 403, f"Only {_named(autopilot_mod.heads(t))} switches Second Look's AI on or off."
    stage, problem, action = autopilot_mod.split_kind(kind or "")
    if stage not in STAGE_SAYS or not problem or action not in ACTION or action == "ASK_SELLER":
        return 400, "No such kind of case."
    return autopilot_store(src).switch(kind, on, who["name"], cases_mod.minute(None), autopilot_mod.settings(t)["window"])


def autopilot_differently(src: str, did: str, by: str | None, why: str = "") -> tuple:
    """A person would have done differently what Second Look's AI sent on its own: that kind goes off at once and its
    count restarts, with who and why. What was sent stays sent: the person follows up."""
    t = team_for_src(src)
    who = team_mod.person(t, by)
    if not who:
        return 400, "Say who you are: a person in this shop's team."
    code, out = autopilot_store(src).differently(did, who["name"], why, cases_mod.minute(None),
                                                 autopilot_mod.settings(t)["window"])
    if code != 200:
        return code, out
    note = " ".join((why or "").split())[:300].rstrip(".")
    text = (f"{who['name']} would have done it differently" + (f": {note}" if note else "") + ". Second Look's AI no "
            f"longer answers these on its own ({kind_words(out)}), and its count starts again. What it sent stays sent: "
            f"{who['name']} follows up.")
    c = case_store(src).get(did) if cases_mod.is_case_id(did) else find_case_of_dispute(did)
    if c:
        case_store(src).add(c["id"], cases_mod.entry(None, reply_channel(c), "note", text, who["name"]))
    return 200, text


def autopilot_looks_right(src: str, did: str, by: str | None) -> tuple:
    """A person checked what Second Look's AI sent on its own, and it looks right: noted on its record and on the case."""
    who = team_mod.person(team_for_src(src), by)
    if not who:
        return 400, "Say who you are: a person in this shop's team."
    code, out = autopilot_store(src).looks_right(did, who["name"], cases_mod.minute(None))
    if code != 200:
        return code, out
    text = f"{who['name']} checked what Second Look's AI sent on its own: it looks right."
    c = case_store(src).get(did) if cases_mod.is_case_id(did) else find_case_of_dispute(did)
    if c:
        case_store(src).add(c["id"], cases_mod.entry(None, reply_channel(c), "note", text, who["name"]))
    return 200, text


def _back_to(to: str, src: str) -> str:
    """Where a check sends the person back: the case page they were on, or the morning screen. Never elsewhere."""
    return to if re.fullmatch(r"/c/[A-Za-z0-9-]+", to or "") else f"/today?shop={src}"


def ai_check_form(src: str, did: str, me: str | None, back: str) -> str:
    """Looks right / I'd have done it differently, on what Second Look's AI sent on its own (anyone in the team). The
    reason opens only after the second button. Once checked: who checked it, and how. Nothing when it didn't answer."""
    x = autopilot_store(src).view()["cases"].get(did) or {}
    if not x.get("handled"):
        return ""
    ch = x.get("checked")
    if ch:
        return (f'<p class="t-sub">{e(ch["by"])} would have done it differently</p>' if ch.get("differently") else
                f'<p class="t-sub">{e(ch["by"])} checked it: looks right</p>')
    hidden = (f'<input type="hidden" name="case" value="{e(did)}"><input type="hidden" name="shop" value="{e(src)}">'
              f'<input type="hidden" name="to" value="{e(back)}">'
              + (f'<input type="hidden" name="by" value="{e(me)}">' if me else ""))
    return (f'<div class="ai-check-actions"><form method="post" action="/autopilot/looks-right">{hidden}'
            '<button class="quiet">Looks right</button></form>'
            '<details><summary class="quiet">I&#x27;d have done it differently</summary>'
            f'<form method="post" action="/autopilot/differently" class="addrule">{hidden}'
            '<input name="why" maxlength="300" aria-label="What you would have done" '
            'placeholder="What you would have done (optional)"><button>Switch it off and note it</button></form>'
            '</details></div>')


def autopilot_handled(src: str, today, rec: dict | None = None, since: bool = True) -> list:
    """What Second Look's AI answered on its own since yesterday, for a person to check; with `since` False, every
    answer it ever sent (Needs you keeps an unchecked one until someone checks it). `rec`: its record, read once by
    the page."""
    start = today_mod.since(today) if since else ""
    out, store = [], case_store(src)
    for did, x in (rec or autopilot_store(src).view())["cases"].items():
        if not x.get("handled") or (x.get("at") or "") < start:
            continue
        c = store.get(did) if cases_mod.is_case_id(did) else find_case_of_dispute(did)
        out.append({"id": did, "link": f"/c/{c['id']}" if c else f"/d/{did}", "at": x["at"], "kind": x["kind"],
                    "kind_words": kind_words(x["kind"]), "who": ((c or {}).get("customer") or {}).get("name"),
                    "what": str(x.get("what") or "").split(". Sent by ")[0].rstrip("."), "checked": x.get("checked")})
    return sorted(out, key=lambda h: h["at"])

# What a review was based on. If any of it changes, the review is out of date and Approve is withdrawn:
# the seller must never approve an answer to a situation that no longer exists.
CHANGED = {"buyer_messages": "the buyer wrote again", "stage": "PayPal moved the case to another stage",
           "amount": "the amount in dispute changed", "tracking": "tracking was added or changed",
           "ship_to": "PayPal now shows the buyer's address",
           "case_refund": "a refund was logged on this order's case",
           "case_refund_paid": "a refund on this order's case was marked paid",
           "case_unconfirmed": "a refund on this order's case wasn't confirmed by PayPal",
           "case_goods": "a replacement was logged on this order's case"}


# The same, for a shop inquiry, in its own words; "who" is whose case it is (customer, order, first request).
CHANGED_INQUIRY = {"buyer_messages": "the customer wrote again", "stage": "the case became a PayPal dispute",
                   "amount": "the amount at stake changed (a refund was logged, or the order changed)",
                   "tracking": "the courier's tracking changed", "ship_to": "the delivery address changed",
                   "who": "the case is now about another customer or order",
                   "words": "the customer's words changed (a call's transcript was updated)",
                   "return": "the returned item reached the shop"}


def _seen(case: dict) -> dict:
    d, r = case["dispute"], case["seller_records"]
    seen = {"buyer_messages": sum(1 for m in d.get("messages", []) if m.get("posted_by") == "BUYER"),
            "stage": d.get("dispute_life_cycle_stage"), "amount": d["dispute_amount"]["value"],
            "tracking": (r.get("tracking") or {}).get("tracking_number"), "ship_to": bool(r.get("ship_to"))}
    if case.get("inquiry"):
        seen["who"] = case["inquiry"].get("identity")
        # what the customer said, in order: a call's words taken from local whisper after the review are new words
        said = "\n".join(m.get("content") or "" for m in d.get("messages", []) if m.get("posted_by") == "BUYER")
        seen["words"] = hashlib.sha256(said.encode("utf-8")).hexdigest()[:16]
        seen["return"] = d.get("exchange_cost")             # the returned item reached the shop since
    if r.get("refund_logged_on_case"):   # only then: a dispute whose case logged no money sees exactly what it saw
        seen["case_refund"] = r.get("refunded_so_far")
        seen["case_refund_paid"] = bool(r.get("refund_paid"))
    if r.get("refund_unconfirmed") and not case.get("inquiry"):
        seen["case_unconfirmed"] = r.get("refund_unconfirmed")
    if r.get("replacement_logged_on_case"):
        seen["case_goods"] = r.get("replaced_so_far")
    return seen


def _changes(dispute_id: str, case: dict) -> list:
    raw = _raw(dispute_id)  # a shipped demo review is judged by what it saw, like any other
    seen = raw.get("seen") if raw is not None else None
    if seen is None:
        return ["this review was saved before Second Look tracked changes"]
    now = _seen(case)
    words = CHANGED_INQUIRY if cases_mod.is_case_id(dispute_id) else CHANGED
    out = [k for k in words if seen.get(k) != now.get(k)]
    if "buyer_messages" in out and "words" in out:
        out.remove("words")                           # a new message: "the customer wrote again" says it
    return [words[k] for k in out]


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
/* numbers: tiles, bar lists, PayPal's line */
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin:24px 0 36px}}
.tile{{background:#fff;border:1px solid var(--rule);padding:18px 20px;display:flex;flex-direction:column;gap:4px}}
.tile b{{font-size:34px;line-height:1.1;font-variant-numeric:tabular-nums}} .t-label{{font-weight:500}} .t-sub{{color:var(--soft);font-size:14px}}
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
.talk .t-sub{{display:block}} .talk q{{white-space:pre-line}} .pick input{{width:100%;font:400 16px "Schibsted Grotesk",sans-serif;padding:10px 12px;border:1px solid var(--rule);background:#fff}}
.pick label{{display:block;font-weight:700;margin:12px 0 6px}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 12px}} .chip{{font-size:14px;padding:3px 10px;border-radius:14px;background:#EEF2F4}}
.chip.off{{color:var(--soft);background:transparent;border:1px dashed var(--rule)}}
ol.see,ul.see{{list-style:none;padding:0;margin:0}} .see li a{{display:grid;grid-template-columns:auto 1fr auto;gap:10px;padding:9px 0;border-top:1px solid var(--rule);text-decoration:none;font-size:15px}}
.see .rec{{display:block;color:var(--soft)}} .due{{color:var(--incon);font-weight:700;white-space:nowrap}} .due.soft{{color:var(--soft);font-weight:400}}
.ai-tag.rules{{border-color:var(--unclear);color:var(--soft)}}
.morning{{max-width:880px}} .morning h1.page{{margin-bottom:4px}} .rule-line{{margin-top:18px}}
section.needs,section.new,section.team{{background:#fff;border:1px solid var(--rule);padding:18px 20px;margin-top:20px}}
section.needs{{border-left:4px solid var(--incon)}} section.needs.calm{{border-left-color:var(--pass)}}
.needs-list{{list-style:none;padding:0;margin:0}} .needs-list li{{border-top:1px solid var(--rule);padding:10px 0}}
.needs-list li:first-child{{border-top:0}} .needs-list li a{{display:grid;grid-template-columns:1fr auto;gap:10px;text-decoration:none;color:inherit}}
.needs-list .ai-head{{font-weight:700;padding-top:14px}} .needs-list .what .t-sub{{display:block}}
.ai-check-actions{{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-start;margin-top:8px}}
.ai-check-actions details{{flex:1 1 260px}} .ai-check-actions summary{{display:inline-block;cursor:pointer;list-style:none}}
.ai-check-actions summary.quiet{{color:var(--soft);border:1px solid var(--rule);padding:6px 12px;font-size:14px;background:#fff}}
.ai-check-actions summary::-webkit-details-marker{{display:none}}
.ai-check-actions details form{{margin-top:8px}}
.see .has{{display:block;font-size:14px}} .see .has.none{{color:var(--incon)}}
table.compare{{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--rule)}}
table.compare th,table.compare td{{text-align:right;padding:10px 14px;border-top:1px solid var(--rule)}} table.compare td{{font-variant-numeric:tabular-nums}}
table.compare th[scope=row]{{text-align:left;font-weight:500}} table.compare th[scope=row] .t-sub{{display:block;font-weight:400}}
table.compare tr.sub th,table.compare tr.sub td{{border-top:0;padding-top:0;color:var(--soft);font-size:14px}}
.weeks,.right-now,.paypal90{{margin-top:36px}} .right-now p .t-sub{{display:block}}
.wchart{{list-style:none;display:grid;grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);gap:2px;height:180px;padding:0;margin:12px 0 0}}
.wchart li{{display:grid;grid-template-rows:1fr auto;min-width:0}} .w-col{{display:flex;align-items:flex-end;border-bottom:1px solid var(--soft)}}
.w-bar{{display:block;width:100%;background:var(--pass);border-radius:4px 4px 0 0}} .wchart li:hover .w-bar{{opacity:.8}}
.wchart .so-far .w-bar{{background:repeating-linear-gradient(45deg,var(--pass) 0 3px,#E8F0EA 3px 6px)}}
.w-label{{font-size:13px;color:var(--soft);text-align:center;padding-top:6px}} .w-label b{{display:block;color:var(--ink);font-size:15px}}
@media (max-width:700px){{table.compare th,table.compare td{{padding:8px 6px;font-size:14px}}
  .xchart li{{grid-template-columns:1fr auto}} .xchart .x-label{{grid-column:1;grid-row:1}} .xchart b{{grid-column:2;grid-row:1}}
  .xchart .x-track{{grid-column:1/3;grid-row:2}} .xchart .t-sub{{grid-column:1/3;grid-row:3}}}}
/* states (spec 2026-10-30): one pill per state, the same on Today and on the case page */
.state-pill{{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:#fff;vertical-align:1px}}
.state-pill.your_move{{background:#B07A2A}} .state-pill.waiting_customer,.state-pill.waiting_paypal{{background:#3F5677}} .state-pill.done{{background:var(--pass)}}
.crumb{{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:14px;color:var(--soft);margin:0 0 14px}} .crumb a{{color:var(--ink)}}
.state-box{{background:#fff;border:1px solid var(--rule);padding:14px 18px;margin:0 0 18px}} .state-box p{{margin:0 0 6px}}
.done-line{{background:#E8F0EA;border-left:4px solid var(--pass);padding:12px 16px;margin:0 0 12px}} .done-line b{{display:block;color:var(--pass)}}
.demo-line{{font-size:13px;color:#6E4F27;background:var(--kraft-bg);padding:6px 12px;margin:0 0 12px}}
.band{{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--soft);margin:12px 0 4px}}
a.next{{display:block;background:var(--ink);color:#fff;font-weight:700;text-decoration:none;padding:10px 14px;margin:6px 0}}
details.fold{{margin-top:18px}} details.fold>summary{{cursor:pointer;color:var(--soft)}}
p.then{{background:#E8F0EA;margin:8px 0 0;padding:8px 12px;font-size:15px}} p.then b{{color:var(--pass)}}
section.bucket{{background:#fff;border:1px solid var(--rule);border-left:4px solid #3F5677;padding:14px 20px;margin-top:16px}}
section.bucket.done{{border-left-color:var(--pass)}}
@media (max-width:700px){{.needs-list li a{{grid-template-columns:1fr}} .needs-list .due{{white-space:normal}}}}
.toast{{background:#E8F0EA;border:1px solid #CFE3D4;padding:10px 16px;margin:0 0 14px}} .toast b{{color:var(--pass)}}
.api{{margin-top:40px}} .api code{{display:inline-block;background:#fff;border:1px solid var(--rule);padding:10px 14px;font-size:15px}}
@media (max-width:1100px){{.barlist li{{grid-template-columns:140px 1fr 32px}} .case{{grid-template-columns:minmax(0,1fr)}} .look{{border:0;padding:0}} main,header.top{{padding-left:20px;padding-right:20px}}}}
/* a phone: the header wraps (brand, shop, who you are, then the nav) instead of making every page scroll sideways */
@media (max-width:700px){{header.top{{flex-wrap:wrap;gap:12px 16px;padding:12px 16px}} main{{padding:24px 16px 60px}}
  .who-am-i{{flex-wrap:wrap;gap:10px 16px;min-width:0}} .shop{{padding-left:14px}} .brand small{{display:none}}
  header.top nav{{flex-wrap:wrap;gap:4px}} header.top nav a{{padding:6px 10px}} header.top nav .mode{{margin-left:0}}
  .shop-menu{{left:0;min-width:0;width:calc(100vw - 32px);max-width:300px}}
  .ev{{grid-template-columns:minmax(0,1fr) auto}} .ev dd:not(.tag){{grid-column:1/3}} .ev dd.tag{{grid-column:1/3;text-align:left}}
  .ruler .mark .lab{{width:120px}} .ruler .mark:first-child .lab{{transform:none;text-align:left}}
  .ruler .mark:last-child .lab{{transform:translateX(-100%);text-align:right}}}}
@media (prefers-reduced-motion:no-preference){{.verdict,.checks{{animation:in .5s ease-out}} @keyframes in{{from{{opacity:0}}}}}}
</style></head><body>
<header class="top {context}"><div class="who-am-i"><a class="brand" href="/today">{mark}Second Look<small>Sell without fear.</small></a>{shop}</div>{nav}</header>
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
    """`here`: the section the page belongs to ("today", "disputes", "numbers" or "rules"), said by the page itself.
    It used to be guessed from the title and the body's first characters, and a list page whose intro says
    "customer care" was marked Overview."""
    q = "?shop=demo" if demo else ""
    waiting = len(suggestions())
    rules = f'Your rules<span class="count">{waiting} to review</span>' if waiting else "Your rules"
    context = "demo" if demo else "practice" if mode.startswith("Practice") else "live"
    cur = lambda k: ' aria-current="page"' if here == k else ""  # noqa: E731
    nav = (f'<nav><a href="/today{q}"{cur("today")}>Today</a><a href="/{q}"{cur("disputes")}>Disputes</a>'
           f'<a href="/numbers{q}"{cur("numbers")}>Numbers</a>'
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
        raise RuntimeError("No PayPal keys in .env: this page needs the live sandbox, or open the demo shop.")
    now = datetime.utcnow()
    return (pp, _live_cached("disputes", lambda: evidence_mod.shop_disputes(pp, now)),
            _live_cached("orders", lambda: evidence_mod._orders(pp, now)), now.date())


def in_view(view: str, a: dict, me: str | None) -> bool:
    return view == "all" or (view == "mine" and a["to"] == me) or (view == "unassigned" and not a["to"])


def owner_tag(t: dict, a: dict) -> str:
    if not a["to"]:
        return "Unassigned"
    who = team_mod.person(t, a["to"])
    name = (who["name"] + (f', {who["role"]}' if who.get("role") else "")) if who else a["to"]
    hand = a.get("handoff")
    return name + (f' · passed by {hand.get("from_name")}' if isinstance(hand, dict) and hand.get("from_name") else "")


def inbox_page(src: str, me: str | None = None, view: str = "") -> str:
    close_quiet(src)
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


def exposure_box(ex: dict, high_volume: bool, cur: str = "EUR") -> str:
    """What the open PayPal disputes could cost: all won, ended like the last ones, all lost."""
    m = lambda v: f"{v:,.0f} {cur}"  # noqa: E731
    top = max(ex["all_lost"], 1)
    bars = [("If you win them all", ex["all_won"], "pass",
             "Nothing leaves your account." if not ex["all_won"] else "High-volume fee on every claim, even won."),
            (f"If they end like your last {ex['closed']} cases", ex["like_before"], "incon",
             f"{ex['share']:.0%} of the money disputed actually left your account." if ex["share"] is not None else "No closed cases yet to compare with."),
            ("If you lose them all", ex["all_lost"], "fail",
             f"Every refund, plus a {m(28 if high_volume else 14)} PayPal fee on each.")]
    chart = "".join(
        f'<li class="{cls}"><span class="x-label">{e(a)}</span><span class="x-track"><span class="x-bar" '
        f'style="width:{0 if v is None else max(0.4, 100 * v / top):.1f}%"></span></span>'
        f'<b>{"—" if v is None else e(m(v))}</b><span class="t-sub">{e(note)}</span></li>' for a, v, cls, note in bars)
    return (f'<section class="exposure"><h3>What the {ex["open"]} open PayPal disputes could cost</h3>'
            f'<p class="who">{m(ex["at_stake"])} in dispute. Money that would leave your account: refunds and '
            'PayPal dispute fees. When you refund, the goods and the postage are lost on top.</p>'
            f'<ul class="xchart">{chart}</ul></section>')


def paypal_block(ov: dict, cur: str = "EUR") -> str:
    """PayPal's own last 90 days, from its outcome codes: how the disputes ended."""
    m = lambda v: f"{v:,.0f} {cur}"  # noqa: E731
    c = ov["counts"]
    tiles = [("Handled", f'{ov["handled"]}', f'closed in the last {ov["window_days"]} days'),
             ("Settled before a claim", f'{ov["settled_before_claim"]} of {ov["handled"]}', "no PayPal dispute fee"),
             ("Money kept", m(ov["kept"]), "won, withdrawn, or closed with no claim"),
             ("Given back", m(ov["refunded"]), "refunds and accepted offers"),
             ("Dispute fees", m(ov["fees_paid"]), "estimated from PayPal's fee table")]
    kpis = "".join(f'<div class="tile"><span class="t-label">{e(a)}</span><b>{e(b)}</b><span class="t-sub">{e(x)}</span></div>'
                   for a, b, x in tiles)
    stayed = [(ledger.OUTCOME_LABEL[k], c[k]) for k in ("won", "withdrew", "closed") if c[k]]
    back = [(ledger.OUTCOME_LABEL[k], c[k]) for k in ("settled_offer", "refunded", "covered", "lost_claim", "lost_no_reply") if c[k]]
    return (f'<section class="paypal90"><h2>PayPal disputes, last {ov["window_days"]} days</h2>'
            f'<p class="who">{ov["disputes"]} disputes in {ov["orders"]:,} orders. From PayPal\'s own records: each '
            f'case\'s stage and outcome.</p><div class="kpis">{kpis}</div>'
            f'<h3 class="bl-h">The money stayed with you</h3>{bar_list(stayed, ov["handled"])}'
            f'<h3 class="bl-h">Money went back</h3>{bar_list(back, ov["handled"])}'
            f'<p class="cost-note">{ov["escalated"]} of {ov["handled"]} went past the inquiry to a PayPal claim.</p></section>')


def customer_page(key: str, src: str, me: str | None = None) -> str:
    demo = src == "demo"
    pp, disputes, orders, today = _shop(src)
    handled = (pp.raw.get("handled_by") or {}) if src == "demo" else {}
    cu = ledger.customer(key, disputes, orders, today) or own_customer(key, src)
    q = "?shop=demo" if demo else ""
    if not cu:
        return page("Customer | Second Look", "PayPal sandbox", '<h1 class="page">No customer with that id or email.</h1>', demo,
                    me=me, here="numbers")
    rate = (f'{len(cu["disputes"])} disputes in {cu["orders"]} orders ({cu["dispute_rate"]:.0%}). '
            f'Your shop: {cu["shop_dispute_rate"]:.1%}.' if cu["dispute_rate"] is not None else "")
    if cu["times_shop_rate"]:
        rate += f' {cu["times_shop_rate"]:.0f}× your usual rate.' if cu["times_shop_rate"] >= 2 else " About your usual rate."
    rows = "".join(f'<tr><td>{e(x["opened"])}</td><td><a href="/d/{e(x["dispute_id"])}">{e(x["reason"])}</a></td>'
                   f'<td>{x["amount"]:.2f}</td><td>{"PayPal claim" if x["escalated"] else "Inquiry"}</td>'
                   f'<td>{e(x["outcome"])}{(" · " + e(handled[x["dispute_id"]])) if x["dispute_id"] in handled else ""}</td></tr>'
                   for x in cu["disputes"])
    api = f'/api/customers/{cu["email"] or cu["payer_id"]}{q}'
    body = (f'<a class="back" href="/numbers{q}">Numbers</a><h1 class="page">{e(cu["name"] or cu["payer_id"])}</h1>'
            f'<p class="who">{e(cu["email"] or "")} · '
            + (f'PayPal payer {e(cu["payer_id"])}' if cu["payer_id"] else f'paid by {e(", ".join(cu.get("paid_with") or []))}')
            + '</p>'
            f'<div class="kpis">'
            f'<div class="tile"><span class="t-label">Orders</span><b>{cu["orders"]}</b><span class="t-sub">{cu["spent"]:,.2f} EUR, since {e(cu["first_order"] or "")}</span></div>'
            f'<div class="tile"><span class="t-label">Disputes</span><b>{len(cu["disputes"])}</b><span class="t-sub">{e(rate)}</span></div>'
            f'<div class="tile"><span class="t-label">Taken to a claim</span><b>{cu["escalated"]}</b><span class="t-sub">past the inquiry</span></div>'
            f'<div class="tile"><span class="t-label">Refunded</span><b>{cu["refunded"]:,.2f}</b><span class="t-sub">EUR</span></div></div>'
            f'<table class="waiting"><thead><tr><th>Opened</th><th>Case</th><th>Amount</th><th>Went to</th><th>Outcome</th></tr></thead>'
            f'<tbody>{rows or "<tr><td colspan=5>No disputes.</td></tr>"}</tbody></table>'
            f'<section class="api"><h2>In your customer database</h2><p class="who">Your CRM or helpdesk can ask for this card '
            f'when this customer orders or calls, by email or PayPal payer id:</p><code>GET {e(api)}</code></section>')
    return page(f"{cu['name'] or 'Customer'} | Second Look", "PayPal sandbox", body, demo, me=me, here="numbers")


def customer_json(key: str, src: str) -> dict | None:
    _, disputes, orders, today = _shop(src)
    return ledger.customer(key, disputes, orders, today) or own_customer(key, src)


# ---------- the shop's own systems as Second Look reads them: its orders, and its courier ----------
# In the demo both are made-up stand-ins (demo/shop.json), labelled so. On the live shop an order is PayPal's
# (Transaction Search) and its tracking PayPal's tracking API. The case's evidence reads the same records.
STAND_IN = "made-up stand-in (demo shop)"


def _raw_order(src: str, no: str | None) -> dict | None:
    key = (no or "").strip().lower()
    return next((o for o in shop_orders(src) if key and (sort_mod.order_no(o) or "").lower() == key), None) if key else None


def order_record(src: str, no: str | None) -> dict | None:
    """One order as the shop's orders system holds it: items, delivery address, how it was paid. None if unknown."""
    o = _raw_order(src, no)
    if o is None:
        return None
    v = sort_mod.order_view(o)
    return {"order_no": v["order_no"], "date": v["date"], "amount": v["amount"], "currency": v["currency"],
            "items": v["items"], "paid_with": v["paid_with"], "ship_to": v["ship_to"],
            "transaction_id": v["transaction_id"], "customer": {"name": v["name"], "email": v["email"]},
            "invoice_no": invoice_of(src, o),
            "source": f"Orders: {STAND_IN}" if src == "demo" else "Orders: PayPal Transaction Search"}


def tracking_record(src: str, no: str | None) -> dict | None:
    """The courier's record of an order: shipped, delivered, where, to whom, and a return on its way back. None if
    the order is unknown; {"tracking": None} if the courier holds nothing for it."""
    o = _raw_order(src, no)
    if o is None:
        return None
    tracking = o.get("tracking")
    if tracking is None and o.get("transaction_id"):
        if src == "demo":
            # a PayPal order's tracking, as the demo's PayPal holds it: only for the orders its disputes are about
            raw = DemoPayPal().raw
            did = next((d["dispute_id"] for d in raw["disputes"] if _tx_of(d) == o["transaction_id"]), None)
            tracking = (raw["records"].get(did) or {}).get("tracking") if did else None
        else:
            pp = client_from_env(ROOT)
            try:
                found = [] if isinstance(pp, MockPayPal) else evidence_mod._trackers(pp, o["transaction_id"])
            except RuntimeError:
                found = []
            tracking = found[-1] if found else None
    return {"order_no": sort_mod.order_no(o), "tracking": tracking, "return": o.get("return"),
            "source": f"Courier: {STAND_IN}" if src == "demo" else "Courier: PayPal tracking"}


def own_customer(key: str, src: str) -> dict | None:
    """A customer who paid the shop directly (card, bank) has no PayPal record: their record from the shop's own
    orders, in the shape the customer API gives for a PayPal customer. None when the shop has no such order."""
    k = (key or "").strip().lower()
    mine = [o for o in shop_orders(src) if not o.get("transaction_id") and (o.get("email") or "").strip().lower() == k]
    if not k or not mine:
        return None
    return {"payer_id": None, "name": mine[-1].get("name"), "email": mine[0].get("email"), "orders": len(mine),
            "spent": round(sum(_num(o.get("amount")) or 0 for o in mine), 2),
            "first_order": min(o.get("date") or "" for o in mine), "last_order": max(o.get("date") or "" for o in mine),
            "paid_with": sorted({str(o.get("paid_with") or "card") for o in mine}), "disputes": [], "escalated": 0,
            "refunded": 0.0, "dispute_rate": None, "shop_dispute_rate": None, "times_shop_rate": None,
            "escalations": "No PayPal disputes: paid the shop directly."}


# ---------- the books: every money event, live to the shop's bookkeeping and as a monthly CSV (secondlook/books.py) ----------

def resolve_unconfirmed(cid: str, request_id: str, refunded: bool, by: str | None) -> tuple:
    """A person checked PayPal about a refund it didn't confirm: it refunded it (a paid PayPal refund is recorded,
    as PayPal shows it) or it didn't (the mark goes). Only someone whose limit covers the amount says so."""
    if not cases_mod.is_case_id(cid):
        return 404, "No such case."
    store = case_store(shop_of_case(cid))
    c = store.get(cid)
    mark = next((x for x in (c or {}).get("unconfirmed", []) if x.get("request_id") == request_id), None)
    if mark is None:
        return 404, "No such refund waiting for PayPal's answer on this case."
    t = team_for(cid)
    who = team_mod.person(t, by)
    if not who:
        return 400, "Say who you are: a person in this shop's team."
    amount, cur = float(mark.get("amount") or 0), mark.get("currency") or "EUR"
    if not t.get("solo") and not team_mod.covers(t, who["id"], amount):
        return 403, (f"Saying what became of a refund of {amount:.2f} {cur} is for someone whose limit covers it "
                     "(the head of customer care).")
    with _case_lock(cid):
        def do(x):
            if not any(m.get("request_id") == request_id for m in x.get("unconfirmed", [])):
                raise ValueError("answered")
            x["unconfirmed"] = [m for m in x["unconfirmed"] if m.get("request_id") != request_id]
            now = cases_mod.minute(None)
            if refunded:
                x["money"].append({"kind": mark.get("kind") if mark.get("kind") in ("refund", "partial_refund") else "refund",
                                   "amount": amount, "currency": cur, "via": "PayPal refund API", "status": "paid",
                                   "paid_with": "paypal", "request_id": request_id, "at": mark.get("at") or now,
                                   "by": mark.get("by"), "reconciled_by": who["name"], "reconciled_at": now})
            x["timeline"].append(cases_mod.entry(None, reply_channel(x), "note",
                                                 f"PayPal {'refunded' if refunded else 'did not refund'} {amount:.2f} {cur} "
                                                 f"(checked by {who['name']}).", who["name"]))
        try:
            store.update(cid, do)
        except ValueError:
            return 409, "Someone has answered this already."
    if refunded:                                   # the refund PayPal made goes to the books, as it is now: paid
        _book_case_entry(shop_of_case(cid), cid, len(store.get(cid)["money"]) - 1)
    return 200, (f"Recorded: PayPal refunded {amount:.2f} {cur}." if refunded else "Recorded: PayPal did not refund it.")


def invoice_of(src: str, o: dict | None) -> str | None:
    """The invoice number of an order: the shop's own when its orders system has one. In the demo, a made-up stand-in
    number from the order's digits; the live shop's PayPal orders carry none (the accounting system knows it)."""
    if not o:
        return None
    if o.get("invoice_no"):
        return str(o["invoice_no"])
    digits = "".join(ch for ch in str(sort_mod.order_no(o) or "") if ch.isdigit())
    return f"LP-INV-{digits}" if src == "demo" and digits else None


def post_books(event) -> None:
    """Second Look -> the shop's bookkeeping: POST one money event as JSON to SECONDLOOK_BOOKS_URL (Bookbox in the demo,
    a made-up stand-in). Never blocks or breaks the person's action; a failure is logged, like notify(). `event` is
    the row, or a function that makes it (in the background too: reading the shop's orders may call PayPal)."""
    from urllib import request as rq
    url = os.environ.get("SECONDLOOK_BOOKS_URL")
    if not url:
        return
    root = ROOT

    def send(before):
        if before is not None:
            before.join()                                   # in the order they happened
        what = None
        try:
            row = event() if callable(event) else event
            what = row.get("case_id") or row.get("dispute_id")
            body = json.dumps({"event": "money", **row}, ensure_ascii=False, default=str).encode()
            rq.urlopen(rq.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"}), timeout=5)
        except Exception as err:  # noqa: BLE001 - the books hear later from the CSV; the answer stands
            why = str(err).replace(url, "the books address").split("?key=")[0]     # never the address or its key
            (root / ".tmp").mkdir(exist_ok=True)
            with open(root / ".tmp" / "books.log", "a") as f:
                f.write(f"{datetime.utcnow():%Y-%m-%d %H:%M} money {what}: {why}\n")
    # in the background: an approval (under its case's lock) never waits on the bookkeeping
    with _BOOKS_LOCK:
        alive = [x for x in _BOOKS_POSTS if x.is_alive()]
        t = threading.Thread(target=send, args=(alive[-1] if alive else None,), daemon=True)
        _BOOKS_POSTS[:] = alive + [t]
        t.start()


_BOOKS_POSTS: list = []
_BOOKS_LOCK = threading.Lock()


def books_flush(timeout: float = 10.0) -> None:
    """Wait for the bookkeeping posts still on their way (tests, and a server that is stopping)."""
    with _BOOKS_LOCK:
        posts = list(_BOOKS_POSTS)
    for t in posts:
        t.join(timeout)


def _dispute_refund_row(did: str, d: dict, at: str, amount: float, cur: str, by: str) -> dict:
    """The books row of a refund approved on a PayPal dispute: its order (the dispute's transaction), the order's
    invoice number (the demo's stand-in; a live PayPal order holds none: "" = not on record), where the item is,
    and the case it belongs to. Read only: the case it joined, or the open case on its order that nothing has
    linked yet (as the morning screen finds it); no case is made or linked here."""
    src, tx = shop_of_case(did), _tx_of(d) or ""
    orders = shop_orders(src) if tx else []
    o = next((x for x in orders if x.get("transaction_id") == tx), None)
    path = CASE_FILES[src]
    cases = cases_mod.CaseStore(path).all() if tx and path.exists() else []
    c = today_mod.links(cases, [d], orders).get(did) if tx else find_case_of_dispute(did)
    view = sort_mod.order_view(o) if o else None
    item = books_mod.item_state((c.get("problem") or {}).get("kind"), view) if c else books_mod.dispute_item(d.get("reason"), view)
    return {"date": at, "kind": "PayPal refund", "order_no": tx, "invoice_no": invoice_of(src, o) or "",
            "amount": amount, "currency": cur, "fees": 0.0, "item": item, "approved_by": by, "channel": "paypal",
            "case_id": (c or {}).get("id") or "", "dispute_id": did, "status": "sent to PayPal"}


def _book_case_entry(src: str, cid: str, index: int) -> None:
    """Post the books row of one money entry of a case, as it is now (logged, paid, cancelled)."""
    c = case_store(src).get(cid)
    o = _raw_order(src, c.get("order_no")) if c else None
    rows = books_mod.case_events(c, sort_mod.order_view(o) if o else None, invoice_of(src, o)) if c else []
    money = [m for m in c.get("money", []) if books_mod.KIND.get(m.get("kind"))] if c else []
    if 0 <= index < len(c.get("money", [])) and c["money"][index] in money:
        post_books(rows[money.index(c["money"][index])])


def books_rows(src: str) -> list:
    """Every money event of the shop: its cases' (the demo's earlier cases included) and PayPal's resolved disputes'."""
    orders = {sort_mod.order_no(o): o for o in shop_orders(src)}
    rows = []
    for c in shop_cases(src):
        o = orders.get(c.get("order_no"))
        rows += books_mod.case_events(c, sort_mod.order_view(o) if o else None, invoice_of(src, o))
    demo = src == "demo"
    handled = (DemoPayPal().raw.get("handled_by") or {}) if demo else {}
    disputes = shop_disputes(src)
    today = DemoPayPal().today if demo else datetime.utcnow().date()
    hv = ledger.overview(disputes, list(orders.values()), today)["high_volume"]["high_volume"] if disputes else False
    by_tx = {o.get("transaction_id"): o for o in orders.values() if o.get("transaction_id")}
    for d in disputes:
        rows += books_mod.dispute_events(d, invoice_of(src, by_tx.get(_tx_of(d))), handled.get(d["dispute_id"]), hv)
    return rows


RECONCILE = {"paid": "paid", "cancelled": "cancelled"}
PAID_WITH = {"card": "by card", "bank": "by bank transfer", "paypal": "through PayPal"}


def reconcile(cid: str, index, outcome: str, paid_with: str | None, by: str | None) -> tuple:
    """A person says what became of a refund logged on a case: paid (by card, bank or PayPal), or cancelled (it never
    went out). Paid: the money holds stay (it went back), and a later PayPal dispute on the order may be defended
    with the refund as proof. Cancelled: it counts nowhere any more, so the order's money holds lift by that amount.
    Once per refund: what the books were told is never rewritten. Returns (HTTP status, what happened)."""
    if not cases_mod.is_case_id(cid):
        return 404, "No such case."
    store = case_store(shop_of_case(cid))
    c = store.get(cid)
    if c is None:
        return 404, "No such case."
    try:
        i = int(index)
    except (TypeError, ValueError):
        return 400, "Which refund: its number on the case."
    money = c.get("money", [])
    if not 0 <= i < len(money) or money[i].get("kind") not in ("refund", "partial_refund"):
        return 400, "Only a refund logged on this case can be marked paid or cancelled."
    if outcome not in RECONCILE:
        return 400, "Mark it paid or cancelled."
    if outcome == "paid" and paid_with not in PAID_WITH:
        return 400, f"Paid how: {', '.join(PAID_WITH)}."
    t = team_for(cid)
    who = team_mod.person(t, by)
    if not who:
        return 400, "Say who you are: a person in this shop's team."
    if outcome == "cancelled":
        if money[i].get("refund_id") or money[i].get("via") == "PayPal refund API":
            return 409, ("This refund went through PayPal: it can only be marked paid. If PayPal didn't pay it, "
                         "check the payment in PayPal.")
        amount = float(money[i].get("amount") or 0)
        if not t.get("solo") and not team_mod.covers(t, who["id"], amount):
            return 403, (f"Cancelling a refund of {amount:.2f} is for someone whose limit covers it "
                         "(the head of customer care): cancelled, it no longer holds anything back.")
    with _case_lock(cid):
        def mark(x):
            m = x["money"][i]
            if m.get("status") in ("paid", "cancelled"):
                raise ValueError(m["status"])
            m.update(status=outcome, reconciled_by=who["name"], reconciled_at=cases_mod.minute(None),
                     **({"paid_with": paid_with} if outcome == "paid" else {}))
            words = (f"paid {PAID_WITH[paid_with]}" if outcome == "paid" else "cancelled: it never went out")
            x["timeline"].append(cases_mod.entry(None, reply_channel(x), "note",
                                                 f"Refund of {float(m['amount']):.2f} marked {words} by {who['name']}.", who["name"]))
        try:
            store.update(cid, mark)
        except ValueError as err:
            return 409, f"This refund is marked {err} already."
    _book_case_entry(shop_of_case(cid), cid, i)
    return 200, ("Marked paid." if outcome == "paid" else "Marked cancelled: it no longer counts as money that went back.")


def money_block(v: dict, me: str | None) -> str:
    """The case's money: each refund, replacement and fee logged on it, and, on a refund still only logged, the two
    things a person can say about it afterwards (paid, cancelled)."""
    c, cur = v["case"], v["currency"]
    rows = []
    by = f'<input type="hidden" name="by" value="{e(me)}">' if me else ""
    for i, m in enumerate(c.get("money", [])):
        kind = books_mod.KIND.get(m.get("kind"))
        if not kind:
            continue
        status = m.get("status") or "logged"
        line = (f'<b>{e(kind.capitalize())} {float(m.get("amount") or 0):.2f} {e(m.get("currency") or cur)}</b> · {e(str(m.get("by") or ""))} · '
                f'{e(_when(m.get("at") or ""))} · {e(status)}'
                + (f' {e(PAID_WITH.get(m.get("paid_with"), ""))}' if status == "paid" else "")
                + (f' · {e(m["via"])}' if m.get("via") else ""))
        form = ""
        if m.get("kind") in ("refund", "partial_refund") and status in ("logged", "sent to PayPal"):
            opts = "".join(f'<option value="{k}">{e(v_)}</option>' for k, v_ in PAID_WITH.items())
            # a refund PayPal made can only be marked paid (reconcile refuses to cancel it): no cancel button for it
            through_paypal = bool(m.get("refund_id")) or m.get("via") == "PayPal refund API"
            form = (f'<form class="pick" method="post" action="/c/{e(c["id"])}/money">{by}'
                    f'<input type="hidden" name="i" value="{i}"><select name="paid_with" aria-label="Paid how">{opts}</select>'
                    '<div class="approve"><button class="quiet" name="outcome" value="paid">Mark paid</button>'
                    + ('' if through_paypal else
                       '<button class="quiet" name="outcome" value="cancelled">It never went out: cancel</button>')
                    + '</div></form>')
        rows.append(f'<li>{line}{form}</li>')
    if not rows:
        return ""
    return f'<section class="costs"><h2>Money on this case</h2><ul class="see">{"".join(rows)}</ul></section>'


# ---------- the morning screen: "I see, I manage, I know" (secondlook/today.py does the counting) ----------

def shop_cases(src: str) -> list:
    """Every case of a shop the morning screen counts: its case file (the demo's seeded on first read), and, for
    the demo shop, the closed cases of the weeks before this morning, from demo/shop.json ("history", read only)."""
    cases = case_store(src).all() if src in CASE_FILES else []
    return cases + (DemoPayPal().history() if src == "demo" else [])


def review_line(did: str, ap_cases: dict | None = None) -> dict:
    """What Second Look recommends on a case, in one line, and who said it: "ai" (Second Look's AI: Claude, here or
    ahead of time), "rules" (the rules baseline, no AI key), or None (not reviewed yet, or already answered). An
    answer Second Look's AI sent on its own says so; a step back says why. `ap_cases`: its record's cases, read once
    by a page that shows many rows."""
    saved = _saved(did)
    if ap_cases is None:
        ap_cases = autopilot_store(shop_of_case(did)).view()["cases"]
    ap = ap_cases.get(did) or {}
    back = f" · Second Look's AI stepped back: {ap['why']}" if ap.get("why") and not ap.get("handled") else ""
    if not saved:
        return {"by": None, "text": "Not reviewed yet" + back}
    dec, sent = saved
    w = _words(did)
    if sent:
        first = sent.split(". ")[0].rstrip(".")
        if str(_saved_by(did).get("by") or "").startswith(autopilot_mod.AI_NAME):
            later = f" · then it stepped back: {ap['later']['why']}" if (ap.get("later") or {}).get("why") else ""
            return {"by": None, "text": "Handled by Second Look's AI · " + first[:1].lower() + first[1:] + later}
        return {"by": None, "text": "Answered: " + first}
    text = w["action"].get(dec.action, dec.action)
    j = dec.judgment
    if dec.overridden and j.action != dec.action and j.action in w["action"]:
        text += f' (your limits held back: {w["action"][j.action].lower()})'
    return {"by": "rules" if judge_of(did) == "rules" else "ai", "text": text + back}


def sent_answers(src: str) -> list:
    """When each answer to one of this shop's PayPal disputes was sent from Second Look (its saved review's `at`).
    An inquiry's answers are on its case's timeline already, so they are not counted here twice."""
    out = []
    for f in sorted(REVIEWS.glob("*.json")) if REVIEWS.exists() else []:
        did = f.stem
        if cases_mod.is_case_id(did) or is_demo(did) != (src == "demo") or did.startswith("PP-D-"):
            continue
        raw = _raw(did) or {}
        if raw.get("sent") and raw.get("at"):
            out.append(_utc_minute(raw["at"]))
    return out


def _utc_minute(at) -> str:
    """A review's `at` (an approval's local time, as it is shown: "Sent by Giulia, 11:47") in UTC, as every other
    time here is ("2026-10-19T08:52"); one with its own offset is converted from it."""
    try:
        t = datetime.fromisoformat(str(at)[:25])
    except ValueError:
        return cases_mod.minute(at)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")


def today_view(src: str, me: str | None = None) -> dict:
    """The morning screen as data (the page and GET /api/today show the same): what needs `me` (today.needs_you), what
    came in since yesterday (each row says who has it), who has what. The figures are on Numbers (numbers_view)."""
    demo = src == "demo"
    today = shop_today(src)
    waiting, failed = 0, []
    if CALL_BOXES.get(src):
        file_calls(case_store(src), src)              # a call left in the box since the last look comes in now
        waiting = calls_waiting(case_store(src), src) if transcriber_on() else 0
        failed = calls_failed(case_store(src), src)
    close_quiet(src)                                  # after the calls: one waiting in the box keeps its case open
    cases, disputes, orders = shop_cases(src), shop_disputes(src), shop_orders(src)
    t = team_for_src(src)
    solo = bool(t.get("solo"))
    who = None if solo else team_mod.person(t, me)
    head = solo or (who is not None and team_mod.limit(t, who["id"]) is None)
    assigned = {} if solo else assignments_for("DEMO-" if demo else None).all()
    rec = autopilot_store(src).view()           # Second Look's AI's record, read once for every row
    see = today_mod.came_in(cases, disputes, orders, today, review_of=lambda did: review_line(did, rec["cases"]))
    if not solo:
        names = {p["id"]: p.get("name") or p["id"] for p in team_mod.people(t)}
        for r in see["rows"]:
            r["has"] = names.get((assigned.get(r["decision_id"]) or {}).get("to"))
    items = today_mod.open_items(cases, disputes, orders, today)
    dmap = {d["dispute_id"]: d for d in disputes}
    held, cmap = today_mod.links(cases, disputes, orders), {c["id"]: c for c in cases}
    states = {it["id"]: case_state(it["id"], dmap.get(it["id"]),
                                   held.get(it["id"]) or cmap.get(it["id"]) or (NO_CASE if it["id"] in dmap else None),
                                   today=today)
              for it in items}
    for r in see["rows"]:
        r["state"] = states.get(r["decision_id"])     # None: a closed or history case, nobody's move to alarm about
    handled = autopilot_handled(src, today, rec)
    # Needs you: every answer nobody checked yet, however old (the since-yesterday list is the API's "autopilot")
    every_ai = autopilot_handled(src, today, rec, since=False)
    unchecked = [h for h in every_ai if not h.get("checked")]
    for h in handled + unchecked:
        h["closes"] = _closes_words(case_store(src).get(h["id"]) if cases_mod.is_case_id(h["id"]) else None)
    hv = ledger.overview(disputes, orders, today)["high_volume"]
    ai_ids = {h["id"] for h in every_ai}
    me_id = who["id"] if who else None
    buckets = today_mod.waiting(me_id, head, items, assigned, t, states, ai_ids, skip={h["id"] for h in unchecked})
    in_done = {x["id"] for x in buckets["done"]}
    buckets["done"] += today_mod.closed_today(
        cases, orders, today,
        lambda i: i not in in_done and (solo or (assigned.get(i) or {}).get("to") == me_id or (head and i in ai_ids)))
    # today you handled: the answers this person sent today (the computer's day: the demo's clicks are real), at the
    # shop's reply minutes each, the same estimate as a case's cost
    name = (who or {}).get("name")
    day, sent_today = _local_now().date().isoformat(), set()
    for i in [*states, *(x["id"] for x in buckets["done"])]:
        raw = _raw(i) or {}
        by = raw.get("by")
        if (raw.get("sent") and str(raw.get("at") or "")[:10] == day
                and not str(by or "").startswith(autopilot_mod.AI_NAME) and (solo or (name and by == name))):
            sent_today.add(i)
    handled_n = len(sent_today)
    return {"today": today, "team": t, "head": head, "phone": bool(CALL_BOXES.get(src)), "calls_pending": waiting,
            "calls_failed": failed, "see": see,
            "needs": today_mod.needs_you(who["id"] if who else None, head, items, assigned, t, unchecked, failed, hv, states=states),
            "waiting": buckets,
            "handled": {"cases": handled_n, "minutes": handled_n * cases_mod.staff_time(_policy())["reply_minutes"]},
            "manage": today_mod.who_has(items, assigned, t),
            "autopilot": {"handled": handled,
                          "on": [kind_words(k) for k, x in rec["kinds"].items()
                                 if x.get("on") and autopilot_mod.split_kind(k)[0] in autopilot_mod.SWITCHABLE]}}


def _hours(minutes: float) -> str:
    h, mm = divmod(int(round(minutes)), 60)
    return f"{h} h {mm} min" if h else f"{mm} min"


def records_from(src: str):
    """The first day this shop's own records cover: a period before it has no record, never a zero. The demo's history
    begins on 1 Sep 2026 (demo/shop.json "records_from"); a live shop's on its first case's day; None: no case yet."""
    if src == "demo":
        return datetime.strptime(DemoPayPal().shop["records_from"], "%Y-%m-%d").date()
    days = [c["opened"][:10] for c in case_store(src).all() if c.get("opened")] if src in CASE_FILES else []
    return datetime.strptime(min(days), "%Y-%m-%d").date() if days else None


def numbers_view(src: str, by: str = "month") -> dict:
    """Numbers, as data: this week or month so far beside the same days of the one before (like for like; None before
    the shop's records begin), the weeks on record, this month with what holds right now (today.month), and PayPal's
    own last 90 days. One counting function for every period (today.period)."""
    by = by if by in ("week", "month") else "month"
    close_quiet(src)
    today = shop_today(src)
    cases, disputes, orders = shop_cases(src), shop_disputes(src), shop_orders(src)
    pol, answers, cur = _policy(), sent_answers(src), "EUR"
    since = records_from(src)

    def flows(first, last, current, fees=True):
        # PayPal's line as it stood at the period's end sets its fee; the week bars count requests only
        hv = fees and ledger.overview(disputes, orders, last, cur)["high_volume"]["high_volume"]
        return today_mod.period(cases, disputes, orders, f"{first.isoformat()}T00:00",
                                None if current else f"{(last + timedelta(days=1)).isoformat()}T00:00",
                                pol, answers, bool(hv), cur)
    (a0, a1), (b0, b1) = today_mod.windows(today, by)
    weeks = []
    for first, last in today_mod.weeks(today):
        if since is None or first < since:
            continue
        f = flows(first, last, last == today, fees=False)
        weeks.append({"first": first, "last": last, "so_far": (last - first).days < 6,
                      "requests": f["requests"], "orders": f["orders"]})
    ov = ledger.overview(disputes, orders, today, cur)
    return {"by": by, "today": today, "records_from": since,
            "this": {"first": a0, "last": a1, **flows(a0, a1, True)},
            "before": {"first": b0, "last": b1, **flows(b0, b1, False)} if since and b0 >= since else None,
            "weeks": weeks, "month": today_mod.month(cases, disputes, orders, today, pol, answers, cur),
            "paypal": ov, "exposure": ledger.exposure(disputes, today, ov["high_volume"]["high_volume"], cur)}


# Numbers: each flow, its kind of figure, and what it counts.
NUMBERS = [("Orders", "orders", "n", "the shop's sales, for scale"),
           ("Requests, every channel", "requests", "n", "emails, web forms, calls and PayPal disputes, each problem once"),
           ("Solved before any PayPal dispute", "solved_before_dispute", "n", "shop requests closed"),
           ("Answered by Second Look's AI on its own", "ai_answered", "n", "under your setting, signed"),
           ("Staff time", "minutes", "min", "estimated: each written answer at your minutes, a call its own length"),
           ("Money given back", "back", "money", "refunds logged on your cases, and PayPal's"),
           ("PayPal dispute fees", "fees", "money", "estimated from PayPal's fee table")]


def _fmt(v, kind: str, cur: str) -> str:
    return f"{v:,.2f} {cur}" if kind == "money" else _hours(v) if kind == "min" else f"{v:,}"


def _change(a, b, kind: str, cur: str) -> str:
    """This period against the one before: "+2", "−19.50 EUR", "+30 min", or "same". Minutes are compared whole, as
    the cells show them (_hours): never "+0 min"."""
    if kind == "min":
        a, b = round(a), round(b)
    d = a - b
    if abs(d) < 0.005:
        return "same"
    sign = "+" if d > 0 else "−"
    return sign + (f"{abs(d):,.2f} {cur}" if kind == "money" else _hours(abs(d)) if kind == "min" else f"{abs(d):,.0f}")


def _span(a, b) -> str:
    """Days, inclusive: "1–20 Oct", "28 Sep–4 Oct"."""
    return f"{a.day}–{b.day} {b:%b}" if (a.year, a.month) == (b.year, b.month) else f"{a.day} {a:%b}–{b.day} {b:%b}"


def export_link(today, q: str = "") -> str:
    """The facts for the accountant, this month: every money event, with order, invoice, item, who and channel."""
    return (f'<p class="cardlink"><a class="export" href="/books.csv?month={today:%Y-%m}{"&" + q[1:] if q else ""}">'
            f'Export for accounting (CSV, {today:%B %Y})</a> <span class="t-sub">the facts, never a credit note</span></p>')


def weeks_chart(weeks: list) -> str:
    """Requests, week by week, from the first week on record: one bar each, this week so far striped."""
    if not weeks:
        return ""
    top = max(w["requests"] for w in weeks) or 1
    bars = "".join(
        f'<li class="{"so-far" if w["so_far"] else ""}" title="Week of {w["first"].day} {w["first"]:%b}: '
        f'{w["requests"]} requests in {w["orders"]:,} orders{" (so far)" if w["so_far"] else ""}">'
        f'<span class="w-col"><span class="w-bar" style="height:{max(1.5, 100 * w["requests"] / top):.1f}%"></span></span>'
        f'<span class="w-label">{w["first"].day} {w["first"]:%b}<b>{w["requests"]}</b></span></li>' for w in weeks)
    first = weeks[0]["first"]
    return (f'<section class="weeks"><h2>Requests, week by week</h2><p class="t-sub">Monday to Sunday, the weeks on '
            f'record (from {first.day} {first:%b}). This week so far is striped.</p><ol class="wchart">{bars}</ol></section>')


def numbers_page(src: str, me: str | None = None, by: str = "month") -> str:
    """Numbers: every figure beside the same days of the period before (like for like), the weeks on record, what holds
    right now (no comparison: a snapshot), and PayPal's own last 90 days. Replaces the Overview (Claudia, 27/10:
    "benchmark weeks on weeks or months on months: better a dedicated space")."""
    demo = src == "demo"
    v = numbers_view(src, by)
    q, amp = ("?shop=demo", "&shop=demo") if demo else ("", "")
    k, a, b = v["month"], v["this"], v["before"]
    cur = k["currency"]
    if v["by"] == "week":
        now_words = f"This week so far ({_span(a['first'], a['last'])})"
        then_words = f"the same days last week ({_span(b['first'], b['last'])})" if b else "last week"
    else:
        now_words = f"{a['first']:%B} so far ({_span(a['first'], a['last'])})"
        then_words = (f"the same days of {b['first']:%B} ({_span(b['first'], b['last'])})" if b
                      else "the month before")
    here = ' aria-current="page"'
    tabs = "".join(f'<a href="/numbers?by={key}{amp}"{here if v["by"] == key else ""}>{label}</a>'
                   for key, label in (("week", "This week"), ("month", "This month")))
    rows = []
    for label, key, kind, note in NUMBERS:
        before, change = ((_fmt(b[key], kind, cur), _change(a[key], b[key], kind, cur)) if b else ("no record yet", ""))
        rows.append(f'<tr><th scope="row">{e(label)}<span class="t-sub">{e(note)}</span></th>'
                    f'<td>{e(_fmt(a[key], kind, cur))}</td><td>{e(before)}</td><td>{e(change)}</td></tr>')
        if key == "requests":
            per = lambda x: f'{100 * x["requests"] / x["orders"]:.1f}' if x["orders"] else "—"  # noqa: E731
            rows.append(f'<tr class="sub"><th scope="row">per 100 orders</th><td>{per(a)}</td>'
                        f'<td>{per(b) if b else ""}</td><td></td></tr>')
    then_head = _span(b["first"], b["last"]) if b else "Before"
    table = (f'<table class="compare"><thead><tr><th scope="col"></th><th scope="col">{e(_span(a["first"], a["last"]))}</th>'
             f'<th scope="col">{e(then_head)}</th><th scope="col">Change</th></tr></thead><tbody>{"".join(rows)}</tbody></table>')
    right_now = (f'<section class="right-now"><h2>Right now</h2><p class="t-sub">A snapshot: what holds today, so '
                 f'nothing to compare it with.</p><p><b>Open cases could still cost at most {k["could_still_cost"]:,.2f} '
                 f'{e(cur)}</b><span class="t-sub">every open PayPal dispute lost at claim ({k["open_disputes_most"]:,.2f} '
                 f'{e(cur)}) and every open request refunded in full ({k["open_inquiries_most"]:,.2f} {e(cur)})</span></p>'
                 f'{exposure_box(v["exposure"], v["paypal"]["high_volume"]["high_volume"], cur)}'
                 f'{claim_line_box(k["high_volume"], v["today"], cur)}</section>')
    about = f'<p class="demo-note">{e(DemoPayPal().shop["about"])}</p>' if demo else ""
    body = (f'<h1 class="page">Numbers</h1>{about}<p class="tabs">{tabs}</p>'
            f'<h2>{e(now_words)} against {e(then_words)}</h2>{table}{both_sides_note(k)}'
            f'{weeks_chart(v["weeks"])}{right_now}{paypal_block(v["paypal"], cur)}'
            f'{export_link(v["today"], q)}<p class="cardlink">The open cases, one by one: '
            f'<a href="/{q}">Disputes and requests</a> · <a href="/api/numbers{q}">these numbers as data (API)</a></p>')
    return page("Numbers | Second Look", "PayPal sandbox", body, demo, me=me, here="numbers")


def claim_line_box(hv: dict, today, cur: str = "EUR") -> str:
    """PayPal's high-volume line, as Numbers shows it: claims and card chargebacks against sales over PayPal's
    own window (the three previous full months), with the 1.5% line."""
    start, end = ledger.quarter_window(today)
    meter_w = min(100, 100 * hv["ratio"] / 0.02) if hv["sales"] else 0
    return (f'<section class="meter-box"><h2>PayPal\'s high-volume line</h2>'
            f'<p class="who">Claims and card chargebacks against sales, {start:%b}–'
            f'{(end - timedelta(days=1)):%b %Y} (PayPal counts the three previous full months). '
            f'At 1.5% with more than 100 sales, every claim costs {28:,.0f} {cur}, even the ones you win.</p>'
            f'<div class="meter" role="img" aria-label="{hv["ratio"]:.2%} of sales, line at 1.5%">'
            f'<span class="m-fill" style="width:{meter_w:.1f}%"></span><span class="m-line" style="left:75%"><i>1.5%</i></span></div>'
            f'<p><b>{hv["claims"]} claims in {hv["sales"]:,} sales: {hv["ratio"]:.2%}.</b> '
            + ("Above the line." if hv["high_volume"] else f'{hv["claims_to_threshold"]} more claims this quarter and you cross it.')
            + '</p></section>')


def both_sides_note(k: dict) -> str:
    both = k.get("both_sides") or []
    return (f'<p class="check-sender">{len(both)} order{"s" if len(both) != 1 else ""} counted on both sides: check '
            f'{"it was" if len(both) == 1 else "they were"} paid once ({e(", ".join(both))}): a refund logged on a case, '
            'and PayPal\'s.</p>' if both else "")


def _rec(r: dict | None) -> str:
    if not r:
        return ""
    tag = ('<span class="ai-tag">Second Look\'s AI</span>' if r["by"] == "ai" else
           '<span class="ai-tag rules">Rules baseline</span>' if r["by"] == "rules" else "")
    return f'<span class="rec">{tag} {e(r["text"])}</span>'


def see_block(s: dict, q: str, phone: bool = False, pending: int = 0) -> str:
    """New since yesterday: one line per problem, every channel, nearest PayPal deadline first, each saying who has it
    (in a team) and what Second Look recommends."""
    chips = []
    if pending:      # recordings local whisper is still on: they come in once it has their words
        chips.append(f'<span class="chip off">📞 {pending} call{"s" if pending != 1 else ""} being transcribed</span>')
    for ch, word, n in today_mod.channel_words(s["counts"]):
        if ch == "paypal" and s.get("paypal_messages"):
            word = "PayPal disputes or new PayPal messages"     # it counts a buyer's new message on an older one too
        if ch == "call" and not phone:
            chips.append('<span class="chip off">📞 Phone: not connected yet</span>')
            continue
        chips.append(f'<span class="chip">{e(cases_mod.CHANNEL_ICON[ch])} {n} {e(word)}</span>')
    rows = []
    for r in s["rows"]:
        icons = " ".join(cases_mod.CHANNEL_ICON[ch] for ch in r["channels"])
        left = r["days_left"]
        when = ("no PayPal deadline" if left is None else "overdue" if left < 0 else "today" if left == 0
                else f"{left} day{'s' if left != 1 else ''} left")
        due = f'<span class="due{" soft" if left is None else ""}">{e(when)}</span>'
        order = f' · order {e(r["order_no"])}' if r["order_no"] else " · no order"
        # who has it; none on a row Second Look's AI answered on its own (its line says so): never a false alarm
        handled = ((r.get("review") or {}).get("text") or "").startswith("Handled by Second Look's AI")
        mine = (r.get("state") or {}).get("state") in (None, "your_move")    # not taken yet is no alarm on a wait
        has = ("" if "has" not in r or handled else f'<span class="has">{e(r["has"])} has it</span>' if r["has"]
               else '<span class="has none">not taken yet</span>' if mine else "")
        rows.append(f'<li><a href="{e(r["link"])}{q}"><span class="chan">{e(icons)}</span>'
                    f'<span class="what"><b>{e(r["who"] or "")}</b>, <i>customer</i> · '
                    # the customer's own words, or Second Look's AI's reading of them: never one for the other
                    + (f'Second Look\'s AI reads this as: {e(r["summary"])}' if r.get("summary_by") == "ai"
                       else e(r["summary"]) if r.get("summary_by") == "call"
                       else f'they wrote: “{e(r["summary"])}”')
                    + f' · {r["amount"]:.2f} {e(r.get("currency") or "EUR")}{order}{" · closed" if r["status"] != "open" else ""}'
                    f'{has}{_rec(r["review"])}</span>{due}</a></li>')
    listing = (f'<ol class="see">{"".join(rows)}</ol>' if rows else
               '<p class="empty">Nothing new since yesterday.</p>')
    return (f'<h2>New since yesterday · {len(s["rows"])}</h2><p class="t-sub">From every channel, nearest PayPal '
            f'deadline first</p><p class="chips">{"".join(chips)}</p>{listing}')


def needs_block(needs: list, q: str, me: str | None, src: str, solo: bool = False) -> str:
    """The morning screen's first block: what needs this person (today.needs_you), or that nothing does (a seller on
    their own has no team to hand the rest to)."""
    if not needs:
        return ('<section class="needs calm"><h2>Nothing needs you</h2>'
                + ('' if solo else '<p class="t-sub">Your team has the rest.</p>') + '</section>')
    rows, ai = [], [n for n in needs if n["kind"] == "ai"]
    for n in needs:
        if n["kind"] == "case":
            left = n.get("days_left")
            when = ("no PayPal deadline" if left is None else "overdue" if left < 0 else "today" if left == 0
                    else f"{left} day{'s' if left != 1 else ''} left")
            why = (f'passed to you by {e(n["from_name"])}' + (f', <i>{e(n["from_role"])}</i>' if n.get("from_role") else "")
                   if n.get("from_name") else "yours")
            rows.append(f'<li><a href="{e(n["link"])}{q}"><span class="what"><b>{e(n["who"] or "")}</b>, <i>customer</i>'
                        f' · {e(n["summary"])} · {n["amount"]:.2f} {e(n.get("currency") or "EUR")}'
                        f'<span class="t-sub">{why}</span></span>'
                        f'<span class="due{" soft" if left is None else ""}">{e(when)}</span></a></li>')
        elif n["kind"] == "calls":
            w = n["wavs"]
            rows.append(f'<li><span class="what">📞 {len(w)} call{"s" if len(w) != 1 else ""} couldn\'t be transcribed: '
                        f'listen to {"it" if len(w) == 1 else "them"} ({e(", ".join(w))})</span></li>')
        elif n["kind"] == "ai":
            if n is ai[0]:
                rows.append(f'<li class="ai-head">Second Look\'s AI answered {len(ai)} on its own: '
                            f'check {"it" if len(ai) == 1 else "them"}</li>')
            rows.append(f'<li class="ai-check"><a href="{e(n["link"])}{q}"><span class="what"><b>{e(n["who"] or "")}</b>, '
                        f'<i>customer</i> · {e(n["kind_words"])}<span class="t-sub">{e(n["what"])}'
                        + (f' · {e(n["closes"])}' if n.get("closes") else "") + '</span></span></a>'
                        f'{ai_check_form(src, n["id"], me, "/today")}</li>')
        elif n["kind"] == "line":
            rows.append(f'<li><span class="what"><b>PayPal\'s high-volume line</b> · {n["claims"]} claims in '
                        f'{n["sales"]:,} sales: {n["ratio"]:.2%}. '
                        + ("Above the line: every claim costs 28 EUR, even the ones you win." if n["high_volume"]
                           else f'{n["claims_to_threshold"]} more claims this quarter and you cross it.')
                        + f' <a href="/numbers{q}">Numbers</a></span></li>')
    return f'<section class="needs"><h2>Needs you · {len(needs)}</h2><ul class="needs-list">{"".join(rows)}</ul></section>'


def team_block(mg: dict, head: bool, q: str) -> str:
    """For the head of customer care: one line, each person with their role and open cases, and what nobody has yet.
    For a colleague: what nobody has yet. A team of one: nothing (every open case is in Needs you)."""
    if mg["solo"]:
        return ""
    free = len(mg["unassigned"])
    link = f'/?view=unassigned{"&" + q[1:] if q else ""}'
    if not head:
        return (f'<section class="team"><h2>Not taken yet · {free}</h2><p class="t-sub">Nobody has these yet: '
                f'<a href="{e(link)}">open one and take it</a>.</p></section>')
    people = " · ".join(f'<b>{e(p["name"])}</b>, <i>{e(p["role"])}</i> · {len(p["items"])}' for p in mg["people"])
    return (f'<section class="team"><h2>Your team is on it</h2><p>{people} · '
            f'<a href="{e(link)}">not taken yet {free}</a></p></section>')


BUCKETS = (("waiting_customer", "Waiting for the customer", ""), ("waiting_paypal", "Waiting for PayPal", ""),
           ("done", "Done", " done"))


def _until_words(st: dict) -> str:
    """The right-hand column of a waiting or done row: the date that matters, said for what it means."""
    u = st.get("until")
    if st["state"] == "done":
        return "closed"
    if st["state"] == "waiting_paypal":
        return "PayPal's move"
    if u and "closes itself" in st.get("then", ""):
        return f"closes itself on {u.day} {u:%b}"
    if u and st.get("paypal"):
        return f"PayPal closes it on {u.day} {u:%b}"
    return f"until {u.day} {u:%b}" if u else "the customer's move"


def bucket_block(rows: list, title: str, cls: str, q: str) -> str:
    """One of Today's other buckets: a case once, in its state, with the last thing that happened and its date."""
    if not rows:
        return ""
    lis = "".join(f'<li><a href="{e(r["link"])}{q}"><span class="what"><b>{e(r["who"] or "")}</b>, <i>customer</i> · '
                  f'{e(r["summary"])}<span class="t-sub">{e(r["state"]["why"])}</span></span>'
                  f'<span class="due soft">{e(_until_words(r["state"]))}</span></a></li>' for r in rows)
    return (f'<section class="bucket{cls}"><h2>{e(title)} · {len(rows)}</h2>'
            f'<ul class="needs-list">{lis}</ul></section>')


def _toast(v: dict, done: str, q: str) -> str:
    """After a move, back on Today: which case, what went, and the state it is in now."""
    rows = [*v["needs"], *(r for k, _, _ in BUCKETS for r in v["waiting"][k])]
    r = next((x for x in rows if x.get("id") == done), None)
    if not r:
        return ""            # `done` is only a lookup key: nothing is read for an id that is not on this page
    sent = ((_raw(r["id"]) or {}).get("sent") or "").split(". Sent by ")[0].split(". (")[0].rstrip(".")
    if not sent:
        return ""
    st = r.get("state") or {}
    now = st.get("label") or "Your move"
    if "(demo: simulated)" in st.get("why", ""):
        now += " (demo: simulated)"
    return (f'<p class="toast"><b>✓ {e(r["who"] or "")}:</b> {e(sent)}. Now: {e(now)}. '
            f'<a href="{e(r["link"])}{q}">Open the case</a></p>')


def today_page(src: str, me: str | None = None, done: str = "") -> str:
    """The morning screen: what needs this person first, then what came in since yesterday, then who has the rest.
    The figures are on Numbers. "I see, I manage, I know" is the idea behind it, not its layout (Claudia, 27/10).
    `done`: the case just acted on (the case page's way back says which): a toast names it and its state now."""
    demo = src == "demo"
    if demo:
        confirm_demo_refunds()          # the demo's PayPal "confirms" a refund at the next look (spec Part 4)
    v = today_view(src, me)
    q = "?shop=demo" if demo else ""
    t = v["team"]
    person = None if t.get("solo") else team_mod.person(t, me)
    hour = 9 if demo else datetime.now().hour          # the demo's clock is a morning
    hello = ("Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening") + \
        (f", {person.get('name') or person['id']}" if person else "")
    d, s = v["today"], v["see"]
    line = (f'{d:%a} {d.day} {d:%b} · {len(s["rows"])} new since yesterday · '
            f'{s["orders"]:,} new order{"s" if s["orders"] != 1 else ""}')
    ours = v["autopilot"]["on"]
    rule = ("Nothing goes out until a person approves it, each within their own limit." if not ours else
            "Nothing goes out until a person approves it, each within their own limit, except the kinds Second Look's AI "
            f"answers on its own under your setting: {'; '.join(ours)} (Your rules).")
    h = v["handled"]
    handled = (f'Today you handled {h["cases"]} case{"s" if h["cases"] != 1 else ""}, about {_hours(h["minutes"])}.'
               if h["cases"] else "")
    buckets = "".join(bucket_block(v["waiting"][k], title, cls, q) for k, title, cls in BUCKETS)
    body = (f'<div class="morning">{_toast(v, done, q) if done else ""}<h1 class="page">{e(hello)}.</h1>'
            f'<p class="who">{e(line)}</p>' + (f'<p class="t-sub">{e(handled)}</p>' if handled else "")
            + f'{needs_block(v["needs"], q, me, src, bool(t.get("solo")))}{buckets}'
            f'<section class="new">{see_block(s, q, v["phone"], v["calls_pending"])}</section>'
            f'{team_block(v["manage"], v["head"], q)}<p class="t-sub rule-line">{e(rule)}</p></div>')
    return page("Today | Second Look", "PayPal sandbox", body, demo, me=me, here="today")


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


def _call_length(minutes) -> str:
    seconds = int(round(float(minutes) * 60))
    return f"{seconds // 60} min {seconds % 60:02d} s call" if seconds >= 60 else f"{seconds} s call"


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
        if x["channel"] == "call" and x.get("minutes"):
            # a call: how long it was (its staff time), and whose words these are: local whisper's, or shipped
            subject += (f'<span class="t-sub">{_call_length(x["minutes"])} · '
                        f'{e(x.get("transcript") or "transcript")}</span>')
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


def _related(c: dict) -> str:
    """The order's earlier case (closed) and its later ones: one order's history, never merged."""
    store = case_store(shop_of_case(c["id"]))
    out = []
    if c.get("earlier_case"):
        before = store.get(c["earlier_case"]) or {}
        how = cases_mod.outcome_says(before, CLOSE_OUTCOMES) if before.get("outcome") else ""
        out.append(f'Earlier case: <a href="/c/{e(c["earlier_case"])}">{e(c["earlier_case"])}</a>'
                   + (f' (closed: {e(how)})' if how else ""))
    for x in c.get("later_cases", []):
        out.append(f'Later case: <a href="/c/{e(x)}">{e(x)}</a>')
    return f'<p class="owner-line">{" · ".join(out)}.</p>' if out else ""


def _close_form(cid: str, me: str | None) -> str:
    by = f'<input type="hidden" name="by" value="{e(me)}">' if me else ""
    opts = "".join(f'<option value="{e(k)}">{e(v)}</option>' for k, v in CLOSE_OUTCOMES.items())
    return (f'<form class="pick" method="post" action="/c/{e(cid)}/close"><label for="outcome">Close this case</label>'
            f'{by}<select id="outcome" name="outcome">{opts}</select><div class="approve"><button class="quiet">Close it</button>'
            '<span>Only when it is settled: a new message from the customer opens a new case.</span></div></form>')


def case_file_page(cid: str, me: str | None = None, flash: str = "") -> str:
    close_quiet(shop_of_case(cid)) if cases_mod.is_case_id(cid) else None
    v = case_view(cid)
    demo = v is not None and v["src"] == "demo"
    if v is None:
        return page("No such case | Second Look", "", '<h1 class="page">No case with that id in this shop.</h1>', is_demo(cid), me=me)
    c, d, o = v["case"], v["dispute"], v["order"]
    cur = v["currency"]
    stage = f'<span class="pill {"shop" if c["stage"] == "inquiry" else "onclaim" if c["stage"] == "paypal_claim" else "paypal"}">' \
            f'{e(cases_mod.STAGE_LABEL[c["stage"]])}</span>'
    if c["status"] != "open":
        stage += (f'<span class="pill buyer">Closed{" by PayPal" if c.get("closed_by") == "PayPal" else ""}: '
                  f'{e(cases_mod.outcome_says(c, CLOSE_OUTCOMES))}</span>')
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
    closes = _closes_words(c)
    owner += f'<p class="owner-line">{e(closes)}</p>' if closes else ""
    left = (f'<a class="back" href="/{"?shop=demo" if demo else ""}">All disputes and requests</a>{stage}'
            f'<p class="claim{"" if c["sorted"].get("by") == "ai" else " quote"}">{e(case_summary(c))}</p>'
            f'<p class="who">{e(cust.get("name") or cust.get("email") or "")}, <i>customer</i> · {e(cust.get("email") or "")}<br>'
            f'{order_line} At stake: {v["at_stake"]:.2f} {e(cur)}.<br>Came in by: {came}</p>{check}{owner}{_related(c)}'
            f'{unconfirmed_note(_marks([c], cur), cid, me)}'
            f'{timeline_block(v)}')
    top = ""
    if d:
        # A PayPal dispute now: PayPal's rules, and the dispute's own review and buttons, right here.
        top, side = side_box(d["dispute_id"], _case(d["dispute_id"]), c, me, plain_owner=False)
        right = (f'<div class="judged"><b>This case is a PayPal dispute now: {e(d["dispute_id"])}.</b> PayPal\'s rules '
                 f'apply, and the answer goes to PayPal. <a href="/d/{e(d["dispute_id"])}">The dispute\'s own page</a>.</div>'
                 + side)
    elif not c["sorted"]["by"]:
        right = _pick_form(cid, me, c["sorted"]["how"] or "")
    else:
        case = _case(cid)
        left += f'<h2>What the evidence says</h2>{evidence(case["seller_records"], inquiry=True)}' if o else ""
        top, side = side_box(cid, case, c, me, plain_owner=False)
        right = (ai_check_form(v["src"], cid, me, f"/c/{cid}") + side
                 + (_close_form(cid, me) if c["status"] == "open" else ""))
        if not c.get("order_no"):
            right += _pick_form(cid, me, "Sorted as a question with no order. If it is about one, say which.", question=True)
    body = (f'{top}<div class="case"><section>{flash}{left}</section><section class="look">{right}{money_block(v, me)}{case_costs_block(v)}'
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


def unconfirmed_note(marks: list, cid: str | None = None, me: str | None = None) -> str:
    """A refund PayPal didn't confirm, said plainly; on its own case, the two answers a person can give."""
    out = []
    for m in marks:
        out.append(f'<p class="check-sender">A refund of {m["amount"]:.2f} {e(m["currency"])} wasn\'t confirmed by PayPal'
                   f'{" on " + e(m["on"]) if m["on"] else ""}: check the payment in PayPal, then say what happened.</p>')
        if cid and m["case_id"] == cid:
            by = f'<input type="hidden" name="by" value="{e(me)}">' if me else ""
            out.append(f'<form class="pick" method="post" action="/c/{e(cid)}/unconfirmed">{by}'
                       f'<input type="hidden" name="request_id" value="{e(m["request_id"] or "")}">'
                       '<div class="approve"><button name="refunded" value="yes">PayPal refunded it</button>'
                       '<button class="quiet" name="refunded" value="no">PayPal did not refund it</button></div></form>')
    return "".join(out)


def case_refund_note(r: dict) -> str:
    """On a PayPal dispute's page: each refund and each replacement the shop already logged on this order's cases,
    before PayPal had it, and any refund PayPal didn't confirm."""
    marks = unconfirmed_note(r.get("unconfirmed_logged") or [])
    if not r.get("refund_logged_on_case") and not r.get("replacement_logged_on_case"):
        return marks

    def when(x):
        return f'{" on " + e(x["on"]) if x.get("on") else ""}{" by " + e(x["by"]) if x.get("by") else ""}'

    def case_link(x):
        return f'<a href="/c/{e(x["case_id"])}">{e(x["case_id"])}</a>'
    each = [f'A refund of {x["amount"]:.2f} {e(x.get("currency", ""))} was already logged on case {case_link(x)}{when(x)}.'
            for x in r.get("refunds_logged", [])]
    each += [f'A replacement ({x["amount"]:.2f} {e(x.get("currency", ""))} of goods) was already logged on case '
             f'{case_link(x)}{when(x)}.' for x in r.get("replacements_logged", [])]
    return marks + (f'<p class="check-sender">{" ".join(each)} Check it before you answer PayPal: paying or sending twice, or '
            'defending what you already gave, is never right.</p>')


def part_of_case(did: str) -> str:
    """On a dispute's page: the case it belongs to when another channel joined it (Pablo's email + DEMO-034)."""
    c = None if did.startswith("PP-D-") else find_case_of_dispute(did)
    if not c:
        return ""
    came = " + ".join(cases_mod.CHANNEL_LABEL[ch] for ch in cases_mod.channels(c, {"dispute_id": did, "messages": []}))
    return f'<p class="owner-line">One case, every channel: <a href="/c/{e(c["id"])}">{e(c["id"])}</a> ({e(came)}).</p>'


def _move_facts(did: str, case: dict, c: dict | None) -> dict:
    """What a move's text and button say about this case (moves.py): the customer's first name, the courier and its
    tracking, the amount, the order, the shop's name."""
    d, r = case["dispute"], case["seller_records"]
    buyer = ((d.get("disputed_transactions") or [{}])[0].get("buyer") or {}).get("name")
    name = ((c or {}).get("customer") or {}).get("name") or buyer or ""
    tr = r.get("tracking") or {}
    carrier = tr.get("carrier_name_other") or (tr.get("carrier") if tr.get("carrier") != "OTHER" else None)
    when = _t(tr.get("last_update")) if tr.get("status") == "DELIVERED" else None
    amt = d["dispute_amount"]
    shop = (DemoPayPal().shop if is_demo(did) else _live_shop()).get("name")
    return {"first": name.split(" ")[0], "carrier": carrier,
            "tracking": f' (tracking {tr["tracking_number"]})' if tr.get("tracking_number") else "",
            "amount": f'{float(amt["value"]):.2f} {amt.get("currency_code", "EUR")}',
            "order": f'order {c["order_no"]}' if (c or {}).get("order_no") else None, "delivered": f" on {when.day} {when:%b}" if when else "", "shop": shop}


BUCKET = {"your_move": "Needs you", "waiting_customer": "Waiting for the customer",
          "waiting_paypal": "Waiting for PayPal", "done": "Done"}


def needs_after(src: str, me: str | None, did: str) -> list:
    """What else needs this person (the same list as Today's), for the case page's way back and its "Next" button."""
    if src not in ("demo", "live"):
        return []
    return [n for n in today_view(src, me)["needs"] if n["kind"] == "case" and n["id"] != did]


def _today_link(src: str, did: str) -> str:
    return "/today?" + urlencode({**({"shop": "demo"} if src == "demo" else {}), "done": did})


def crumb(st: dict, name: str, src: str, did: str, more: int) -> str:
    """Where you are (spec Part 3, slot 1): Today › the bucket this case is in › its customer; and the way back, which
    says how many more need you and names this case, so Today can say what just happened to it."""
    q = "?shop=demo" if src == "demo" else ""
    left = f'{more} more need{"s" if more == 1 else ""} you' if more else "nothing else needs you"
    return (f'<nav class="crumb"><span><a href="/today{q}">Today</a> › {e(BUCKET[st["state"]])} › <b>{e(name)}</b></span>'
            f'<a href="{e(_today_link(src, did))}">← Back to Today · {e(left)}</a></nav>')


def state_box(st: dict, did: str, src: str, nxt: list) -> str:
    """The top of the side box (spec Part 3, slot 6): the state, until when, and what happens then. After a move, a
    "✓ Done" line says what went, who and when (in the demo: that nothing really went). When it isn't this person's
    move: "Nothing needs you", and the next case that does."""
    q = "?shop=demo" if src == "demo" else ""
    raw, sb = _raw(did) or {}, _saved_by(did)
    done = ""
    if raw.get("sent"):
        what = str(raw["sent"]).split(". Sent by ")[0].split(" (Demo shop")[0].rstrip(".")
        who = ", ".join(x for x in (sb.get("by"), _when(str(sb.get("at") or "")[:16])) if x)
        done = (f'<div class="done-line"><b>✓ Done: {e(what)}</b><span class="t-sub">{e(who)}</span></div>'
                + ('<p class="demo-line">Demo shop: logged here. Nothing was really sent.</p>' if is_demo(did) else ""))
    pill = f'<span class="state-pill {e(st["state"])}">{e(st["label"])}</span>'
    u = st["until"]
    if st["state"] == "your_move":
        when = (f' Answer by <b>{u:%a} {u.day} {u:%b}</b>' if u else "" if st["paypal"] else " No PayPal deadline")
        return (done + f'<div class="state-box move"><p>{pill}{when}</p>'
                f'<p class="t-sub">{e(st["why"])} {e(st["then"])}</p></div>')
    nothing = "" if st["state"] == "done" else "<b>Nothing needs you.</b> "
    nxt_html = ""
    if nxt:
        n = nxt[0]
        nxt_html = (f'<p class="band">Next in Needs you · {len(nxt)}</p>'
                    f'<a class="next" href="{e(n["link"])}{q}">{e(n["who"] or "")} · {e(n["summary"])} →</a>')
    nxt_html += f'<a href="{e(_today_link(src, did))}">or back to Today</a>'
    return (done + f'<div class="state-box"><p>{pill} {e(st["why"])}</p><p>{nothing}{e(st["then"])}</p>'
            f'{nxt_html}</div>')


def side_box(did: str, case: dict, c: dict | None, me: str | None, flash: str = "", plain_owner: bool = True) -> tuple:
    """(crumb, side box) for a case page: the state first, then the review. Off this person's move, the review and its
    checks fold away: what happened is above, what's left to do is said."""
    src = src_of_case(did, "live") if not cases_mod.is_case_id(did) else shop_of_case(did)
    saved = _saved(did)
    st = case_state(did, case["dispute"] if not cases_mod.is_case_id(did) else None, c,
                    out_of_date=bool(saved) and not saved[1] and bool(_changes(did, case)))
    nxt = needs_after(src, me, did)
    name = ((c or {}).get("customer") or {}).get("name") or \
        ((case["dispute"].get("disputed_transactions") or [{}])[0].get("buyer") or {}).get("name") or did
    col = review_column(did, case, me, flash, plain_owner)
    if st["state"] != "your_move":
        col = f'<details class="fold"><summary>Second Look\'s review and the ten checks</summary>{col}</details>'
    return crumb(st, name, src, did, len(nxt)), state_box(st, did, src, nxt) + col


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
    top, side = side_box(dispute_id, case, find_case_of_dispute(dispute_id) if not practice else None, me, flash)
    body = (f'{top}<div class="case"><section>{left}</section>'
            f'<section class="look">{side}</section></div>')
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
            role = f' ({holder["role"]})' if holder and holder.get("role") else ""
            owner = f'<p class="owner-line">{e(holder_name)}\'s case{e(role)}.</p>' if plain_owner else ""
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
        if o["outcome"] == "send" and o["action"] in moves_mod.THEN:
            c_ = case_store(shop_of_case(did)).get(did) if cases_mod.is_case_id(did) else find_case_of_dispute(did)
            nxt = moves_mod.then(o["action"], _move_facts(did, case, c_), cases_mod.is_case_id(did))
            action_part += f'<p class="then"><b>What happens next:</b> {e(nxt)}</p>'
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
    elif _money_cases_for(did, lambda: _client(did).get_dispute(did)):
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
    "already_replaced": "the order's value already went out as a replacement",
    "refund_logged_on_case": "a refund already logged on this order's case",
    "replacement_logged_on_case": "a replacement already logged on this order's case",
    "refund_unconfirmed": "a refund PayPal hasn't confirmed yet",
}


def _refused(dec: Decision | None, chosen: str, w: dict | None = None) -> str:
    """Why may_approve refused. The guard's reasons only where they are the reason: for the AI's own answer,
    or for the drafted question on "your call" (PayPal's rules, an unrecognised answer, a promised refund)."""
    w = w or _words(None)
    if dec and dec.action == "ASK_SELLER" and chosen == "MESSAGE":
        why = [STOP_SAYS[s] for s in ("message_not_allowed", "unknown_action", "refund_logged_on_case",
                                      "replacement_logged_on_case", "refund_unconfirmed") if s in dec.stops]
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
            review: str | None = None, *, ai_signed: str | None = None, ai_kind: str | None = None,
            report: dict | None = None) -> tuple[int, str]:
    """Send the answer a person chose. Returns (HTTP status, what happened).
    200 sent · 202 passed to a colleague (nothing sent) · 400 nobody named or no words · 409 changed or not allowed.
    `review`: the review_mark of the review they were shown; when given, a different review is refused.
    `ai_signed`: Second Look's AI approves, on a kind the shop switched on (autopilot_case only: a page or the API
    always names a person, and "second-look-ai" is nobody in the team), signed so, within its own limit. Under the
    case's lock it checks again that the case is nobody's and that `ai_kind` (required) is still on: a review takes
    seconds, and a person may take the case or switch the kind off meanwhile. `report` gets what happened as data:
    report["code"] ("sent", "unconfirmed", "pass", "over", "person", "off", "paypal", "already_sent",
    "review_changed", "case_changed", "refused"), so its look never reads approve's sentences."""
    from .__main__ import execute
    if chosen == "ASK_SELLER":
        # "your call" is what the review says when a person must choose; approving it would mark the review sent
        # with nothing done (found in review, 25/10)
        return 400, "\"Your call\" is not an answer: choose what to send (a reply, a refund, your evidence)."
    t = team_for(did)
    ai = None
    if ai_signed and not ai_kind:
        return 400, "Second Look's AI approves only for a kind of case that is on: say which."
    if ai_signed:
        ai = {"kind": ai_kind, "solo": bool(t.get("solo")), "src": shop_of_case(did),
              "report": report if report is not None else {}}
        ai["report"]["code"] = "refused"
        shop_t, (t, who) = t, autopilot_mod.as_ai(t, ai_signed)
    else:
        who = team_mod.person(t, by)
    if not who:
        return 400, "Say who is approving: a person in this shop's team."
    if shop_of_case(did) == "demo":
        case_store("demo")   # the demo's first load first: its own looks approve, under their cases' locks
    with _case_lock(did):  # from reading the review to saving what was sent, or the handoff
        if ai:
            no = _ai_may_not(did, shop_t, ai)
            if no:
                return 409, no
        return _approve(did, chosen, message, rule, t, who, execute, review, ai)


def _ai_handled(did: str, ai: dict, what: str) -> None:
    """Second Look's AI's send on its record, under the case's lock, after the review is saved as sent. A record
    that can't be written is logged only: it never stops the save, nor makes what went out look unsent."""
    try:
        autopilot_store(ai["src"]).handled(did, ai["kind"], cases_mod.minute(None), what)
    except Exception as err:  # noqa: BLE001 - see above
        print(f"Second Look's AI ({did}): its record wasn't written: {err}", file=sys.stderr)


def _ai_may_not(did: str, t: dict, ai: dict) -> str | None:
    """Why Second Look's AI may not send on this case now (under the case's lock, as `take` and every approval are),
    or None. `t`: the shop's own team. Sets ai["report"]."""
    rep = ai["report"]
    if not cases_mod.is_case_id(did):
        rep["code"] = "paypal"
        return autopilot_mod.NOT_YET
    why = _a_person_s(did, t, case_store(ai["src"]).get(did), None)
    if why:
        rep["code"], rep["why"] = "person", why
        return why[:1].upper() + why[1:] + "."
    if not (autopilot_store(ai["src"]).view()["kinds"].get(ai["kind"]) or {}).get("on"):
        rep["code"] = "off"
        return "This kind was switched off while it looked."
    return None


def _approve(did, chosen, message, rule, t, who, execute, review=None, ai=None) -> tuple[int, str]:
    rep = ai["report"] if ai else {}      # Second Look's AI's approval: what happened, as a code (approve)
    saved = _saved(did)
    if cases_mod.is_case_id(did) and not (saved and saved[1]):
        no = _inquiry_refusal(did)      # unsorted, or PayPal has it now: never answered as an inquiry
        if no:
            return 409, no
    if saved and saved[1]:
        if ai:      # never "200": what was sent then is not its own
            rep["code"] = "already_sent"
            return 409, "Already answered on this case: Second Look's AI sends nothing more."
        return 200, saved[1]  # already sent: a second approval sends nothing
    if not saved:
        return 409, _refused(None, chosen)
    if review and review != review_mark(did):
        rep["code"] = "review_changed"
        return 409, "This answer changed since you saw it. Look again."
    if chosen in _WORDS_NEEDED and message is not None and not message.strip():
        return 400, "Write a message first."
    dec = saved[0]
    case = _case(did)
    if _changes(did, case):
        rep["code"] = "case_changed"
        return 409, "Something changed since this review. Take a fresh look."
    kind, to = outcome(dec, chosen, case["dispute"], t, who)
    if kind == "refused":
        return 409, to
    cur = case["dispute"]["dispute_amount"].get("currency_code", "EUR")
    amount = money_out(chosen, dec.judgment, case["dispute"])
    need = required(chosen, dec, case["dispute"])
    now = _local_now()
    if kind == "pass" and ai and ai["solo"]:
        # A team of one: over its own limit, the seller decides; no handoff (nobody would ever clear one).
        cap = team_mod.limit(t, who["id"]) or 0.0
        rep.update(code="over", what=f"{ACTION.get(chosen, chosen).lower()} of {amount:.2f} {cur}", limit=f"{cap:.2f} {cur}")
        return 409, f"{rep['what'][:1].upper()}{rep['what'][1:]} is over its own {rep['limit']} limit: you decide."
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
        rep.update(code="pass", what=what, limit=f"{cap:.2f} {cur}", to=to["name"])
        return 202, f"Passed to {to['name']}: {what} is over your {cap:.2f} {cur} limit. Nothing was sent."
    if message is None and not t.get("solo"):
        # No message given (the API): the colleague who passed this case on edited the reply; send theirs.
        hand = assignments_for(did).get(did)["handoff"]
        if isinstance(hand, dict) and hand.get("action") == chosen and hand.get("message") is not None:
            message = hand["message"]
    recommended, drafted = dec.action, dec.judgment.draft_message
    is_ai = who["id"] == autopilot_mod.AI_ID
    dec.action = chosen  # "your call": a question, or the answer held back only for its size
    if message is not None:
        dec.judgment.draft_message = message
    raw = _raw(did) or {}  # the case's own review, or the shipped demo one it starts from
    seen, judged = raw.get("seen"), raw.get("judge")
    inquiry = cases_mod.is_case_id(did)
    rid = None
    if inquiry:
        n_money = len((case_store(shop_of_case(did)).get(did) or {}).get("money", []))
        rid = "sl-" + hashlib.sha256(f"{did}|{review_mark(did)}|{n_money}".encode()).hexdigest()[:32]
    client = (Outbox(did, by=who["name"], ai=judged == "claude", amount=float(case["dispute"]["dispute_amount"]["value"]),
                     request_id=rid, autopilot=is_ai)
              if inquiry else _client(did))
    try:
        result = execute(client, dec, case["dispute"], case["seller_records"])
    except RefundRefused as err:
        return 409, str(err)
    except RefundNotConfirmed as err:
        if err.attempted:
            # PayPal may have made it: no money recorded, but a mark that holds every money action on the order
            # until a person checks PayPal and says what happened (or this same approval is retried and confirmed)
            mark = {"request_id": rid, "kind": chosen.lower(), "amount": round(err.amount, 2), "currency": err.currency,
                    "at": cases_mod.minute(None), "by": who["name"]}
            case_store(shop_of_case(did)).update(did, lambda c: c.update(
                unconfirmed=[x for x in c.get("unconfirmed", []) if x.get("request_id") != rid] + [mark]))
            if ai:
                # Second Look's AI asked PayPal: the money may have moved. Its slot stays used, and the case is on
                # the list a person checks.
                rep["code"] = "unconfirmed"
                _ai_handled(did, ai, "Refund not confirmed by PayPal: check the payment in PayPal.")
        return 502, "PayPal didn't confirm the refund: check the payment in PayPal before trying again."
    rep["code"] = "sent"    # Second Look's AI's answer is out: whatever fails after, it is never taken for unsent
    if not is_demo(did):
        _live_forget()      # PayPal's side may have changed: the next page reads it afresh
    if result.get("amount") is not None:
        amount, cur = float(result["amount"]), result.get("currency") or cur     # what PayPal was asked to refund
    how = OUT_WORDS.get(result.get("channel"), "by email") if inquiry else ""
    via = ("logged for PayPal's refund API (demo: nothing sent)" if is_demo(did) else "sent through PayPal") \
        if inquiry and result.get("via") == "paypal" else "logged"
    sent = {"MESSAGE": ("Question" if recommended == "ASK_SELLER" else "Reply") + f" sent {how}.",
            "REFUND": f"Refund of {amount:.2f} {cur} {via} and reply sent {how}.",
            "PARTIAL_REFUND": f"Partial refund of {amount:.2f} {cur} {via} and reply sent {how}.",
            "REPLACE": f"Exchange or replacement logged and reply sent {how}."}.get(dec.action, "Done.") if inquiry else {"DEFEND": "Evidence submitted and reply sent." if not str(result.get("message", "")).startswith("not sent")
            else "Evidence submitted. Reply not sent: PayPal is waiting for the buyer to answer your last message.",
            "MESSAGE": "Question sent." if recommended == "ASK_SELLER" else "Reply sent.",
            "REFUND": "Refund accepted and reply sent.", "PARTIAL_REFUND": "Partial refund offered.",
            "REPLACE": "Replacement offered."}.get(dec.action, "Done.")
    if not t.get("solo"):
        sent += f" Sent by {who['name']}, {now:%H:%M}."
    if inquiry:
        sent += (" (Demo shop: logged; no email or money sent.)" if is_demo(did) else
                 " (Logged in Second Look: your helpdesk sends the email; the refund went to PayPal.)"
                 if result.get("via") == "paypal" else
                 " (Logged in Second Look: your helpdesk sends the email; money is not moved from here.)")
    elif is_demo(did):
        sent += " (Demo shop: logged, not sent to PayPal.)"
    elif isinstance(_client(did), MockPayPal):
        sent += " (Practice case: logged, not sent to PayPal.)"
    if suggest_rule(rule or "", did):
        sent += " Your rule suggestion waits on Your rules for review."
    dec.action = recommended  # the page keeps showing what was recommended
    by_name = None if t.get("solo") else who["name"]
    if inquiry and seen and chosen == "REPLACE":
        # an exchange: what is left of the order went out as goods, and its return is used (no postage count now)
        seen = {**seen, "amount": "0.00", "return": None}
    if inquiry and seen and chosen in ("REFUND", "PARTIAL_REFUND"):   # what was sent (dec.action is the recommendation again)
        # What this approval itself logged (a refund lowers what is left) is part of what the review saw; only
        # something new (the customer writing again) makes it out of date. Only this send's own change is added:
        # a message that lands while it is sent was never seen (re-reading the case here would count it).
        seen = {**seen, "amount": f"{max(0.0, float(seen['amount']) - amount):.2f}"}
    _save(did, dec, sent, seen, by=by_name, at=now.isoformat(timespec="minutes"), judge=judged, chosen=chosen,
          amount=round(amount, 2) if amount else None, due=case["dispute"].get("seller_response_due_date"))
    if ai:
        _ai_handled(did, ai, sent)    # on its record and the list a person checks (its slot is taken already)
    if not t.get("solo") and not is_ai:
        # Sent by them: the case is theirs, and any handoff waiting on it is done. (Second Look's AI is never given
        # a case: what it sent stays open for a person.)
        assignments_for(did).update(did, lambda a: {"to": who["id"], "handoff": None})
    notify("answer.sent", {**_about(did), "action": chosen, "what_happened": sent, "by": by_name})
    if not is_ai and (judged or "claude") == "claude":    # a review saved before judges were recorded is Claude's
        _record_decision(did, case, recommended, chosen, message, drafted, who, now)
    if not inquiry and chosen in ("REFUND", "PARTIAL_REFUND") and amount:
        d, at, name = case["dispute"], now.strftime("%Y-%m-%dT%H:%M"), who["name"]
        post_books(lambda: _dispute_refund_row(did, d, at, round(amount, 2), cur, name))
    return 200, sent


def _record_decision(did: str, case: dict, recommended: str, chosen: str, message: str | None, drafted: str,
                     who: dict, now: datetime) -> None:
    """A person's decision on a review Second Look's AI made, for its record (autopilot.py): approved as advised =
    the action it recommended (after your limits), the same amount (an amount is the review's own, so the same
    action sends the same), the reply not edited. The caller has checked it is a person and the AI's review (never
    the rules baseline's, never its own sends). "Your call" is no kind it could answer on its own: not recorded."""
    src = src_of_case(did, "live")
    if src == "practice" or recommended == "ASK_SELLER":
        return
    inquiry = cases_mod.is_case_id(did)
    stage, problem = ("inquiry", case["inquiry"]["problem_kind"]) if inquiry else ("paypal", case["dispute"].get("reason"))
    same = message is None or autopilot_mod.same_words(message, drafted)
    entry = {"case": did, "at": now.isoformat(timespec="minutes"), "by": who["name"], "as_advised": chosen == recommended and same}
    if not entry["as_advised"]:
        entry["why"] = "another action" if chosen != recommended else "the reply was edited"
    autopilot_store(src).decide(autopilot_mod.kind_key(stage, problem, recommended), entry,
                                autopilot_mod.settings(team_for(did))["window"])


# ---------- earned autonomy: Second Look's AI answers a kind the shop switched on (secondlook/autopilot.py) ----------
# How its look runs: None = at once, in the caller's thread (the tests, the CLI); serve() sets a thread of its own,
# like whisper's and the books' posts, so no page or API request waits on a review. A test that forgets a setting
# never leaves a thread running past its bench.
AUTOPILOT_RUN = None


def _in_a_thread(fn) -> threading.Thread:
    th = threading.Thread(target=fn, daemon=True)
    th.start()
    return th


def autopilot_soon(src: str, stage: str, problem: str | None, did: str):
    """Second Look's AI takes its look at one case (autopilot_case) when this shop has a kind on for this stage and
    problem. A shop with nothing on pays for nothing: no review runs. Returns the thread, when one was started."""
    if src not in CASE_FILES or not autopilot_store(src).kinds_on(stage, problem):
        return None
    if AUTOPILOT_RUN is None:
        _look(src, did)
        return None
    at = cases_mod.CLOCK.at                       # a look in its own thread keeps the clock of whoever asked for it

    def look():
        with cases_mod.clock(at):
            return _look(src, did)
    return AUTOPILOT_RUN(look)


def _look(src: str, did: str) -> dict | None:
    """autopilot_case, which never fails the request that filed the case, nor the server: a look that fails leaves
    its trace on the case, and the case waits for a person. A look never waits for the first load (case_store)."""
    was, _IN_A_LOOK.on = getattr(_IN_A_LOOK, "on", False), True
    try:
        return autopilot_case(src, did)
    except Exception as err:  # noqa: BLE001 - see above
        print(f"Second Look's AI ({did}): {err}", file=sys.stderr)
        try:
            c = case_store(src).get(did) if cases_mod.is_case_id(did) else find_case_of_dispute(did)
            return _ai_steps_back(src, did, c, None, f"its look failed ({err})")
        except Exception as err2:  # noqa: BLE001 - nowhere left to write it: the log has it
            print(f"Second Look's AI ({did}): {err2}", file=sys.stderr)
            return None
    finally:
        _IN_A_LOOK.on = was


def autopilot_after(src: str, c: dict | None):
    """A request was filed on this case: its decision is its PayPal dispute when it has one, else the inquiry."""
    if not c or not any(k.get("on") for k in autopilot_store(src).view()["kinds"].values()):
        return None
    if c.get("dispute_id"):
        d = next((x for x in shop_disputes(src) if x["dispute_id"] == c["dispute_id"]), None)
        return autopilot_soon(src, "paypal", d.get("reason"), c["dispute_id"]) if d and d.get("status") != "RESOLVED" else None
    return autopilot_soon(src, "inquiry", c["problem"]["kind"], c["id"])


# What approve() refused Second Look's AI for (its report's code), in the words a step back gives; any other
# refusal is given in approve's own words.
AI_REFUSED = {"unconfirmed": "PayPal didn't confirm its refund: check the payment in PayPal",
              "off": "this kind was switched off while it looked",
              "review_changed": "its review was replaced while it looked",
              "case_changed": "the case changed since the review",
              "already_sent": "the case was answered while it looked"}
# The guard's two size stops, in the words a step back gives (STOP_SAYS has every other one).
SIZE_SAYS = {"cap": "a refund over your auto-refund cap", "always_ask": "a case over your always-ask line"}


def _ai_steps_back(src: str, did: str, c: dict | None, kind: str | None, why: str) -> dict:
    """Nothing sent: the case stays a person's, with the reason on its record and on the case."""
    autopilot_store(src).stepped_back(did, kind, cases_mod.minute(None), why)
    text = f"Second Look's AI stepped back: {why}. A person decides."
    if c:
        def note(x):
            if not any(y.get("text") == text for y in x["timeline"] if y.get("direction") == "note"):
                x["timeline"].append(cases_mod.entry(None, reply_channel(x), "note", text, autopilot_mod.AI_NAME,
                                                     ai=True, autopilot=True))
        case_store(src).update(c["id"], note)
    return {"did": did, "kind": kind, "handled": False, "why": why}


def _local_now() -> datetime:
    """Now in local time, as an approval shows it ("Sent by Giulia, 11:47"): the demo morning's when its clock is set."""
    if cases_mod.CLOCK.at:
        return cases_mod.now().replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    return datetime.now()


def _a_person_s(did: str, t: dict, c: dict | None, d: dict | None) -> str | None:
    """Why this case is a person's already, or None: someone has it, a handoff waits, or someone answered on it.
    Second Look's AI never takes a person's case, nor talks over them. `t`: the shop's own team."""
    a = None if t.get("solo") else assignments_for(did).get(did)
    if a and a.get("to"):
        p = team_mod.person(t, a["to"])
        name = p["name"] if p else a["to"]
        return f"a handoff to {name} waits" if isinstance(a.get("handoff"), dict) else f"{name} has this case"
    if _a_person_answered(did, c, d):
        return "a person has already answered on this case: it stays theirs"
    return None


def _hidden_instructions(c: dict | None) -> bool:
    """The customer's own words carry one of your injection markers (policy.json). Whatever the answer, it steps
    back: the guard stops such a case only when money moves, and a reply drafted from them would go out unseen."""
    said = " ".join(x.get("text") or "" for x in (c or {}).get("timeline", []) if x.get("direction") == "in").lower()
    return any(m.lower() in said for m in _policy().get("injection_markers", []))


def _a_person_answered(did: str, c: dict | None, d: dict | None) -> bool:
    """Someone of the shop already answered on this case: it stays theirs (Second Look's AI never talks over them)."""
    if cases_mod.is_case_id(did):
        return any(x["direction"] == "out" and not x.get("autopilot") for x in (c or {}).get("timeline", []))
    return any(m.get("posted_by") == "SELLER" for m in (d or {}).get("messages", [])) or \
        any(ev.get("source") == "SUBMITTED_BY_SELLER" for ev in (d or {}).get("evidences", []))


def autopilot_case(src: str, did: str) -> dict:
    """Second Look's AI's look at one case of a kind the shop switched on: one review by Second Look's AI (the current
    one when there is one), then, when its answer is a kind that's on and nothing says a person should decide, it
    approves it as itself through approve(), within its own limit. Otherwise it steps back: nothing sent, the reason
    on the case. Returns {"did", "kind", "handled", "why"}; why None = nothing to do here."""
    with _case_lock(f"autopilot|{did}"):    # one look at a time per case: two requests never pay for two reviews
        return _autopilot_case(src, did)


def _autopilot_case(src: str, did: str) -> dict:
    nothing = {"did": did, "kind": None, "handled": False, "why": None}
    store = autopilot_store(src)
    inquiry = cases_mod.is_case_id(did)
    c = case_store(src).get(did) if inquiry else find_case_of_dispute(did)
    d = None if inquiry else _client(did).get_dispute(did)
    stage, problem = ("inquiry", (c or {}).get("problem", {}).get("kind")) if inquiry else ("paypal", d.get("reason"))
    on = store.kinds_on(stage, problem)
    if not on or (inquiry and (not c or c["status"] != "open" or c.get("dispute_id"))):
        return nothing                            # nothing on here; or closed, or answered on its PayPal dispute

    def back(why: str, kind: str | None = None) -> dict:
        return _ai_steps_back(src, did, c, kind, why)
    # A person's case already: no review is paid for, nothing is sent over a colleague. (On a PayPal dispute, any
    # seller message counts as a person's, its own included: it never answers a dispute twice.) approve() checks
    # these again under the case's lock, once its review is done.
    if inquiry and not c["sorted"]["by"]:
        return back("the request isn't matched to an order yet")
    t = team_for(did)
    held = _a_person_s(did, t, c, d)
    if held:
        return back(held)
    if stage not in autopilot_mod.SWITCHABLE:     # a record that says on anyway: it never answers a PayPal dispute
        return back(autopilot_mod.NOT_YET[:1].lower() + autopilot_mod.NOT_YET[1:].rstrip("."))
    ours = [i for i, x in enumerate(c["timeline"]) if x["direction"] == "out" and x.get("autopilot")]
    if ours:      # it answered once: what the customer says next is a person's to answer
        if any(x["direction"] == "in" for x in c["timeline"][ours[-1] + 1:]):
            return back("the customer wrote again after Second Look's AI answered")
        return nothing
    if _hidden_instructions(c):
        return back("your limits held it back: " + STOP_SAYS["injection"])
    saved = _saved(did)
    changed = bool(saved) and bool(_changes(did, _case(did)))
    if saved and saved[1] and not changed:
        return nothing                            # answered, and nothing new since
    if not (saved and not saved[1] and judge_of(did) == "claude" and not changed):
        try:
            run_review(did)                       # Second Look's AI with a key; the rules baseline without one
        except Exception as err:  # noqa: BLE001 - a review that fails sends nothing
            return back(f"its review failed ({err})")
    dec, _, mark = _saved_marked(did)      # the review it checks, and the mark it approves with
    j, s = dec.judgment, autopilot_mod.settings(t)
    kind = autopilot_mod.kind_key(stage, problem, dec.action)
    if judge_of(did) != "claude":
        return back("the review came from the rules baseline (no AI key, or the model failed)", kind)
    if dec.stops or dec.reasons:
        held = [SIZE_SAYS.get(x) or STOP_SAYS.get(x, x) for x in dec.stops]
        return back("your limits held it back: " + (", ".join(held) if held else dec.reasons[0].rstrip(".")), kind)
    if j.action == "ASK_SELLER":
        return back("its own answer was: your call", kind)
    if j.confidence < s["min_confidence"]:
        return back(f"it is {j.confidence:.0%} sure, and it answers on its own only from {s['min_confidence']:.0%}", kind)
    if kind not in on:
        return back(f"its answer ({_words(did)['action'].get(dec.action, dec.action).lower()}) is not one it sends on its own", kind)
    day = cases_mod.now().strftime("%Y-%m-%d")
    if not store.reserve(kind, day, s["per_day"]):       # today's slot, taken before it sends
        return back(f"today's {s['per_day']} for this kind are used", kind)
    rep = {}
    try:
        signed = autopilot_mod.signature(store.view()["kinds"][kind], solo=bool(t.get("solo")))
        code, text = approve(did, dec.action, None, review=mark, ai_signed=signed, ai_kind=kind, report=rep)
    finally:
        if rep.get("code") not in ("sent", "unconfirmed"):
            store.release(kind, day)                        # nothing went: the slot is free again
    code = rep.get("code")
    if code == "sent":
        return {"did": did, "kind": kind, "handled": True, "why": None}
    if code in ("pass", "over"):
        return back(f"{rep['what']} is over its own {rep['limit']} limit: "
                    + (f"passed to {rep['to']}" if code == "pass" else "you decide"), kind)
    return back(rep["why"] if code == "person" else AI_REFUSED.get(code) or text.rstrip("."), kind)


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
    st = case_state(did, None if cases_mod.is_case_id(did) else d, out_of_date=bool(saved) and bool(_changes(did, case)))
    out["state"] = {**st, "until": st["until"].isoformat() if st["until"] else None}
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
            # The shop you're in stays the same from page to page: the numbers of one shop next to the
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
            if u.path == "/books.csv":
                bsrc = "live" if src == "live" else "demo"
                default = (DemoPayPal().today if bsrc == "demo" else datetime.utcnow().date()).strftime("%Y-%m")
                month = (qs.get("month") or [default])[0]
                if not re.fullmatch(r"\d{4}-\d{2}", month):
                    return self._send("month: YYYY-MM", 400)
                b = books_mod.csv_text(books_mod.for_month(books_rows(bsrc), month)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="second-look-books-{month}.csv"')
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                return self.wfile.write(b)
            if u.path == "/today":
                if src == "practice":
                    return self._redirect("/?practice=1")    # practice cases are a test bench, not a shop's morning
                return self._send(today_page(src, me=me, done=(qs.get("done") or [""])[0]))
            if u.path == "/api/today":
                if src != "live":
                    confirm_demo_refunds()          # the page's look and this one agree: the demo's PayPal confirms
                v = today_view("live" if src == "live" else "demo", (qs.get("as") or [None])[0])
                return self._json({"today": v["today"], "see": v["see"], "needs": v["needs"], "manage": v["manage"],
                                   "waiting": v["waiting"], "handled": v["handled"], "autopilot": v["autopilot"],
                                   "calls": {"being_transcribed": v["calls_pending"], "not_transcribed": v["calls_failed"]}})
            if u.path == "/api/numbers":
                return self._json(numbers_view("live" if src == "live" else "demo", (qs.get("by") or ["month"])[0]))
            if u.path in ("/overview", "/overview/"):
                return self._redirect("/numbers" + (f"?{u.query}" if u.query else ""))   # an old link still works
            if u.path == "/numbers":
                if src == "practice":
                    return self._redirect("/?practice=1")    # practice cases are a test bench, not a shop's numbers
                return self._send(numbers_page(src, me=me, by=(qs.get("by") or ["month"])[0]))
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
                cid = u.path[3:].strip("/")
                known = cases_mod.is_case_id(cid) and case_store(shop_of_case(cid)).get(cid) is not None
                return self._send(case_file_page(cid, me=me), 200 if known else 404)
            if u.path.startswith(("/api/orders/", "/api/tracking/")):
                kind, no = u.path.split("/")[2], unquote(u.path.split("/", 3)[3].strip("/"))
                rec = (order_record if kind == "orders" else tracking_record)("live" if src == "live" else "demo", no)
                return self._json(rec if rec else {"error": "unknown order"}, 200 if rec else 404)
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
            if parts in (["autopilot", "switch"], ["autopilot", "differently"], ["autopilot", "looks-right"]):
                src = "live" if form.get("shop", [""])[0] == "live" else "demo"
                by = form.get("by", [""])[0]
                if parts[1] == "switch":
                    code, text = autopilot_switch(src, form.get("kind", [""])[0], form.get("on", [""])[0] == "on", by)
                    to = f"/rules?shop={src}"
                elif parts[1] == "differently":
                    code, text = autopilot_differently(src, form.get("case", [""])[0], by, form.get("why", [""])[0])
                    to = _back_to(form.get("to", [""])[0], src)
                else:
                    code, text = autopilot_looks_right(src, form.get("case", [""])[0], by)
                    to = _back_to(form.get("to", [""])[0], src)
                return self._redirect(to) if code == 200 else self._send(e(text), code)
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
            if len(parts) == 3 and parts[0] == "c" and parts[2] == "unconfirmed":
                ok, me = by_for_post(team_for(parts[1]), form.get("by", [""])[0])
                if not ok:
                    return self._send("Choose who you are at the top of the page.", 400)
                code, text = resolve_unconfirmed(parts[1], form.get("request_id", [""])[0],
                                                 form.get("refunded", [""])[0] == "yes", me)
                return self._redirect(f"/c/{parts[1]}") if code == 200 else self._send(e(text), code)
            if len(parts) == 3 and parts[0] == "c" and parts[2] == "money":
                ok, me = by_for_post(team_for(parts[1]), form.get("by", [""])[0])
                if not ok:
                    return self._send("Choose who you are at the top of the page.", 400)
                code, text = reconcile(parts[1], form.get("i", [""])[0], form.get("outcome", [""])[0],
                                       form.get("paid_with", [None])[0], me)
                return self._redirect(f"/c/{parts[1]}") if code == 200 else self._send(e(text), code)
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


def _transcribe_in_the_background(every: float = 30.0) -> None:
    """The call box's own worker: local whisper on new recordings, outside every request, then a look again."""
    import time
    while True:
        for src in CALL_BOXES:
            try:
                transcribe_calls(src)
            except Exception as err:  # noqa: BLE001 - a recording that can't be heard never stops the server
                print(f"call box ({src}): {err}", file=sys.stderr)
        time.sleep(every)


def serve(port: int = 8765) -> None:
    global AUTOPILOT_RUN
    print(f"Second Look: http://127.0.0.1:{port}")
    AUTOPILOT_RUN = _in_a_thread          # Second Look's AI's looks: in the background, never inside a request
    threading.Thread(target=_transcribe_in_the_background, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
