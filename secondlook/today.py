"""The morning screen, "I see, I manage, I know": grouping and arithmetic over what the shop already holds (its
cases, PayPal's disputes, its orders, who has which case). Nothing here calls PayPal or a model.

  I see     everything that came in since yesterday, from every channel, in one list, nearest deadline first,
            with the orders that came in over the same time beside it (problems read against sales);
  I manage  who has which open case, what nobody has yet, and what waits for a colleague after a handoff;
  I know    this month, every channel: requests, solved before any PayPal dispute, staff time (estimated),
            money given back, fees, what the open cases could still cost.

"Since yesterday" starts at 00:00 on the day before the shop's today and has no end: in the demo shop (today is
20 Oct 2026) it is everything from 19 Oct on, including anything a person does now, whatever the clock says.
"This month" starts at 00:00 on the 1st of the shop's today's month, with no end either. "A period" (Numbers) runs
from 00:00 on its first day to 00:00 after its last; the current one, like this month, has no end. Times are compared
as Second Look saves them ("2026-10-19T08:52"): the demo shop's are UTC, like PayPal's.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import ledger
from .cases import CHANNEL_LABEL, KIND_LABEL, minute, staff_time
from .costs import DISPUTE_FEE, escalated

# The order chips and rows show channels in.
CHANNEL_ORDER = ("call", "email", "form", "paypal")
# Money that went back to a customer, as a case logs it (an inquiry's refund).
BACK = ("refund", "partial_refund")


def since(today: date) -> str:
    return (today - timedelta(days=1)).isoformat() + "T00:00"


def month_start(today: date) -> str:
    return today.replace(day=1).isoformat() + "T00:00"


def windows(today: date, by: str = "month") -> tuple:
    """Like for like: ((first, last) of this period so far, (first, last) of the same days of the one before), days
    inclusive. By month: the 1st to today, and the 1st of the month before to the same day, cut at that month's last
    day (31 Oct is compared with 1-30 Sep). By week, Monday first: Monday to today, and the same days a week before."""
    if by == "week":
        first = today - timedelta(days=today.weekday())
        return (first, today), (first - timedelta(days=7), today - timedelta(days=7))
    first = today.replace(day=1)
    end_before = first - timedelta(days=1)
    first_before = end_before.replace(day=1)
    return (first, today), (first_before, min(first_before + timedelta(days=today.day - 1), end_before))


def weeks(today: date, n: int = 8) -> list:
    """The last `n` weeks, Monday to Sunday, oldest first; this one ends today."""
    monday = today - timedelta(days=today.weekday())
    return [(monday - timedelta(days=7 * i), min(monday - timedelta(days=7 * i - 6), today)) for i in range(n - 1, -1, -1)]


def _within(at: str, start: str, end: str | None) -> bool:
    return at >= start and (end is None or at < end)


def _at(iso) -> str:
    """A PayPal or Second Look time as Second Look saves it; "" when there is none (never "now")."""
    return minute(iso) if iso else ""


def _num(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return v if v == v else 0.0


def _tx(d: dict) -> str | None:
    return ((d.get("disputed_transactions") or [{}])[0]).get("seller_transaction_id")


def _buyer_name(d: dict) -> str | None:
    return (((d.get("disputed_transactions") or [{}])[0]).get("buyer") or {}).get("name")


def _first_message(d: dict) -> str:
    return next((m.get("content", "") for m in d.get("messages", []) if m.get("posted_by") == "BUYER"), "")


def _buyer_since(d: dict, start: str) -> list:
    """When the buyer wrote on a PayPal dispute since `start` (an older dispute's new message came in too)."""
    return sorted(_at(m.get("time_posted")) for m in d.get("messages", [])
                  if m.get("posted_by") == "BUYER" and _at(m.get("time_posted")) >= start)


def _opened_by_call(c: dict) -> bool:
    """The case began with a phone call: its line is Second Look's description of the call, not anyone's words."""
    first = next((x for x in sorted(c.get("timeline", []), key=lambda x: x.get("at") or "") if x.get("direction") == "in"), None)
    return bool(first) and first.get("channel") == "call"


def _dispute_of_case(cases: list) -> dict:
    """Dispute id -> the case holding it: the open one first (a closed case is history)."""
    out = {}
    for c in sorted(cases, key=lambda c: c.get("status") == "open"):
        if c.get("dispute_id"):
            out[c["dispute_id"]] = c
    return out


def _amounts(orders: list) -> dict:
    """Order number -> its amount (the shop's own number, else PayPal's transaction id, as cases name orders)."""
    return {(o.get("order_no") or o.get("transaction_id")): _num(o.get("amount")) for o in orders}


def _currencies(orders: list) -> dict:
    """Order number -> its currency (EUR when the order doesn't say)."""
    return {(o.get("order_no") or o.get("transaction_id")): o.get("currency") or "EUR" for o in orders}


def links(cases: list, disputes: list, orders: list) -> dict:
    """Dispute id -> the case it belongs to: the case holding it (the open one first), or an open case nothing has
    linked yet whose order IS that dispute's PayPal transaction (CaseStore.link_disputes links it on the next case
    view; here it is only read, so the morning screen never writes). A card or bank order never matches."""
    held = _dispute_of_case(cases)
    tx_of = {(o.get("order_no") or o.get("transaction_id")): o.get("transaction_id") for o in orders}
    taken = {id(c) for c in held.values()}
    for d in disputes:
        tx = _tx(d)
        if d["dispute_id"] in held or d.get("status") == "RESOLVED" or not tx:
            continue
        c = next((c for c in cases if c.get("status") == "open" and not c.get("dispute_id") and id(c) not in taken
                  and c.get("order_no") and tx_of.get(c["order_no"]) == tx), None)
        if c is not None:
            held[d["dispute_id"]] = c
            taken.add(id(c))
    return held


def came_in(cases: list, disputes: list, orders: list, today: date, review_of=lambda did: None) -> dict:
    """I see: every problem something came in on since yesterday, one row each (a case and its PayPal dispute are
    one row), nearest PayPal deadline first, then the shop's own inquiries in the order they came in.
    `review_of(decision id)`: one line on what Second Look recommends there, or None."""
    start = since(today)
    by_id = {d["dispute_id"]: d for d in disputes}
    held = links(cases, disputes, orders)
    of_case = {id(c): by_id[did] for did, c in held.items() if did in by_id}   # a dispute's row is its case's
    amount_of, currency_of = _amounts(orders), _currencies(orders)
    rows, counts, messages = [], {ch: 0 for ch in CHANNEL_ORDER}, 0
    for c in cases:
        ins = [x for x in c.get("timeline", []) if x.get("direction") == "in" and (x.get("at") or "") >= start]
        d = of_case.get(id(c))
        new_dispute = d is not None and _at(d.get("create_time")) >= start
        wrote = _buyer_since(d, start) if d is not None and not new_dispute else []
        if not ins and not new_dispute and not wrote:
            continue
        for x in ins:
            counts[x["channel"]] = counts.get(x["channel"], 0) + (x["channel"] != "paypal")
        chans = [ch for ch in CHANNEL_ORDER if any(x["channel"] == ch for x in ins)]
        if d is not None and "paypal" not in chans:
            chans.append("paypal")
        decision = d["dispute_id"] if d is not None else c["id"]
        rows.append({"case_id": c["id"], "dispute_id": d["dispute_id"] if d is not None else c.get("dispute_id"),
                     "link": f"/c/{c['id']}",
                     "decision_id": decision, "channels": chans, "who": c["customer"].get("name") or c["customer"].get("email"),
                     "summary": c["problem"].get("summary") or KIND_LABEL.get(c["problem"].get("kind"), ""),
                     # whose words the summary is: Second Look's AI's reading, or the customer's own
                     "summary_by": "ai" if (c.get("sorted") or {}).get("by") == "ai"
                     else "call" if _opened_by_call(c) else "customer",
                     "order_no": c.get("order_no"),
                     "amount": _num(d["dispute_amount"]["value"]) if d else amount_of.get(c.get("order_no"), 0.0),
                     "currency": (d["dispute_amount"].get("currency_code") if d else currency_of.get(c.get("order_no")))
                     or "EUR",
                     "status": c.get("status"),
                     "first": min([x["at"] for x in ins] + ([_at(d.get("create_time"))] if new_dispute else []) + wrote),
                     "days_left": ledger.days_left(d, today) if d is not None and d.get("status") != "RESOLVED" else None,
                     "review": review_of(decision)})
    for d in disputes:
        opened = _at(d.get("create_time"))
        wrote = [] if opened >= start else _buyer_since(d, start)
        if opened < start and not wrote:
            continue
        counts["paypal"] += 1 if opened >= start else len(wrote)   # a dispute opened, or a buyer's new message
        messages += len(wrote)
        if d["dispute_id"] in held:
            continue
        rows.append({"case_id": None, "dispute_id": d["dispute_id"], "link": f"/d/{d['dispute_id']}",
                     "decision_id": d["dispute_id"], "channels": ["paypal"], "who": _buyer_name(d),
                     "summary": _first_message(d), "summary_by": "customer",
                     "order_no": _tx(d), "amount": _num(d["dispute_amount"]["value"]),
                     "currency": d["dispute_amount"].get("currency_code") or "EUR",
                     "status": "open" if d.get("status") != "RESOLVED" else "closed", "first": wrote[0] if wrote else opened,
                     "days_left": ledger.days_left(d, today) if d.get("status") != "RESOLVED" else None,
                     "review": review_of(d["dispute_id"])})
    rows.sort(key=lambda r: (r["days_left"] is None, r["days_left"] if r["days_left"] is not None else 0, r["first"]))
    return {"since": start, "rows": rows, "counts": counts, "paypal_messages": messages,
            "orders": sum(1 for o in orders if (o.get("date") or "") >= start[:10])}


def channel_words(counts: dict) -> list:
    """("📞", "calls", n)-style labels for the chips, in CHANNEL_ORDER: plural words for the counts."""
    nouns = {"call": ("call", "calls"), "email": ("email", "emails"), "form": ("web form", "web forms"),
             "paypal": ("PayPal dispute", "PayPal disputes")}
    return [(ch, nouns[ch][counts.get(ch, 0) != 1], counts.get(ch, 0)) for ch in CHANNEL_ORDER if ch in CHANNEL_LABEL]


def open_items(cases: list, disputes: list, orders: list, today: date | None = None) -> list:
    """Everything still open, once each: every open PayPal dispute (a case holding one is answered on it), and every
    open shop inquiry. Each with its decision id (whose assignment it is), who it is about and what is at stake.
    `today`: with it, each item says the days left on its PayPal deadline (None for an inquiry)."""
    held = links(cases, disputes, orders)
    linked = {id(c) for c in held.values()}
    amount_of, currency_of = _amounts(orders), _currencies(orders)
    out = []
    for d in disputes:
        if d.get("status") == "RESOLVED":
            continue
        c = held.get(d["dispute_id"])
        out.append({"id": d["dispute_id"], "link": f"/c/{c['id']}" if c else f"/d/{d['dispute_id']}",
                    "who": (c or {}).get("customer", {}).get("name") or _buyer_name(d),
                    "summary": (c or {}).get("problem", {}).get("summary") or _first_message(d),
                    "amount": _num(d["dispute_amount"]["value"]), "currency": d["dispute_amount"].get("currency_code") or "EUR",
                    "days_left": ledger.days_left(d, today) if today else None})
    for c in cases:
        if c.get("status") == "open" and not c.get("dispute_id") and id(c) not in linked:
            out.append({"id": c["id"], "link": f"/c/{c['id']}", "who": c["customer"].get("name") or c["customer"].get("email"),
                        "summary": c["problem"].get("summary") or "", "amount": amount_of.get(c.get("order_no"), 0.0),
                        "currency": currency_of.get(c.get("order_no")) or "EUR", "days_left": None})
    return out


def who_has(items: list, assigned: dict, team: dict) -> dict:
    """I manage: for each person of the team (in the shop's own order), the open items they have and the handoffs
    waiting for them; what nobody has; every handoff. `assigned`: decision id -> {"to", "handoff"}."""
    if team.get("solo"):
        return {"solo": True, "total": len(items), "people": [], "unassigned": [], "handoffs": []}
    people = [p for p in team.get("people", []) if isinstance(p, dict) and p.get("id")]
    ids = {p["id"] for p in people}
    rows = {p["id"]: {"id": p["id"], "name": p.get("name") or p["id"], "role": p.get("role") or "", "items": [],
                      "waiting": [], "passed_on": 0} for p in people}
    unassigned, handoffs = [], []
    for it in items:
        a = assigned.get(it["id"]) or {}
        to, hand = a.get("to"), a.get("handoff") if isinstance(a.get("handoff"), dict) else None
        if to not in ids:
            unassigned.append(it)
            continue
        rows[to]["items"].append(it)
        if hand:
            rows[to]["waiting"].append(it)
            if hand.get("from") in rows:
                rows[hand["from"]]["passed_on"] += 1
            frm = rows.get(hand.get("from")) or {"name": hand.get("from_name") or "A colleague", "role": ""}
            handoffs.append({**it, "from_name": frm["name"], "from_role": frm["role"],
                             "to_name": rows[to]["name"], "to_role": rows[to]["role"]})
    return {"solo": False, "total": len(items), "people": [rows[p["id"]] for p in people],
            "unassigned": unassigned, "handoffs": handoffs}


# Claims: PayPal's high-volume line comes onto the morning screen when this few more would cross it, or once crossed.
NEAR_LINE = 3


def needs_you(me: str | None, head: bool, items: list, assigned: dict, team: dict, handled=(), failed=(), hv=None,
              states=None) -> list:
    """The morning screen's first block: what needs this person now. Their cases, nearest PayPal deadline first (a
    handoff to them says who passed it); the calls nobody could transcribe (anyone listens); and for the head of
    customer care, Second Look's AI's answers nobody checked yet, and PayPal's high-volume line when it is near or
    crossed. In a team of one every open case is the seller's. `items`: open_items(..., today); `assigned`: decision
    id -> {"to", "handoff"}; `handled`: what Second Look's AI answered on its own, not checked yet.
    `states`: decision id -> case state (web.case_state); a case that isn't the person's move waits in its own bucket
    (waiting())."""
    solo = bool(team.get("solo"))
    people = {p["id"]: p for p in team.get("people", []) if isinstance(p, dict) and p.get("id")}
    checks = {h.get("id") for h in handled} if head else set()     # a case that is also a check shows once, as the check
    mine = []
    for it in items:
        a = assigned.get(it["id"]) or {}
        if (not solo and (not me or a.get("to") != me)) or it["id"] in checks:
            continue
        st = (states or {}).get(it["id"])
        if st is not None and st["state"] != "your_move":
            continue            # answered, or PayPal's move: it waits in its own bucket, not here
        hand = a.get("handoff") if isinstance(a.get("handoff"), dict) else None
        frm = (people.get(hand.get("from")) or {}) if hand else {}
        mine.append({**it, "kind": "case", "state": st,
                     "from_name": (frm.get("name") or hand.get("from_name") or "A colleague") if hand else None,
                     "from_role": (frm.get("role") or "") if hand else None})
    mine.sort(key=lambda x: (x.get("days_left") is None, x.get("days_left") or 0))
    out = mine + ([{"kind": "calls", "wavs": list(failed)}] if failed else [])
    if head:
        out += [{**h, "ai_kind": h.get("kind"), "kind": "ai"} for h in handled]
        if hv and hv.get("counts") and (hv.get("high_volume") or hv.get("claims_to_threshold", NEAR_LINE + 1) <= NEAR_LINE):
            out.append({**hv, "kind": "line"})
    return out


def waiting(me: str | None, head: bool, items: list, assigned: dict, team: dict, states: dict, ai_ids=()) -> dict:
    """Today's other buckets (spec 2026-10-30, Part 3): this person's cases that wait for the customer or for PayPal,
    or are done though still open in PayPal's list (the demo's simulated confirmation). The head of customer care also
    sees what Second Look's AI answered (`ai_ids`): it answers for them. In a team of one, every case is the seller's.
    Each row is open_items' row with its "state"; the nearest date first."""
    solo = bool(team.get("solo"))
    out = {"waiting_customer": [], "waiting_paypal": [], "done": []}
    for it in items:
        st = states.get(it["id"])
        if not st or st["state"] not in out:
            continue
        if solo or (me and (assigned.get(it["id"]) or {}).get("to") == me) or (head and it["id"] in ai_ids):
            out[st["state"]].append({**it, "state": st})
    for k in out:
        out[k].sort(key=lambda x: (x["state"]["until"] is None, x["state"]["until"] or date.max))
    return out


def closed_today(cases: list, orders: list, today: date, keep) -> list:
    """Cases closed on the shop's today or later (the demo's clicks are stamped with the computer's date, after the
    demo's fixed today), as open_items rows. `keep(decision id)`: whether this person sees it (web decides)."""
    amount_of, currency_of = _amounts(orders), _currencies(orders)
    out = []
    for c in cases:
        did = c.get("dispute_id") or c["id"]
        if c.get("status") == "open" or _closed_at(c)[:10] < today.isoformat() or not keep(did):
            continue
        out.append({"id": did, "link": f"/c/{c['id']}",
                    "who": c["customer"].get("name") or c["customer"].get("email"),
                    "summary": c["problem"].get("summary") or "", "amount": amount_of.get(c.get("order_no"), 0.0),
                    "currency": currency_of.get(c.get("order_no")) or "EUR", "days_left": None,
                    "state": {"state": "done", "label": "Done", "whose": None, "why": "Closed.", "until": None,
                              "then": "", "paypal": bool(c.get("dispute_id"))}})
    return out


def _closed_at(c: dict) -> str:
    """When a case closed: as recorded, else its last timeline entry (cases closed before closed_at was kept)."""
    return c.get("closed_at") or max((x.get("at") or "" for x in c.get("timeline", [])), default="")


def period(cases: list, disputes: list, orders: list, start: str, end: str | None, policy: dict | None, answers=(),
           high_volume: bool = False, currency: str = "EUR") -> dict:
    """What happened from `start` up to `end` (None: no end, as this month has none): the flows a period is compared on
    (Numbers), every channel. `answers`: when each answer to a PayPal dispute was sent from Second Look (an inquiry's
    answers are on its case already). Staff time is an estimate (cases.staff_time); dispute fees are estimated from
    PayPal's fee table, at the fee `high_volume` says (PayPal's line as it stood at the period's end)."""
    held = set(links(cases, disputes, orders))
    inside = lambda at: _within(at or "", start, end)  # noqa: E731
    ordered = sum(1 for o in orders if _within(o.get("date") or "", start[:10], end and end[:10]))
    new_cases = [c for c in cases if inside(c.get("opened"))]
    new_disputes = [d for d in disputes if inside(_at(d.get("create_time"))) and d["dispute_id"] not in held]
    solved = [c for c in cases if c.get("status") != "open" and not c.get("dispute_id") and inside(_closed_at(c))]
    st = staff_time(policy)
    entries = [x for c in cases for x in c.get("timeline", []) if inside(x.get("at"))]
    # a reply Second Look's AI sent on its own took nobody's minutes: it is not staff time
    written = sum(1 for x in entries if x.get("direction") == "out" and x.get("channel") != "call" and not x.get("autopilot"))
    written += sum(1 for a in answers if inside(a))
    call_min = sum(_num(x.get("minutes")) for x in entries if x.get("channel") == "call" and x.get("direction") in ("in", "out"))
    minutes = written * st["reply_minutes"] + call_min
    # a refund a person cancelled moved no money
    money = [x for c in cases for x in c.get("money", []) if inside(x.get("at")) and x.get("status") != "cancelled"]
    back_cases = round(sum(_num(x.get("amount")) for x in money if x.get("kind") in BACK), 2)
    resolved = [d for d in disputes if d.get("status") == "RESOLVED" and inside(_at(d.get("update_time") or d.get("create_time")))]
    back_paypal = round(sum(ledger.refunded(d) for d in resolved), 2)
    # the same order given back on both sides (a refund logged on a case, and PayPal's): flagged, not hidden in a sum
    on_cases = {c.get("order_no") for c in cases for x in c.get("money", [])
                if c.get("order_no") and x.get("kind") in BACK and inside(x.get("at")) and x.get("status") != "cancelled"}
    both_sides = sorted(on_cases & {_tx(d) for d in resolved if ledger.refunded(d) > 0})
    standard, hv_fee = DISPUTE_FEE.get(currency, (0.0, 0.0))
    fees = sum(hv_fee if high_volume else standard if ledger.outcome(d) in ("lost_claim", "lost_no_reply") else 0
               for d in resolved if escalated(d))
    fees = round(fees + sum(_num(x.get("amount")) for x in money if x.get("kind") == "fee"), 2)
    return {"from": start, "to": end, "orders": ordered, "requests": len(new_cases) + len(new_disputes),
            "requests_by_channel": _first_channels(new_cases, len(new_disputes)),
            "solved_before_dispute": len(solved),
            "ai_answered": sum(1 for x in entries if x.get("direction") == "out" and x.get("autopilot")),
            "answers": written, "minutes": minutes,
            "calls": sum(1 for x in entries if x.get("channel") == "call" and x.get("direction") == "in"),
            "call_minutes": round(call_min, 2),
            "hourly_cost": st["hourly_cost"], "reply_minutes": st["reply_minutes"],
            "staff_cost": round(minutes / 60 * st["hourly_cost"], 2),
            "back_cases": back_cases, "back_paypal": back_paypal, "back": round(back_cases + back_paypal, 2),
            "both_sides": both_sides, "fees": fees, "currency": currency}


def month(cases: list, disputes: list, orders: list, today: date, policy: dict | None, answers=(),
          currency: str = "EUR") -> dict:
    """This month so far, every channel (period from the 1st, no end), and what holds right now: what the open cases
    could still cost, and PayPal's high-volume line."""
    hv = ledger.overview(disputes, orders, today, currency)["high_volume"]
    out = period(cases, disputes, orders, month_start(today), None, policy, answers, hv["high_volume"], currency)
    linked = {id(c) for c in links(cases, disputes, orders).values()}
    ex = ledger.exposure(disputes, today, hv["high_volume"], currency)
    amount_of = _amounts(orders)
    open_inq = [c for c in cases if c.get("status") == "open" and not c.get("dispute_id") and c.get("order_no")
                and id(c) not in linked]
    # what already went back on each order, from every case on it (closed ones too): refunds and goods
    given = {}
    for c in cases:
        for x in c.get("money", []):
            if c.get("order_no") and x.get("kind") in BACK + ("replace",) and x.get("status") != "cancelled":
                given[c["order_no"]] = given.get(c["order_no"], 0.0) + _num(x.get("amount"))
    inq_stake = round(sum(max(0.0, amount_of.get(c["order_no"], 0.0) - given.get(c["order_no"], 0.0))
                          for c in open_inq), 2)
    return {**out, "open_disputes_most": ex["all_lost"], "open_inquiries_most": inq_stake,
            "could_still_cost": round(ex["all_lost"] + inq_stake, 2), "high_volume": hv}


def _first_channels(new_cases: list, new_disputes: int) -> dict:
    """How this month's requests first came in: each case by its first message's channel, a dispute with no
    case by PayPal."""
    out = {ch: 0 for ch in CHANNEL_ORDER}
    for c in new_cases:
        first = next((x["channel"] for x in sorted(c.get("timeline", []), key=lambda x: x.get("at") or "")
                      if x.get("direction") == "in"), "paypal" if c.get("dispute_id") else None)
        if first in out:
            out[first] += 1
    out["paypal"] += new_disputes
    return out
