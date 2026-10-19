"""Gathers the seller's evidence for a dispute automatically, and labels where each fact came from.

Sources, in order of trust:
  1. The dispute itself (PayPal)        items, order time, seller protection, buyer messages
  2. PayPal Transaction Search          the shipping address and items PayPal holds for the order
  3. PayPal tracking (Add Tracking API) carrier, tracking number, status the seller registered
  4. PayPal disputes + Transaction Search  this buyer's disputes and orders with the shop, against the
                                         shop's usual rate (the base rate), last 90 days
  5. shop.json                          the shop's public promises: listing text, handling time, returns
  6. records/<dispute_id>.json          the seller's own notes (photos, weights, history); optional

Every fact keeps its source in records["sources"], so the judge can cite it and the seller can
check it. A source that is unavailable is reported, never invented.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib import parse


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


WINDOW_DAYS = 90


def _orders(pp, until: datetime) -> list:
    """Payments received in the window, as (payer_id, date). Transaction Search allows 31 days per query."""
    out, fmt, end = [], "%Y-%m-%dT%H:%M:%SZ", until
    while end > until - timedelta(days=WINDOW_DAYS):
        start = max(end - timedelta(days=31), until - timedelta(days=WINDOW_DAYS))
        q = parse.urlencode({"start_date": start.strftime(fmt), "end_date": end.strftime(fmt),
                             "fields": "transaction_info,payer_info", "page_size": 500})
        for t in pp._call("GET", f"/v1/reporting/transactions?{q}").get("transaction_details", []):
            ti = t["transaction_info"]
            # T00xx = a payment received; funding (T19xx) and holds (T11xx) are not orders
            if ti.get("transaction_event_code", "").startswith("T00") and \
                    float(ti.get("transaction_amount", {}).get("value", 0)) > 0:
                out.append(t.get("payer_info", {}).get("account_id"))
        end = start
    return out


def _buyer_history(pp, dispute: dict) -> dict:
    """This buyer against the shop's own base rate. A raw count means nothing: 3 disputes is a lot for a
    shop with 1,000 orders and 2 disputes, and normal where one order in three ends in a dispute."""
    buyer = ((dispute.get("disputed_transactions") or [{}])[0].get("buyer") or {}).get("payer_id")
    if not buyer:
        return {}
    now = datetime.utcnow()
    since = (now - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    disputes, earlier_outcomes = [], []
    for d in pp._call("GET", "/v1/customer/disputes?page_size=50").get("items", []):
        if d.get("create_time", "")[:19] < since:
            continue
        full = d if d["dispute_id"] == dispute.get("dispute_id") else pp.get_dispute(d["dispute_id"])
        who = ((full.get("disputed_transactions") or [{}])[0].get("buyer") or {}).get("payer_id")
        disputes.append(who)
        if who == buyer and d["dispute_id"] != dispute.get("dispute_id"):
            earlier_outcomes.append((full.get("dispute_outcome") or {}).get("outcome_code") or "still open")
    orders = _orders(pp, now)
    return {"window_days": WINDOW_DAYS, "buyer_orders": orders.count(buyer), "buyer_disputes": disputes.count(buyer),
            "earlier_disputes": len(earlier_outcomes), "earlier_outcomes": earlier_outcomes,
            "shop_orders": len(orders), "shop_disputes": len(disputes)}


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
    return text


def _trackers(pp, tx_id: str) -> list:
    return pp._call("GET", f"/v1/shipping/trackers?transaction_id={tx_id}").get("trackers", [])


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
    try:
        h = _buyer_history(pp, dispute)
        if h:
            records["buyer_history_counts"] = h
            pol = json.loads((root / "policy.json").read_text()) if (root / "policy.json").exists() else {}
            records["buyer_history"] = describe_history(h, (pol.get("repeat_buyer") or {}).get("min_shop_orders", 20))
            sources["buyer_history"] = sources["buyer_history_counts"] = "PayPal disputes and Transaction Search"
    except RuntimeError as e:
        unavailable["buyer_history"] = "Buyer history unavailable: " + str(e)[:120]

    # 5. the shop's public promises
    shop_file = root / "shop.json"
    if shop_file.exists():
        shop = json.loads(shop_file.read_text())
        records["handling_time_promised"] = shop.get("handling_time")
        records["return_policy"] = shop.get("return_policy")
        # match by listing name inside the item name, any case: buyers type "art print x3" for "Art print"
        listings = shop.get("listings", {})
        listing = [next((t for n, t in listings.items() if n.lower() in (i["name"] or "").lower()), None)
                   for i in records["items"]]
        records["listing_text"] = " | ".join(x for x in listing if x) or None
        for k in ("handling_time_promised", "return_policy", "listing_text"):
            sources[k] = "shop.json (the shop's published terms)"

    # 6. the seller's own notes, which override nothing PayPal said, only add
    notes = root / "records" / f"{dispute['dispute_id']}.json"
    if notes.exists():
        for k, v in json.loads(notes.read_text()).items():
            # notes only fill gaps; an empty note never replaces what PayPal said (even "no tracking")
            if v not in (None, [], "") and (k not in records or records[k] in (None, [], "")):
                records[k] = v
                sources[k] = "seller's notes"

    records["sources"] = sources
    if unavailable:
        records["unavailable"] = unavailable
    return records
