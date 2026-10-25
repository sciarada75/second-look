"""The books: every money event of the shop's cases and PayPal disputes, as the shop's accounting needs the facts.

Decision 5: accounting gets the facts, never the credit note. Each event says what happened to money or goods,
for which order and invoice, how much, any fee, whether the item came back or was lost, when, who approved it and
on which channel. The credit note is a legal document the accounting system or the accountant makes from these.

Two ways out: each event Second Look itself causes goes live to the shop's bookkeeping (web.post_books, to
SECONDLOOK_BOOKS_URL), and every month's events, PayPal's own outcomes included, export as one CSV. Pure code:
nothing here calls PayPal or a model.
"""
from __future__ import annotations

import csv
import io

from . import ledger
from .costs import DISPUTE_FEE, escalated

COLUMNS = ["date", "kind", "order_no", "invoice_no", "amount", "currency", "fees", "item", "approved_by", "channel",
           "case_id", "dispute_id", "status"]
KIND = {"refund": "refund", "partial_refund": "partial refund", "replace": "replacement", "fee": "fee"}
# What happened to the item: back at the shop, lost on the way, with the customer, or not known.
BACK, LOST, KEPT, UNKNOWN = "back at the shop", "lost", "with the customer", "not known"


def item_state(kind: str | None, order: dict | None) -> str:
    """Where the item is, from the courier's record of the order and what the case is about."""
    o = order or {}
    ret = o.get("return") or {}
    if ret.get("status") == "DELIVERED" and "shop" in str(ret.get("delivered_to") or "shop").lower():
        return BACK
    if kind == "refund_missing":
        return BACK                                    # the customer returned it: that is what the refund is for
    if kind == "not_received":
        return KEPT if (o.get("tracking") or {}).get("status") == "DELIVERED" else LOST
    return KEPT if kind in ("not_as_described", "wrong_size") else UNKNOWN


def dispute_item(reason: str | None, order: dict | None = None) -> str:
    """Where the item is, for a PayPal dispute no case of the shop tells about: back at the shop when the courier
    brought its return there, else from what the buyer says (never received: lost; refund not processed: back)."""
    ret = (order or {}).get("return") or {}
    if ret.get("status") == "DELIVERED" and "shop" in str(ret.get("delivered_to") or "shop").lower():
        return BACK
    return {"MERCHANDISE_OR_SERVICE_NOT_RECEIVED": LOST, "CREDIT_NOT_PROCESSED": BACK}.get(reason, UNKNOWN)


def _channel_at(c: dict, at: str) -> str:
    """The channel the shop's answer went out on when the money moved: the "out" entry of that minute, else the
    channel the customer last used before it."""
    out = [x for x in c.get("timeline", []) if x.get("direction") == "out" and x.get("at") == at]
    if out:
        return out[-1].get("channel") or ""
    ins = [x for x in c.get("timeline", []) if x.get("direction") == "in" and (x.get("at") or "") <= (at or "")]
    return ins[-1]["channel"] if ins else ""


def case_events(c: dict, order: dict | None, invoice: str | None, currency: str = "EUR") -> list:
    """The money events one case logged: refunds, partial refunds, replacements, fees, each as a row of the books."""
    rows = []
    for m in c.get("money", []):
        kind = KIND.get(m.get("kind"))
        if not kind:
            continue
        rows.append({"date": m.get("at") or "", "kind": kind, "order_no": c.get("order_no") or "", "invoice_no": invoice or "",
                     "amount": round(float(m.get("amount") or 0), 2), "currency": (order or {}).get("currency") or currency,
                     "fees": 0.0, "item": item_state(c["problem"].get("kind"), order) if kind != "fee" else "",
                     "approved_by": m.get("by") or "", "channel": _channel_at(c, m.get("at") or ""),
                     "case_id": c.get("id") or "", "dispute_id": c.get("dispute_id") or "",
                     "status": m.get("status") or "logged"})
    return rows


def dispute_events(d: dict, invoice: str | None, handled_by: str | None, high_volume: bool) -> list:
    """What a resolved PayPal dispute moved: PayPal's refund to the buyer and the dispute fee, from PayPal's outcome
    (the fee estimated from PayPal's fee table, as the Overview estimates it)."""
    if d.get("status") != "RESOLVED":
        return []
    cur = d["dispute_amount"].get("currency_code", "EUR")
    standard, hv = DISPUTE_FEE.get(cur, (0.0, 0.0))
    fee = (hv if high_volume else standard if ledger.outcome(d) in ("lost_claim", "lost_no_reply") else 0.0) \
        if escalated(d) else 0.0
    back = ledger.refunded(d)
    if not back and not fee:
        return []
    tx = ((d.get("disputed_transactions") or [{}])[0]).get("seller_transaction_id") or ""
    item = dispute_item(d.get("reason"))
    return [{"date": (d.get("update_time") or d.get("create_time") or "")[:16], "kind": "PayPal refund" if back else "PayPal fee",
             "order_no": tx, "invoice_no": invoice or "", "amount": round(back, 2), "currency": cur, "fees": round(fee, 2),
             "item": item if back else "", "approved_by": handled_by or "", "channel": "paypal", "case_id": "",
             "dispute_id": d["dispute_id"], "status": ledger.OUTCOME_LABEL.get(ledger.outcome(d), "resolved")}]


def for_month(rows: list, month: str) -> list:
    """The rows of one month ("2026-10"), oldest first."""
    return sorted((r for r in rows if str(r["date"]).startswith(month)), key=lambda r: (r["date"], r["kind"]))


NUMBERS = ("amount", "fees")
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _text_cell(v) -> str:
    """A text cell as a spreadsheet can't run it: one starting like a formula (=, +, -, @, a tab, a carriage
    return) gets a leading apostrophe, and a line break inside a cell is a space (it would break the file)."""
    t = "" if v is None else str(v)
    if t.startswith(_FORMULA):
        t = "'" + t
    return t.replace("\r", " ").replace("\n", " ")


def csv_text(rows: list) -> str:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({**{k: _text_cell(r.get(k)) for k in COLUMNS if k not in NUMBERS},
                    "amount": f'{r["amount"]:.2f}', "fees": f'{r["fees"]:.2f}'})
    return out.getvalue()
