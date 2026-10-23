"""The team: who answers disputes, and how much money each person may send.

Roles and people are the shop's own data: policy.json "team" for the live shop, demo/shop.json for
the demo shop. The guard decides first what may be approved at all; a person's role then caps how
much money they may send themselves (it can only be stricter). Over their cap, the case passes to the
first colleague whose role covers it, with the draft, and nothing reaches PayPal.

No team block = a team of one with full rights: a solo seller sees nothing new.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from pathlib import Path

SOLO = {"roles": {"Owner": {"refund_up_to": None}},
        "people": [{"id": "you", "name": "You", "role": "Owner"}], "solo": True}


def of(block: dict | None) -> dict:
    # A fresh copy: a caller that edits the team of one must not change it for everyone else.
    return block if block and block.get("people") else copy.deepcopy(SOLO)


def person(t: dict, pid: str | None) -> dict | None:
    """Who is acting. In a team of one it is always the seller; in a team, nobody is assumed."""
    if t.get("solo"):
        return t["people"][0]
    return next((p for p in t.get("people") or [] if p.get("id") == pid), None)


def limit(t: dict, pid: str | None):
    """The most money this person may send themselves. None = no cap of the role's own.
    A role with no limit written sends no money: the safe reading of a missing number."""
    p = person(t, pid)
    if not p:
        return 0.0
    role = (t.get("roles") or {}).get(p.get("role")) or {}
    cap = role.get("refund_up_to", 0.0)
    if cap is None:
        return None
    # Only a real number counts. A string ("30"), a yes/no or anything else hand-typed into the file
    # is bad data, and bad data sends no money: the person hands the case on instead.
    if isinstance(cap, bool) or not isinstance(cap, (int, float)):
        return 0.0
    return float(cap)


def covers(t: dict, pid: str | None, amount: float) -> bool:
    if person(t, pid) is None:
        return False
    cap = limit(t, pid)
    return cap is None or amount <= cap + 1e-9


def handoff_to(t: dict, amount: float, exclude: str | None) -> dict | None:
    """The first colleague, in the shop's own order, who may send this amount."""
    return next((p for p in t.get("people") or [] if p.get("id") != exclude and covers(t, p.get("id"), amount)), None)


# One lock for every store in this process: the web server answers requests on several threads, and two
# approvals at once must not each read the file, change their own case and write back over the other's.
_LOCK = threading.Lock()


def _shape(a) -> dict:
    a = a if isinstance(a, dict) else {}
    return {"to": a.get("to"), "handoff": a.get("handoff")}


class Assignments:
    """Who each open case belongs to, and any handoff waiting on it. One JSON file per shop.
    A seed (the demo shop's starting state) is written only when the file doesn't exist yet.
    Writes go to a temporary file first, then replace the old one in one step, so a crash mid-write
    never leaves half a file. A file that can't be read is kept aside as <name>.corrupt, never
    overwritten: the store starts empty and the old data is still there to look at."""

    def __init__(self, path: Path, seed: dict | None = None):
        self.path = Path(path)
        with _LOCK:
            if not self.path.exists() and seed:
                self._write(seed)

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
        except OSError:
            return {}
        except ValueError:
            data = None
        if isinstance(data, dict):
            return data
        self._set_aside()
        return {}

    def _set_aside(self) -> None:
        aside, n = self.path.with_name(self.path.name + ".corrupt"), 1
        while aside.exists():
            aside, n = self.path.with_name(f"{self.path.name}.corrupt.{n}"), n + 1
        os.replace(self.path, aside)

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=self.path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def all(self) -> dict:
        with _LOCK:
            return {did: _shape(a) for did, a in self._read().items()}

    def get(self, did: str) -> dict:
        with _LOCK:
            return _shape(self._read().get(did))

    def assign(self, did: str, to: str | None, handoff: dict | None = None) -> None:
        with _LOCK:
            data = self._read()
            data[did] = {"to": to, "handoff": handoff}
            self._write(data)
