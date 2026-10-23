"""Gathers the seller's evidence for a dispute automatically, and labels where each fact came from.

Sources, in order of trust:
  1. The dispute itself (PayPal)        items, order time, seller protection, buyer messages
  2. PayPal Transaction Search          the shipping address and items PayPal holds for the order
  3. PayPal tracking (Add Tracking API) carrier, tracking number, status the seller registered
  4. PayPal disputes + Transaction Search  this buyer's disputes and orders with the shop, against the
                                         shop's usual rate (the base rate), last 90 days
  5. shop.json                          the shop's public promises: listing text, handling time, returns
  6. records/<dispute_id>.json          the seller's own notes (photos, weights, history); optional
  7. costs (costs.py)                   what refunding, settling or losing a claim would cost: PayPal's fee
                                         table, PayPal's fee on this payment, the shop's own item costs

Every fact keeps its source in records["sources"], so the judge can cite it and the seller can
check it. A source that is unavailable is reported, never invented.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib import parse

from . import ledger
from .costs import escalated, high_volume, paths


def _day_window(iso: str):
    t = datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return (t - timedelta(days=1)).strftime(fmt), (t + timedelta(days=1)).strftime(fmt)


def _iso(value):
    """PayPal's tracker returns last_updated_time as epoch milliseconds in the sandbox (seen 2026-10-17)."""
    if isinstance(value, (int, str)) and str(value).isdigit():
        return datetime.utcfromtimestamp(int(value) / 1000).strftime("%Y-%m-%dT%H:%M:%SZ")
    return value


def _transaction(pp, tx_id: str, when: str) -> dict:
    start, end = _day_window(when)
    q = parse.urlencode({"transaction_id": tx_id, "start_date": start, "end_date": end, "fields": "all"})
    details = pp._call("GET", f"/v1/reporting/transactions?{q}").get("transaction_details", [])
    return details[0] if details else {}


WINDOW_DAYS = ledger.WINDOW_DAYS


def since(now: datetime) -> datetime:
    """How far back to read: the buyer history's 90 days, or the start of PayPal's high-volume quarter
    (the three previous full calendar months), whichever is earlier."""
    q = datetime.combine(ledger.quarter_window(now.date())[0], datetime.min.time())
    return min(q, now - timedelta(days=WINDOW_DAYS))


def _orders(pp, until: datetime) -> list:
    """Payments received since since(): payer, email, name, date, amount and PayPal's fee.
    Transaction Search allows 31 days per query."""
    out, fmt, end, first = [], "%Y-%m-%dT%H:%M:%SZ", until, since(until)
    while end > first:
        start = max(end - timedelta(days=31), first)
        q = parse.urlencode({"start_date": start.strftime(fmt), "end_date": end.strftime(fmt),
                             "fields": "transaction_info,payer_info", "page_size": 500})
        for t in pp._call("GET", f"/v1/reporting/transactions?{q}").get("transaction_details", []):
            ti, pi = t["transaction_info"], t.get("payer_info", {})
            # T00xx = a payment received; funding (T19xx) and holds (T11xx) are not orders
            if ti.get("transaction_event_code", "").startswith("T00") and \
                    float(ti.get("transaction_amount", {}).get("value", 0)) > 0:
                name = pi.get("payer_name") or {}
                out.append({"payer_id": pi.get("account_id"), "email": pi.get("email_address"),
                            "name": name.get("alternate_full_name") or " ".join(
                                x for x in (name.get("given_name"), name.get("surname")) if x) or None,
                            "date": ti.get("transaction_initiation_date", "")[:10],
                            "amount": float(ti["transaction_amount"]["value"]),
                            "fee": abs(float((ti.get("fee_amount") or {}).get("value", 0))),
                            "transaction_id": ti.get("transaction_id")})
        end = start
    return out


def shop_disputes(pp, now: datetime) -> list:
    """Every dispute the shop had in the window, as full objects (the list omits buyer and outcome)."""
    first = since(now).strftime("%Y-%m-%dT%H:%M:%S")
    return [pp.get_dispute(d["dispute_id"]) for d in pp._call("GET", "/v1/customer/disputes?page_size=50").get("items", [])
            if d.get("create_time", "")[:19] >= first]


