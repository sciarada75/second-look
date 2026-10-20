"""The shop's dispute record: how cases ended, what is waiting, and one customer's history.

Input: full PayPal dispute objects and the shop's orders ({payer_id, email, name, date, amount}).
Same code for the live sandbox and the demo shop; nothing here calls PayPal or a model.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from .costs import DISPUTE_FEE, escalated, high_volume

# How a closed case ended, from PayPal's outcome_code and outcome_reason (Disputes API v1).
OUTCOME_LABEL = {
    "won": "Won", "withdrew": "Buyer withdrew", "closed": "Closed, no decision",
    "settled_offer": "Settled with an offer", "refunded": "Refunded by you",
    "covered": "PayPal covered it", "lost_claim": "Lost at claim", "lost_no_reply": "Lost: no reply in time",
}
# Kept: the money stayed with the shop. The order matters only for display.
KEPT = ("won", "withdrew", "closed")
NO_REPLY = ("NO_SELLER_RESPONSE", "SELLER_NOT_REACHABLE", "NO_SELLER_RESPONSE_FOR_ADDITIONAL_INFO_REQUEST")
OFFER = ("PARTIAL_REFUND_OFFER_ACCEPTED", "INQUIRY_OFFER_PARTIAL_REFUND", "INQUIRY_OFFER_ITEM_REPLACED",
         "INQUIRY_OFFER_REFUND_WITH_ITEM_RETURN", "INQUIRY_OFFER_REFUND_WITH_REPLACEMENT")
REASON_SHORT = {
    "MERCHANDISE_OR_SERVICE_NOT_RECEIVED": "Not received",
    "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED": "Not as described",
    "CREDIT_NOT_PROCESSED": "Refund not received",
    "UNAUTHORISED": "Unauthorised",
}
INQUIRY_DAYS = 20   # the buyer must escalate within 20 days or PayPal closes the dispute (Purchase Protection)
ANSWER_DAYS = 10    # the seller should answer within 10 days (PayPal Help HELP1083)


def _day(iso) -> date | None:
    try:
        return datetime.strptime(str(iso)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def buyer_of(d: dict) -> str | None:
    return ((d.get("disputed_transactions") or [{}])[0].get("buyer") or {}).get("payer_id")


def amount_of(d: dict) -> float:
    return float(d["dispute_amount"]["value"])


def outcome(d: dict) -> str | None:
    """None while the case is open."""
    if d.get("status") != "RESOLVED":
        return None
    o = d.get("dispute_outcome") or {}
    code = o.get("outcome_code")
    reason = (o.get("outcome_reason") or "").upper()
    if code == "RESOLVED_SELLER_FAVOUR":
        return "won"
    if code == "CANCELED_BY_BUYER":
        return "withdrew"
    if code == "RESOLVED_WITH_PAYOUT":
        return "covered"
    if code == "RESOLVED_BUYER_FAVOUR":
        if reason in NO_REPLY:
            return "lost_no_reply"
        if reason in OFFER:
            return "settled_offer"
        return "lost_claim" if escalated(d) else "refunded"
    return "closed"  # NONE, or no outcome: PayPal closed it without a decision


def refunded(d: dict) -> float:
    o = d.get("dispute_outcome") or {}
    if o.get("amount_refunded"):
        return float(o["amount_refunded"]["value"])
    return amount_of(d) if outcome(d) in ("refunded", "lost_claim", "lost_no_reply") else 0.0


def if_nobody_answers(d: dict, today: date) -> str:
    """What PayPal does next if nobody acts, in PayPal's own terms."""
    stage, status = d.get("dispute_life_cycle_stage"), d.get("status")
    due = _day(d.get("seller_response_due_date"))
    if status == "UNDER_REVIEW":
        return "PayPal is deciding. It usually takes about 10 days."
    if stage == "INQUIRY" and status == "WAITING_FOR_SELLER_RESPONSE":
        when = f"by {due:%d %b}" if due else f"within {ANSWER_DAYS} days"
        return f"Answer {when}. If you don't and the buyer escalates, PayPal decides for the buyer."
    if stage == "INQUIRY":
        opened = _day(d.get("create_time"))
        close = opened + timedelta(days=INQUIRY_DAYS) if opened else None
        return ("If the buyer doesn't escalate " + (f"by {close:%d %b}" if close else "within 20 days")
                + ", PayPal closes the dispute and it can't be reopened.")
    if status == "WAITING_FOR_SELLER_RESPONSE":
        return "Answer" + (f" by {due:%d %b}" if due else "") + ", or PayPal closes the claim in the buyer's favour."
    bdue = _day(d.get("buyer_response_due_date"))
    return "If the buyer doesn't answer" + (f" by {bdue:%d %b}" if bdue else "") + ", PayPal closes it in your favour."


def days_left(d: dict, today: date) -> int | None:
    if d.get("status") == "WAITING_FOR_SELLER_RESPONSE":
        due = _day(d.get("seller_response_due_date"))
    elif d.get("dispute_life_cycle_stage") == "INQUIRY":
        opened = _day(d.get("create_time"))
        due = opened + timedelta(days=INQUIRY_DAYS) if opened else None
    else:
        due = _day(d.get("buyer_response_due_date"))
    return (due - today).days if due else None


def quarter_window(today: date):
    """PayPal's high-volume test looks at the previous three full calendar months."""
    first = today.replace(day=1)
    m, y = first.month - 3, first.year
    if m < 1:
        m, y = m + 12, y - 1
    return date(y, m, 1), first


WINDOW_DAYS = 90


