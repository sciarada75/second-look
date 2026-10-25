"""The demo shop: made-up data (demo/shop.json, written by demo/make_demo.py) behind the same interface
as the PayPal client, so every page and the judge run the same code as on the live sandbox.

Every page that shows it says so. Actions are logged to .tmp/actions-demo.jsonl, never sent anywhere.
"""
from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path

from . import evidence
from .paypal import MockPayPal

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "demo" / "shop.json"
LABEL = "Demo shop — made-up data"

# PayPal's dispute_state filter, applied to the demo's statuses
STATE = {"REQUIRED_ACTION": ("WAITING_FOR_SELLER_RESPONSE",), "REQUIRED_OTHER_PARTY_ACTION": ("WAITING_FOR_BUYER_RESPONSE",),
         "UNDER_PAYPAL_REVIEW": ("UNDER_REVIEW",), "RESOLVED": ("RESOLVED",)}


def is_demo(dispute_id: str | None) -> bool:
    return bool(dispute_id) and dispute_id.startswith("DEMO-")


# shop.json is about 1 MB and every page, API call and team lookup builds a DemoPayPal: parse it once per
# version of the file (path, modification time, size), not on every call. Instances share the parsed data,
# so it is read-only: nothing in Second Look writes to it (actions go to the log).
_PARSED: dict = {}
_PARSED_LOCK = threading.Lock()


def _read(data: Path) -> dict:
    st = data.stat()
    version = (st.st_mtime_ns, st.st_size)
    with _PARSED_LOCK:
        hit = _PARSED.get(str(data))
    if hit and hit[0] == version:
        return hit[1]
    raw = json.loads(data.read_text())
    with _PARSED_LOCK:
        _PARSED[str(data)] = (version, raw)
    return raw


class DemoPayPal(MockPayPal):
    def __init__(self, data: Path = DATA, log: Path = ROOT / ".tmp" / "actions-demo.jsonl"):
        super().__init__(data.parent, log)
        self.raw = _read(Path(data))
        self.today = date.fromisoformat(self.raw["today"])
        self.shop = self.raw["shop"]

    # the same reads the live client offers
    def disputes(self) -> list:
        return self.raw["disputes"]

    def orders(self) -> list:
        return self.raw["orders"]

    def other_orders(self) -> list:
        """Orders paid by card or bank transfer: the shop's own records, not PayPal's (no transaction id)."""
        return self.raw.get("other_orders", [])

    def requests(self) -> list:
        """What reached the shop by email or web form this morning, through its helpdesk."""
        return self.raw.get("requests", [])

    def list_disputes(self, status: str = "REQUIRED_ACTION") -> list:
        return [d for d in self.raw["disputes"] if d["status"] in STATE.get(status, ())]

    def get_dispute(self, dispute_id: str) -> dict:
        return next(d for d in self.raw["disputes"] if d["dispute_id"] == dispute_id)

    def get_case(self, dispute_id: str) -> dict:
        d = self.get_dispute(dispute_id)
        return {"dispute": d, "seller_records": self.gather(d)}

    def gather(self, d: dict) -> dict:
        """The records evidence.gather() would build from PayPal, built from the demo's orders instead."""
        tx = d["disputed_transactions"][0]
        o = next(x for x in self.raw["orders"] if x["transaction_id"] == tx["seller_transaction_id"])
        notes = dict(self.raw["records"].get(d["dispute_id"], {}))
        records = {"order_date": tx["create_time"],
                   "items": [{"name": i["item_name"], "qty": int(i["item_quantity"])} for i in tx["items"]],
                   "paypal_fee": o["fee"], "ship_to": f'{o["name"]}, {o["address"]}', "ship_to_is_paypal_address": True,
                   "tracking": notes.pop("tracking", None)}
        notes.pop("ship_to_paypal", None)
        sources = {"order_date": "PayPal dispute", "items": "PayPal dispute", "paypal_fee": "PayPal Transaction Search",
                   "ship_to": "PayPal Transaction Search",
                   "tracking": "PayPal tracking" if records["tracking"] else "PayPal tracking (none registered)"}
        policy = json.loads((ROOT / "policy.json").read_text())
        evidence.add_history(records, sources, d, self.disputes(), self.orders(), policy,
                             "PayPal disputes and Transaction Search", self.today)
        evidence.add_shop_terms(records, sources, self.shop)
        for k, v in notes.items():
            records[k], sources[k] = v, "seller's notes"
        records["costs"] = evidence.cost_paths(d, records, self.shop, self.disputes(), self.orders(), self.today)
        sources["costs"] = "PayPal fee rules + your costs"
        records["sources"] = sources
        return records
