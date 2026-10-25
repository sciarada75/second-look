"""The morning screen, "I see, I manage, I know": grouping and arithmetic over what the shop already holds (its
cases, PayPal's disputes, its orders, who has which case). Nothing here calls PayPal or a model.

  I see     everything that came in since yesterday, from every channel, in one list, nearest deadline first,
            with the orders that came in over the same time beside it (problems read against sales);
  I manage  who has which open case, what nobody has yet, and what waits for a colleague after a handoff;
  I know    this month, every channel: requests, solved before any PayPal dispute, staff time (estimated),
            money given back, fees, what the open cases could still cost.

"Since yesterday" starts at 00:00 on the day before the shop's today and has no end: in the demo shop (today is
20 Oct 2026) it is everything from 19 Oct on, including anything a person does now, whatever the clock says.
"This month" starts at 00:00 on the 1st of the shop's today's month, with no end either. Times are compared
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


def open_items(cases: list, disputes: list, orders: list) -> list:
    """Everything still open, once each: every open PayPal dispute (a case holding one is answered on it), and every
    open shop inquiry. Each with its decision id (whose assignment it is), who it is about and what is at stake."""
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
                    "amount": _num(d["dispute_amount"]["value"]), "currency": d["dispute_amount"].get("currency_code") or "EUR"})
    for c in cases:
        if c.get("status") == "open" and not c.get("dispute_id") and id(c) not in linked:
            out.append({"id": c["id"], "link": f"/c/{c['id']}", "who": c["customer"].get("name") or c["customer"].get("email"),
                        "summary": c["problem"].get("summary") or "", "amount": amount_of.get(c.get("order_no"), 0.0),
                        "currency": currency_of.get(c.get("order_no")) or "EUR"})
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


def _closed_at(c: dict) -> str:
    """When a case closed: as recorded, else its last timeline entry (cases closed before closed_at was kept)."""
    return c.get("closed_at") or max((x.get("at") or "" for x in c.get("timeline", [])), default="")


def month(cases: list, disputes: list, orders: list, today: date, policy: dict | None, answers=(),
          currency: str = "EUR") -> dict:
    """I know: this month, every channel. `answers`: when each answer to a PayPal dispute was sent from Second Look
    (an inquiry's answers are on its case already). Staff time is an estimate (cases.staff_time); dispute fees are
    estimated from PayPal's fee table, as the Overview's."""
    m = month_start(today)
    held_by = links(cases, disputes, orders)
    held = set(held_by)
    linked = {id(c) for c in held_by.values()}
    ordered = sum(1 for o in orders if (o.get("date") or "") >= m[:10])
    new_cases = [c for c in cases if (c.get("opened") or "") >= m]
    new_disputes = [d for d in disputes if _at(d.get("create_time")) >= m and d["dispute_id"] not in held]
    solved = [c for c in cases if c.get("status") != "open" and not c.get("dispute_id") and _closed_at(c) >= m]
    st = staff_time(policy)
    entries = [x for c in cases for x in c.get("timeline", []) if (x.get("at") or "") >= m]
    written = sum(1 for x in entries if x.get("direction") == "out" and x.get("channel") != "call")
    written += sum(1 for a in answers if (a or "") >= m)
    call_min = sum(_num(x.get("minutes")) for x in entries if x.get("channel") == "call" and x.get("direction") in ("in", "out"))
    minutes = written * st["reply_minutes"] + call_min
    money = [x for c in cases for x in c.get("money", []) if (x.get("at") or "") >= m]
    back_cases = round(sum(_num(x.get("amount")) for x in money if x.get("kind") in BACK), 2)
    resolved = [d for d in disputes if d.get("status") == "RESOLVED" and _at(d.get("update_time") or d.get("create_time")) >= m]
    back_paypal = round(sum(ledger.refunded(d) for d in resolved), 2)
    # the same order given back on both sides (a refund logged on a case, and PayPal's): flagged, not hidden in a sum
    on_cases = {c.get("order_no") for c in cases for x in c.get("money", [])
                if c.get("order_no") and x.get("kind") in BACK and (x.get("at") or "") >= m}
    both_sides = sorted(on_cases & {_tx(d) for d in resolved if ledger.refunded(d) > 0})
    hv = ledger.overview(disputes, orders, today, currency)["high_volume"]
    standard, hv_fee = DISPUTE_FEE.get(currency, (0.0, 0.0))
    fees = sum(hv_fee if hv["high_volume"] else standard if ledger.outcome(d) in ("lost_claim", "lost_no_reply") else 0
               for d in resolved if escalated(d))
    fees = round(fees + sum(_num(x.get("amount")) for x in money if x.get("kind") == "fee"), 2)
    ex = ledger.exposure(disputes, today, hv["high_volume"], currency)
    amount_of = _amounts(orders)
    open_inq = [c for c in cases if c.get("status") == "open" and not c.get("dispute_id") and c.get("order_no")
                and id(c) not in linked]
    # what already went back on each order, from every case on it (closed ones too): refunds and goods
    given = {}
    for c in cases:
        for x in c.get("money", []):
            if c.get("order_no") and x.get("kind") in BACK + ("replace",):
                given[c["order_no"]] = given.get(c["order_no"], 0.0) + _num(x.get("amount"))
    inq_stake = round(sum(max(0.0, amount_of.get(c["order_no"], 0.0) - given.get(c["order_no"], 0.0))
                          for c in open_inq), 2)
    return {"from": m, "orders": ordered, "requests": len(new_cases) + len(new_disputes),
            "requests_by_channel": _first_channels(new_cases, len(new_disputes)),
            "solved_before_dispute": len(solved), "answers": written, "minutes": minutes,
            "calls": sum(1 for x in entries if x.get("channel") == "call" and x.get("direction") == "in"),
            "call_minutes": round(call_min, 2),
            "hourly_cost": st["hourly_cost"], "reply_minutes": st["reply_minutes"],
            "staff_cost": round(minutes / 60 * st["hourly_cost"], 2),
            "back_cases": back_cases, "back_paypal": back_paypal, "back": round(back_cases + back_paypal, 2),
            "both_sides": both_sides,
            "fees": fees, "open_disputes_most": ex["all_lost"], "open_inquiries_most": inq_stake,
            "could_still_cost": round(ex["all_lost"] + inq_stake, 2), "high_volume": hv, "currency": currency}


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