def overview(disputes: list, orders: list, today: date, currency: str = "EUR") -> dict:
    """The last 90 days at a glance; the high-volume test on PayPal's own window (previous full quarter)."""
    first = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    recent = [d for d in disputes if d.get("create_time", "")[:10] >= first]
    closed = [d for d in recent if d.get("status") == "RESOLVED"]
    open_ = [d for d in disputes if d.get("status") != "RESOLVED"]
    counts = {k: 0 for k in OUTCOME_LABEL}
    for d in closed:
        counts[outcome(d)] += 1
    standard = DISPUTE_FEE.get(currency, (0, 0))[0]
    start, end = quarter_window(today)
    q_claims = sum(1 for d in disputes if escalated(d) and d.get("reason") != "UNAUTHORISED"
                   and start <= (_day(d.get("create_time")) or today) < end)
    q_sales = sum(1 for o in orders if start <= (_day(o["date"]) or today) < end)
    hv = high_volume(q_claims, q_sales)
    # Estimated from PayPal's fee table: the dispute object doesn't carry the fee. Standard fee on a lost
    # claim only; the high-volume fee on every claim, won or lost.
    hv_fee = DISPUTE_FEE.get(currency, (0, 0))[1]
    fees_paid = sum(hv_fee if hv["high_volume"] else standard if outcome(d) in ("lost_claim", "lost_no_reply") else 0
                    for d in closed if escalated(d))
    waiting = []
    for d in open_:
        waiting.append({"dispute_id": d["dispute_id"],
                        "buyer": ((d.get("disputed_transactions") or [{}])[0].get("buyer") or {}).get("name"), "on": "you" if d.get("status") == "WAITING_FOR_SELLER_RESPONSE"
                        else "PayPal" if d.get("status") == "UNDER_REVIEW" else "the buyer",
                        "reason": REASON_SHORT.get(d.get("reason"), d.get("reason")),
                        "amount": amount_of(d), "days_left": days_left(d, today),
                        "next": if_nobody_answers(d, today), "stage": d.get("dispute_life_cycle_stage")})
    waiting.sort(key=lambda w: (w["on"] != "you", w["days_left"] if w["days_left"] is not None else 99))
    return {
        "handled": len(closed), "open": len(open_), "counts": counts,
        "kept": round(sum(amount_of(d) for d in closed if outcome(d) in KEPT), 2),
        "refunded": round(sum(refunded(d) for d in closed), 2),
        "fees_paid": round(fees_paid, 2), "fee_standard": standard,
        "settled_before_claim": sum(1 for d in closed if not escalated(d)),
        "escalated": sum(1 for d in closed if escalated(d)),
        "orders": sum(1 for o in orders if o["date"] >= first), "disputes": len(recent), "window_days": WINDOW_DAYS,
        "high_volume": hv, "quarter": (start, end), "waiting": waiting,
    }


def describe_escalations(buyer_earlier: int, buyer_escalated: int, shop_closed: int, shop_escalated: int) -> str:
    """One neutral sentence: how often this buyer took a dispute to a claim, next to the shop's usual rate."""
    if not buyer_earlier:
        return "No earlier disputes with you."
    shop = (f"Your shop: {shop_escalated} in {shop_closed} disputes went to a claim." if shop_closed
            else "Your shop has no closed disputes to compare with.")
    return (f"Took {buyer_escalated} of {buyer_earlier} earlier dispute{'s' if buyer_earlier != 1 else ''} "
            f"with you to a PayPal claim. {shop}")


def customer(key: str, disputes: list, orders: list) -> dict | None:
    """One customer's record with the shop, by PayPal payer id or email. None if unknown."""
    key = (key or "").strip().lower()
    mine = [o for o in orders if (o.get("payer_id") or "").lower() == key or (o.get("email") or "").lower() == key]
    payer = mine[0]["payer_id"] if mine else next((buyer_of(d) for d in disputes if (buyer_of(d) or "").lower() == key), None)
    if not payer:
        return None
    mine = mine or [o for o in orders if o.get("payer_id") == payer]
    theirs = sorted((d for d in disputes if buyer_of(d) == payer), key=lambda d: d.get("create_time", ""))
    closed_shop = [d for d in disputes if d.get("status") == "RESOLVED"]
    rate = len(theirs) / len(mine) if mine else None
    shop_rate = len(disputes) / len(orders) if orders else None
    name = next((o.get("name") for o in mine if o.get("name")), None) or \
        next((((d.get("disputed_transactions") or [{}])[0].get("buyer") or {}).get("name") for d in theirs), None)
    return {
        "payer_id": payer, "name": name, "email": next((o.get("email") for o in mine if o.get("email")), None),
        "orders": len(mine), "spent": round(sum(o.get("amount", 0) for o in mine), 2),
        "first_order": min((o["date"] for o in mine), default=None), "last_order": max((o["date"] for o in mine), default=None),
        "disputes": [{"dispute_id": d["dispute_id"], "opened": d.get("create_time", "")[:10],
                      "reason": REASON_SHORT.get(d.get("reason"), d.get("reason")), "amount": amount_of(d),
                      "escalated": escalated(d), "outcome": OUTCOME_LABEL.get(outcome(d), "Open")} for d in theirs],
        "escalated": sum(1 for d in theirs if escalated(d)),
        "refunded": round(sum(refunded(d) for d in theirs), 2),
        "dispute_rate": rate, "shop_dispute_rate": shop_rate,
        "times_shop_rate": (rate / shop_rate) if rate is not None and shop_rate else None,
        "escalations": describe_escalations(len(theirs), sum(1 for d in theirs if escalated(d)),
                                            len(closed_shop), sum(1 for d in closed_shop if escalated(d))),
    }
