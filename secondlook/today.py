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


def came_in(cases: list, disputes: list, orders: list, today: date, review_of=lambda did: None) -> dict:
    """I see: every problem something came in on since yesterday, one row each (a case and its PayPal dispute are
    one row), nearest PayPal deadline first, then the shop's own inquiries in the order they came in.
    `review_of(decision id)`: one line on what Second Look recommends there, or None."""
    start = since(today)
    by_id = {d["dispute_id"]: d for d in disputes}
    held = _dispute_of_case(cases)
    amount_of = _amounts(orders)
    rows, counts = [], {ch: 0 for ch in CHANNEL_ORDER}
    for c in cases:
        ins = [x for x in c.get("timeline", []) if x.get("direction") == "in" and (x.get("at") or "") >= start]
        d = by_id.get(c.get("dispute_id"))
        if d is not None and held.get(d["dispute_id"]) is not c:
            d = None                                   # the dispute's row is its open case's, not this old one's
        new_dispute = d is not None and _at(d.get("create_time")) >= start
        if not ins and not new_dispute:
            continue
        for x in ins:
            counts[x["channel"]] = counts.get(x["channel"], 0) + (x["channel"] != "paypal")
        chans = [ch for ch in CHANNEL_ORDER if any(x["channel"] == ch for x in ins)]
        if d is not None and "paypal" not in chans:
            chans.append("paypal")
        decision = c.get("dispute_id") if d is not None else c["id"]
        rows.append({"case_id": c["id"], "dispute_id": c.get("dispute_id"), "link": f"/c/{c['id']}",
                     "decision_id": decision, "channels": chans, "who": c["customer"].get("name") or c["customer"].get("email"),
                     "summary": c["problem"].get("summary") or KIND_LABEL.get(c["problem"].get("kind"), ""),
                     "order_no": c.get("order_no"),
                     "amount": _num(d["dispute_amount"]["value"]) if d else amount_of.get(c.get("order_no"), 0.0),
                     "status": c.get("status"), "first": min([x["at"] for x in ins] + ([_at(d.get("create_time"))] if new_dispute else [])),
                     "days_left": ledger.days_left(d, today) if d is not None and d.get("status") != "RESOLVED" else None,
                     "review": review_of(decision)})
    for d in disputes:
        opened = _at(d.get("create_time"))
        if opened < start:
            continue
        counts["paypal"] += 1
        if d["dispute_id"] in held:
            continue
        rows.append({"case_id": None, "dispute_id": d["dispute_id"], "link": f"/d/{d['dispute_id']}",
                     "decision_id": d["dispute_id"], "channels": ["paypal"], "who": _buyer_name(d),
                     "summary": _first_message(d), "order_no": _tx(d), "amount": _num(d["dispute_amount"]["value"]),
                     "status": "open" if d.get("status") != "RESOLVED" else "closed", "first": opened,
                     "days_left": ledger.days_left(d, today) if d.get("status") != "RESOLVED" else None,
                     "review": review_of(d["dispute_id"])})
    rows.sort(key=lambda r: (r["days_left"] is None, r["days_left"] if r["days_left"] is not None else 0, r["first"]))
    return {"since": start, "rows": rows, "counts": counts,
            "orders": sum(1 for o in orders if (o.get("date") or "") >= start[:10])}


def channel_words(counts: dict) -> list:
    """("📞", "calls", n)-style labels for the chips, in CHANNEL_ORDER: plural words for the counts."""
    nouns = {"call": ("call", "calls"), "email": ("email", "emails"), "form": ("web form", "web forms"),
             "paypal": ("PayPal dispute", "PayPal disputes")}
    return [(ch, nouns[ch][counts.get(ch, 0) != 1], counts.get(ch, 0)) for ch in CHANNEL_ORDER if ch in CHANNEL_LABEL]