def history(dispute: dict, disputes: list, orders: list, today) -> dict:
    """This buyer against the shop's own base rate, last 90 days. A raw count means nothing: 3 disputes is a
    lot for a shop with 1,000 orders and 2 disputes, and normal where one order in three ends in a dispute."""
    buyer = ledger.buyer_of(dispute)
    if not buyer:
        return {}
    disputes, orders = ledger.in_window(disputes, orders, today)
    earlier = [d for d in disputes if ledger.buyer_of(d) == buyer and d["dispute_id"] != dispute.get("dispute_id")]
    closed = [d for d in disputes if d.get("status") == "RESOLVED"]
    return {"window_days": WINDOW_DAYS, "buyer_orders": sum(1 for o in orders if o.get("payer_id") == buyer),
            "buyer_disputes": sum(1 for d in disputes if ledger.buyer_of(d) == buyer),
            "earlier_disputes": len(earlier),
            "earlier_outcomes": [ledger.OUTCOME_LABEL.get(ledger.outcome(d), "still open") for d in earlier],
            "earlier_escalated": sum(1 for d in earlier if escalated(d)),
            "shop_orders": len(orders), "shop_disputes": len(disputes),
            "shop_closed": len(closed), "shop_escalated": sum(1 for d in closed if escalated(d))}


def cost_paths(dispute: dict, records: dict, shop: dict, disputes: list, orders: list, today) -> dict:
    """What refunding now, settling in the dispute, or losing a claim would cost this shop."""
    amt = dispute["dispute_amount"]
    costs = shop.get("costs", {})
    item_cost = postage = None
    if costs:
        listings = costs.get("listings", {})
        per_item = [next((v for n, v in listings.items() if n.lower() in (i["name"] or "").lower()), None)
                    for i in records.get("items", [])]
        if per_item and all(v is not None for v in per_item):
            item_cost = round(sum(v * i["qty"] for v, i in zip(per_item, records["items"])), 2)
            postage = costs.get("postage")
    start, end = ledger.quarter_window(today)
    q = lambda iso: start <= (ledger._day(iso) or today) < end  # noqa: E731
    hv = high_volume(sum(1 for d in disputes if escalated(d) and q(d.get("create_time"))),
                     sum(1 for o in orders if q(o["date"])))
    return {**paths(float(amt["value"]), amt["currency_code"], records.get("paypal_fee"), item_cost, postage,
                    hv["high_volume"]), "threshold": hv}


def describe_history(h: dict, min_shop_orders: int = 20) -> str:
    """The buyer's history in one neutral sentence: their rate next to the shop's usual rate."""
    def rate(d, o):
        return f"{d} dispute{'s' if d != 1 else ''} in {o} order{'s' if o != 1 else ''}" + (f" ({d / o:.0%})" if o else "")
    text = (f"This buyer: {rate(h['buyer_disputes'], h['buyer_orders'])} with you. "
            f"Your shop: {rate(h['shop_disputes'], h['shop_orders'])}. Last {h['window_days']} days.")
    if h["shop_orders"] < min_shop_orders:
        text += f" Too few orders for a fair comparison (under {min_shop_orders})."
    elif h["buyer_orders"] and h["shop_disputes"]:
        times = (h["buyer_disputes"] / h["buyer_orders"]) / (h["shop_disputes"] / h["shop_orders"])
        text += f" This buyer disputes {times:.1f} times your shop's usual rate."
    if "earlier_escalated" in h:
        text += " " + ledger.describe_escalations(h["earlier_disputes"], h["earlier_escalated"],
                                                  h["shop_closed"], h["shop_escalated"])
    return text


def _trackers(pp, tx_id: str) -> list:
    return pp._call("GET", f"/v1/shipping/trackers?transaction_id={tx_id}").get("trackers", [])


def add_history(records: dict, sources: dict, dispute: dict, disputes: list, orders: list, policy: dict,
                source: str, today) -> None:
    h = history(dispute, disputes, orders, today)
    if h:
        records["buyer_history_counts"] = h
        records["buyer_history"] = describe_history(h, (policy.get("repeat_buyer") or {}).get("min_shop_orders", 20))
        sources["buyer_history"] = sources["buyer_history_counts"] = source


def add_shop_terms(records: dict, sources: dict, shop: dict) -> None:
    if not shop:
        return
    records["handling_time_promised"] = shop.get("handling_time")
    records["return_policy"] = shop.get("return_policy")
    # match by listing name inside the item name, any case: buyers type "art print x3" for "Art print"
    listings = shop.get("listings", {})
    listing = [next((t for n, t in listings.items() if n.lower() in (i["name"] or "").lower()), None)
               for i in records.get("items", [])]
    records["listing_text"] = " | ".join(x for x in listing if x) or None
    for k in ("handling_time_promised", "return_policy", "listing_text"):
        sources[k] = "shop.json (the shop's published terms)"


