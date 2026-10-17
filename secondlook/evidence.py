"""Gathers the seller's evidence for a dispute automatically, and labels where each fact came from.

Sources, in order of trust:
  1. The dispute itself (PayPal)        items, order time, seller protection, buyer messages
  2. PayPal Transaction Search          the shipping address and items PayPal holds for the order
  3. PayPal tracking (Add Tracking API) carrier, tracking number, status the seller registered
  4. shop.json                          the shop's public promises: listing text, handling time, returns
  5. records/<dispute_id>.json          the seller's own notes (photos, weights, history); optional

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

    # 4. the shop's public promises
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

    # 5. the seller's own notes, which override nothing PayPal said, only add
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
