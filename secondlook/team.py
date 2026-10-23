"""The team: who answers disputes, and how much money each person may send.

Roles and people are the shop's own data: policy.json "team" for the live shop, demo/shop.json for
the demo shop. The guard decides first what may be approved at all; a person's role then caps how
much money they may send themselves (it can only be stricter). Over their cap, the case passes to the
first colleague whose role covers it, with the draft, and nothing reaches PayPal.

No team block = a team of one with full rights: a solo seller sees nothing new.
"""
from __future__ import annotations

import json
from pathlib import Path

SOLO = {"roles": {"Owner": {"refund_up_to": None}},
        "people": [{"id": "you", "name": "You", "role": "Owner"}], "solo": True}


def of(block: dict | None) -> dict:
    return block if block and block.get("people") else SOLO


def person(t: dict, pid: str | None) -> dict | None:
    """Who is acting. In a team of one it is always the seller; in a team, nobody is assumed."""
    if t.get("solo"):
        return t["people"][0]
    return next((p for p in t["people"] if p["id"] == pid), None)


def limit(t: dict, pid: str | None):
    """The most money this person may send themselves. None = no cap of the role's own.
    A role with no limit written sends no money: the safe reading of a missing number."""
    p = person(t, pid)
    if not p:
        return 0.0
    return (t["roles"].get(p["role"]) or {}).get("refund_up_to", 0.0)


def covers(t: dict, pid: str | None, amount: float) -> bool:
    if person(t, pid) is None:
        return False
    cap = limit(t, pid)
    return cap is None or amount <= cap + 1e-9


def handoff_to(t: dict, amount: float, exclude: str | None) -> dict | None:
    """The first colleague, in the shop's own order, who may send this amount."""
    return next((p for p in t["people"] if p["id"] != exclude and covers(t, p["id"], amount)), None)


class Assignments:
    """Who each open case belongs to, and any handoff waiting on it. One JSON file per shop.
    A seed (the demo shop's starting state) is written only when the file doesn't exist yet."""

    def __init__(self, path: Path, seed: dict | None = None):
        self.path = Path(path)
        if not self.path.exists() and seed:
            self._write(seed)

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    def all(self) -> dict:
        return self._read()

    def get(self, did: str) -> dict:
        a = self._read().get(did) or {}
        return {"to": a.get("to"), "handoff": a.get("handoff")}

    def assign(self, did: str, to: str | None, handoff: dict | None = None) -> None:
        data = self._read()
        data[did] = {"to": to, "handoff": handoff}
        self._write(data)
