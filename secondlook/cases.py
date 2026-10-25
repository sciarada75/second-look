"""Cases: one customer, one order, one problem, and every contact about it, from any channel, in one place.

A case starts from a request (an email or a web form today; a phone call in a later step). Each contact is
an entry on its timeline: when, which channel, in or out, who, and whether Second Look's AI wrote it.
PayPal's own messages are never copied in: timeline() reads them from the dispute each time, so a case can
never disagree with PayPal.

Joining:
  - a request from the same customer about the same order joins that customer's open case;
  - a request about an order with an open PayPal dispute joins the dispute's case (opening it if needed);
  - an open case whose order then gets a PayPal dispute is linked to it (link_disputes), and its stage
    moves from "inquiry" to "paypal_dispute" ("paypal_claim" once PayPal escalates it).

PayPal disputes work exactly as before: a dispute gets a case only when another channel joins it.

The store is one JSON file per shop with the team's file handling (team.JsonFile: atomic writes, one lock,
a broken file kept aside, never overwritten).
"""
from __future__ import annotations

import re
from datetime import datetime

from .costs import escalated
from .ledger import REASON_SHORT
from .team import JsonFile

STAGES = ("inquiry", "paypal_dispute", "paypal_claim")
STAGE_LABEL = {"inquiry": "Shop inquiry", "paypal_dispute": "PayPal dispute", "paypal_claim": "PayPal claim"}
CHANNELS = ("call", "email", "form", "paypal")
CHANNEL_LABEL = {"call": "call", "email": "email", "form": "web form", "paypal": "PayPal"}
CHANNEL_ICON = {"call": "📞", "email": "✉️", "form": "📝", "paypal": "PayPal"}
KINDS = ("not_received", "not_as_described", "wrong_size", "refund_missing", "question")
KIND_LABEL = {"not_received": "Says it never arrived", "not_as_described": "Says it's not as described",
              "wrong_size": "Wrong size", "refund_missing": "Says the refund never came", "question": "A question"}
# Demo cases are DEMO-C001, DEMO-C002 ...; the live shop's C001, C002 ... (PayPal's ids start with PP-).
CASE_ID = re.compile(r"(?:DEMO-)?C\d{3,}")
# Staff time, when the shop's rules (policy.json "staff_time") don't say: an estimate, always labelled so.
STAFF_DEFAULTS = {"hourly_cost": 25.0, "reply_minutes": 6}


def is_case_id(x) -> bool:
    return isinstance(x, str) and bool(CASE_ID.fullmatch(x))