def gather(pp, dispute: dict, root: Path) -> dict:
    records: dict = {}
    sources: dict = {}
    unavailable: dict = {}
    tx = (dispute.get("disputed_transactions") or [{}])[0]
    tx_id, order_time = tx.get("seller_transaction_id"), tx.get("create_time")

    # 1. the dispute
    records["order_date"] = order_time
    records["items"] = [{"name": i.get("item_name"), "qty": int(i.get("item_quantity", 1) or 1)}
                        for i in tx.get("items", [])]
    sources["order_date"] = sources["items"] = "PayPal dispute"

    # 2. what PayPal knows about the order
    try:
        t = _transaction(pp, tx_id, order_time) if tx_id and order_time else {}
        fee = (t.get("transaction_info") or {}).get("fee_amount")
        if fee:
            records["paypal_fee"] = abs(float(fee["value"]))  # PayPal keeps it on a refund
            sources["paypal_fee"] = "PayPal Transaction Search"
        ship = t.get("shipping_info") or {}
        if ship.get("address"):
            a = ship["address"]
            records["ship_to"] = ", ".join(x for x in (ship.get("name"), a.get("line1"), a.get("postal_code"),
                                                        a.get("city"), a.get("country_code")) if x)
            records["ship_to_is_paypal_address"] = True  # PayPal's own shipping address on the order
            sources["ship_to"] = "PayPal Transaction Search"
        elif t:
            unavailable["ship_to"] = "PayPal holds no shipping address for this order"
        else:
            unavailable["ship_to"] = "Transaction Search returned nothing yet (PayPal can take hours to index)"
    except RuntimeError as e:
        unavailable["ship_to"] = "Transaction Search unavailable: " + str(e)[:120]

    # 3. tracking the seller registered with PayPal
    try:
        trackers = _trackers(pp, tx_id) if tx_id else []
        if trackers:
            tr = trackers[-1]
            records["tracking"] = {"carrier": tr.get("carrier"), "carrier_name_other": tr.get("carrier_name_other"),
                                   "tracking_number": tr.get("tracking_number"),
                                   "status": tr.get("status"), "shipped_date": tr.get("shipment_date"),
                                   "last_update": _iso(tr.get("last_updated_time"))}
            sources["tracking"] = "PayPal tracking"
        else:
            records["tracking"] = None
            sources["tracking"] = "PayPal tracking (none registered)"
    except RuntimeError as e:
        unavailable["tracking"] = "PayPal tracking unavailable: " + str(e)[:120]

    # 4. this buyer's history with the shop, against the shop's usual rate
    disputes, orders = [], []
    try:
        now = datetime.utcnow()
        disputes, orders = shop_disputes(pp, now), _orders(pp, now)
        pol = json.loads((root / "policy.json").read_text()) if (root / "policy.json").exists() else {}
        add_history(records, sources, dispute, disputes, orders, pol, "PayPal disputes and Transaction Search", now.date())
    except RuntimeError as e:
        unavailable["buyer_history"] = "Buyer history unavailable: " + str(e)[:120]

    # 5. the shop's public promises
    shop_file = root / "shop.json"
    shop = json.loads(shop_file.read_text()) if shop_file.exists() else {}
    add_shop_terms(records, sources, shop)

    # 6. the seller's own notes, which override nothing PayPal said, only add
    notes = root / "records" / f"{dispute['dispute_id']}.json"
    if notes.exists():
        for k, v in json.loads(notes.read_text()).items():
            # notes only fill gaps; an empty note never replaces what PayPal said (even "no tracking")
            if v not in (None, [], "") and (k not in records or records[k] in (None, [], "")):
                records[k] = v
                sources[k] = "seller's notes"

    # 7. what each way out would cost: PayPal's fee table, PayPal's fee on this payment, the shop's own costs
    records["costs"] = cost_paths(dispute, records, shop, disputes, orders, datetime.utcnow().date())
    sources["costs"] = "PayPal fee rules + your costs"

    records["sources"] = sources
    if unavailable:
        records["unavailable"] = unavailable
    return records