def minute(iso=None) -> str:
    """'2026-10-19T08:52:00Z' -> '2026-10-19T08:52', the way Second Look saves times. Unreadable or none: now (UTC)."""
    for fmt, n in (("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%dT%H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(str(iso)[:n], fmt).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            continue
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M")


def entry(at, channel: str, direction: str, text: str, by: str, ai: bool = False, **extra) -> dict:
    """One line of a timeline. direction: "in" (from the customer), "out" (from the shop), "note" (an event).
    ai: Second Look's AI wrote it (a person still approved anything that went out)."""
    return {"at": minute(at), "channel": channel, "direction": direction, "text": text, "by": by, "ai": bool(ai), **extra}


def stage_for(dispute: dict) -> str:
    return "paypal_claim" if escalated(dispute) else "paypal_dispute"


def staff_time(policy: dict | None) -> dict:
    """The shop's own figures for staff time (policy.json "staff_time"), each one only when it is a number above zero."""
    given = (policy or {}).get("staff_time") or {}
    out = dict(STAFF_DEFAULTS)
    for k in out:
        v = given.get(k) if isinstance(given, dict) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            out[k] = float(v)
    return out


def _tx(dispute: dict) -> str | None:
    return ((dispute.get("disputed_transactions") or [{}])[0]).get("seller_transaction_id")


def timeline(case: dict, dispute: dict | None = None) -> list:
    """Every entry in time order: the case's own, and, for a case with a PayPal dispute, what PayPal holds
    (the dispute opening and its messages). A shop message already on the case is not shown twice."""
    items = [dict(x) for x in case.get("timeline", [])]
    if dispute:
        who = case.get("customer", {}).get("name") or "Customer"
        items.append(entry(dispute.get("create_time"), "paypal", "note",
                           f"PayPal dispute opened: {REASON_SHORT.get(dispute.get('reason'), dispute.get('reason'))}",
                           "PayPal", dispute_id=dispute.get("dispute_id")))
        ours = {x["text"] for x in items if x["channel"] == "paypal" and x["direction"] == "out"}
        for m in dispute.get("messages", []):
            mine = m.get("posted_by") != "BUYER"
            if mine and m.get("content") in ours:
                continue
            items.append(entry(m.get("time_posted"), "paypal", "out" if mine else "in", m.get("content", ""),
                               "The shop" if mine else who))
    return sorted(items, key=lambda x: x["at"])


def channels(case: dict, dispute: dict | None = None) -> list:
    """The channels this case came in by, in the order they first appear."""
    seen = []
    for x in timeline(case, dispute):
        if x["direction"] == "in" and x["channel"] not in seen:
            seen.append(x["channel"])
    if dispute and "paypal" not in seen:
        seen.append("paypal")
    return seen


def costs_so_far(case: dict, dispute: dict | None, policy: dict | None) -> dict:
    """What this case has cost so far. Staff time is an estimate: each written answer counts the shop's
    reply minutes, a call its own length; times the shop's hourly cost. Fees and money moved are recorded
    on the case when they happen."""
    st = staff_time(policy)
    tl = timeline(case, dispute)
    contacts = [x for x in tl if x["direction"] in ("in", "out")]
    replies = [x for x in contacts if x["direction"] == "out" and x["channel"] != "call"]
    calls = [x for x in contacts if x["channel"] == "call"]
    minutes = len(replies) * st["reply_minutes"] + sum(float(x.get("minutes") or 0) for x in calls)
    money = case.get("money", [])
    return {"contacts": len(contacts), "replies": len(replies), "calls": len(calls), "minutes": minutes,
            "hourly_cost": st["hourly_cost"], "reply_minutes": st["reply_minutes"],
            "staff_cost": round(minutes / 60 * st["hourly_cost"], 2),
            "fees": round(sum(m["amount"] for m in money if m.get("kind") == "fee"), 2),
            "money_moved": round(sum(m["amount"] for m in money if m.get("kind") in ("refund", "partial_refund")), 2),
            "estimated": True}


def _shape(data: dict) -> dict:
    data.setdefault("next", 1)
    data.setdefault("cases", {})
    data.setdefault("sources", {})
    return data


def _same(a: str | None, b: str | None) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower() and bool(a)


def _of_dispute(cases: dict, dispute_id: str) -> dict | None:
    """The case holding this PayPal dispute: an open one first (a closed case is history), else any."""
    held = [c for c in cases.values() if c.get("dispute_id") == dispute_id]
    return next((c for c in held if c["status"] == "open"), held[0] if held else None)


class CaseStore(JsonFile):
    """Every case of one shop: {"next": n, "cases": {id: case}, "sources": {source id: case id}}.
    `prefix` makes the ids: "DEMO-" for the demo shop (DEMO-C001), "" for the live shop (C001)."""

    def __init__(self, path, prefix: str = ""):
        super().__init__(path)
        self.prefix = prefix

    # ---------- reading ----------

    def get(self, cid: str) -> dict | None:
        return _shape(self.snapshot())["cases"].get(cid)

    def all(self) -> list:
        return sorted(_shape(self.snapshot())["cases"].values(), key=lambda c: c["opened"])

    def by_source(self, source_id: str) -> str | None:
        return _shape(self.snapshot())["sources"].get(source_id)

    def by_dispute(self, dispute_id: str) -> dict | None:
        return _of_dispute(_shape(self.snapshot())["cases"], dispute_id)

    # ---------- writing ----------

    def file(self, request: dict, sorting: dict, dispute: dict | None = None) -> tuple:
        """Put one request on its case. Returns (case, how): how is "opened", "joined" or "already_received"
        (the same source id was filed before: nothing changes, so a system may send a request twice).
        `sorting` is what sort.sort() said; `dispute`, the open PayPal dispute on the sorted order, if any."""
        def do(data):
            data = _shape(data)
            sid = request.get("source_id")
            if sid and data["sources"].get(sid) in data["cases"]:
                return dict(data["cases"][data["sources"][sid]]), "already_received"
            sender = request.get("from") or {}
            got = entry(request.get("time"), request["channel"], "in", request["text"],
                        sender.get("name") or sender.get("email") or "Customer",
                        subject=request.get("subject") or "", source_id=sid,
                        **{"from": {"name": sender.get("name"), "email": sender.get("email")}},
                        sorted={"by": sorting.get("by"), "how": sorting.get("how")})
            customer = sorting.get("customer") or {"name": sender.get("name"), "email": sender.get("email")}
            target = _of_dispute(data["cases"], dispute["dispute_id"]) if dispute else None
            if target is None and sorting.get("settled"):
                target = next((c for c in data["cases"].values() if c["status"] == "open" and c["sorted"]["by"]
                               and _same(c["customer"].get("email"), customer.get("email"))
                               and c.get("order_no") == sorting.get("order_no")), None)
            if target is None and sorting.get("settled") and not sorting.get("order_no"):
                # "Any news?" (a settled request about no order) from someone whose one open case is still
                # waiting for a person to pick its order: it is about that case
                waiting = [c for c in data["cases"].values() if c["status"] == "open" and not c["sorted"]["by"]
                           and _same(c["customer"].get("email"), customer.get("email"))]
                target = waiting[0] if len(waiting) == 1 else None
            if target is not None:
                target["timeline"].append(got)
                if dispute and not target.get("dispute_id"):
                    target["dispute_id"], target["stage"] = dispute["dispute_id"], stage_for(dispute)
                how = "joined"
            else:
                cid = f"{self.prefix}C{data['next']:03d}"
                data["next"] += 1
                target = {"id": cid, "customer": {"name": customer.get("name"), "email": customer.get("email")},
                          "order_no": sorting.get("order_no"),
                          "problem": {"kind": sorting.get("kind") or "question", "summary": sorting.get("summary") or ""},
                          "stage": stage_for(dispute) if dispute else "inquiry", "status": "open", "outcome": None,
                          "dispute_id": dispute["dispute_id"] if dispute else None,
                          "sorted": {"by": sorting.get("by") if sorting.get("settled") else None, "how": sorting.get("how")},
                          "opened": got["at"], "timeline": [got], "money": []}
                data["cases"][cid] = target
                how = "opened"
            if sid:
                data["sources"][sid] = target["id"]
            return dict(target), how
        return self.transact(do)

    def add(self, cid: str, e: dict) -> dict:
        """Add one timeline entry to a case."""
        return self.update(cid, lambda c: c["timeline"].append(e))

    def update(self, cid: str, fn) -> dict:
        """Change one case in place under the store's lock: fn(case) edits it. KeyError for an unknown id."""
        def do(data):
            c = _shape(data)["cases"][cid]
            fn(c)
            return dict(c)
        return self.transact(do)

    def link_disputes(self, disputes: list, orders: dict) -> int:
        """Open cases whose order now has an open PayPal dispute join it; linked cases follow PayPal's stage.
        `orders`: order number -> order (as sort.order_view gives it). Returns how many cases changed; the file
        is written only when one did (every page view calls this)."""
        by_tx = {_tx(d): d for d in disputes if d.get("status") != "RESOLVED" and _tx(d)}
        by_id = {d["dispute_id"]: d for d in disputes}

        def changes(data) -> list:
            out = []
            # a dispute already on a case is never linked to a second one
            taken = {c.get("dispute_id") for c in _shape(data)["cases"].values() if c.get("dispute_id")}
            for c in _shape(data)["cases"].values():
                if c["status"] != "open":
                    continue
                if c.get("dispute_id"):
                    d = by_id.get(c["dispute_id"])
                    if d and c["stage"] != stage_for(d):
                        out.append((c["id"], d))
                    continue
                tx = (orders.get(c.get("order_no")) or {}).get("transaction_id")
                if tx and by_tx.get(tx) and by_tx[tx]["dispute_id"] not in taken:
                    out.append((c["id"], by_tx[tx]))
                    taken.add(by_tx[tx]["dispute_id"])
            return out
        if not changes(self.snapshot()):
            return 0

        def do(data):
            todo = changes(data)
            for cid, d in todo:
                data["cases"][cid]["dispute_id"], data["cases"][cid]["stage"] = d["dispute_id"], stage_for(d)
            return len(todo)
        return self.transact(do)

    def pick_order(self, cid: str, order: dict | None, by: str, dispute: dict | None = None) -> str:
        """A person says which order an unsorted case is about (None: a general question, no order), or which
        order a case sorted as a question turns out to be about. A case settled on an order is never picked
        again. If that customer already has an open case on that order, this case's entries move into it and
        this case is removed. Returns the id of the case the request now lives in."""
        def do(data):
            data = _shape(data)
            c = data["cases"][cid]
            if c["sorted"]["by"] and (c.get("order_no") or order is None):
                raise ValueError(f"{cid} is already sorted.")
            if order is None:
                c["sorted"] = {"by": "person", "how": f"{by} marked it a general question: no order."}
                c["problem"]["kind"], c["order_no"] = "question", None
                return cid
            customer = {"name": order.get("name"), "email": order.get("email")}
            target = _of_dispute(data["cases"], dispute["dispute_id"]) if dispute else None
            if target is None:
                target = next((x for x in data["cases"].values() if x["id"] != cid and x["status"] == "open"
                               and x["sorted"]["by"] and _same(x["customer"].get("email"), customer["email"])
                               and x.get("order_no") == order["order_no"]), None)
            how = f"Order {order['order_no']} picked by {by}."
            if target is not None and target["id"] != cid:
                target["timeline"] = sorted(target["timeline"] + c["timeline"], key=lambda x: x["at"])
                target["timeline"].append(entry(None, c["timeline"][0]["channel"], "note",
                                                f"{how} Joined to this case from {cid}.", by))
                for sid, to in list(data["sources"].items()):
                    if to == cid:
                        data["sources"][sid] = target["id"]
                del data["cases"][cid]
                return target["id"]
            c.update(customer=customer, order_no=order["order_no"], sorted={"by": "person", "how": how})
            if dispute:
                c["dispute_id"], c["stage"] = dispute["dispute_id"], stage_for(dispute)
            return cid
        return self.transact(do)
