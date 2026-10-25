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
    if not (isinstance(block, dict) and block.get("people")):
        return copy.deepcopy(SOLO)
    # "solo" is ours to set, never the file's: a team block that says it would skip every team check.
    return {k: v for k, v in block.items() if k != "solo"}


# The team block is typed by hand into a JSON file. Whatever shape it arrives in, a wrong shape means
# "nobody here" or "no limit written" (no money), never a crash in the middle of an approval.
def _people(t: dict) -> list:
    people = t.get("people")
    return [p for p in people if isinstance(p, dict)] if isinstance(people, list) else []


def _role(t: dict, p: dict) -> dict:
    roles, name = t.get("roles"), p.get("role")
    role = roles.get(name) if isinstance(roles, dict) and isinstance(name, str) else None
    return role if isinstance(role, dict) else {}


def people(t: dict) -> list:
    """The people a page may show: entries with an id (anything else in the file is skipped, not a crash)."""
    return [p for p in _people(t) if isinstance(p.get("id"), str) and p["id"]]


def first(t: dict) -> dict | None:
    """The first valid person in the team, in the shop's own order. None when the file lists nobody usable."""
    return next(iter(people(t)), None)


def person(t: dict, pid: str | None) -> dict | None:
    """Who is acting. In a team of one it is always the seller; in a team, nobody is assumed."""
    if t.get("solo"):
        return t["people"][0]
    if not isinstance(pid, str) or not pid:
        return None  # no name never matches an entry written without an id
    return next((p for p in _people(t) if p.get("id") == pid), None)


def limit(t: dict, pid: str | None):
    """The most money this person may send themselves. None = no cap of the role's own.
    A role with no limit written sends no money: the safe reading of a missing number."""
    p = person(t, pid)
    if not p:
        return 0.0
    cap = _role(t, p).get("refund_up_to", 0.0)
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
    return next((p for p in _people(t) if p.get("id") != exclude and covers(t, p.get("id"), amount)), None)


# One lock for every store in this process: the web server answers requests on several threads, and two
# approvals at once must not each read the file, change their own case and write back over the other's.
class _OneLock:
    """A plain lock that knows which thread holds it. Taking it again on that same thread (a change that
    reads or writes a store from inside its own transact) would wait on itself for ever: it raises instead.
    Not a re-entrant lock on purpose: the inner write would be undone by the outer one."""

    def __init__(self):
        self._lock, self._owner = threading.Lock(), None

    def __enter__(self):
        if self._owner == threading.get_ident():
            raise RuntimeError("A store was used from inside its own change (transact/update): "
                               "read what you need before the change, or return it from the change.")
        self._lock.acquire()
        self._owner = threading.get_ident()
        return self

    def __exit__(self, *exc):
        self._owner = None
        self._lock.release()
        return False


_LOCK = _OneLock()


def _shape(a) -> dict:
    a = a if isinstance(a, dict) else {}
    return {"to": a.get("to"), "handoff": a.get("handoff")}


class JsonFile:
    """One JSON object in one file, shared by every thread of the server.
    A seed (the demo shop's starting state) is written only when the file doesn't exist yet.
    Writes go to a temporary file first, then replace the old one in one step, so a crash mid-write
    never leaves half a file. A file that isn't valid JSON is kept aside as <name>.corrupt, never
    overwritten: the store starts empty and the old data is still there to look at. A file that
    can't be opened at all (permissions, a disk error) raises: better no answer than writing over it."""

    def __init__(self, path: Path, seed: dict | None = None):
        self.path = Path(path)
        with _LOCK:
            if not self.path.exists() and seed:
                self._write(seed)

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
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
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())   # on disk before it replaces the old file, not only in a buffer
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def snapshot(self) -> dict:
        """The whole object as it is now (a copy: changing it changes nothing on disk)."""
        with _LOCK:
            return self._read()

    def transact(self, fn):
        """Read, change and write under one lock: fn(data) changes the object in place and returns what the
        caller needs. Two writers never undo each other. Nothing is written when fn raises."""
        with _LOCK:
            data = self._read()
            result = fn(data)
            self._write(data)
            return result


class Assignments(JsonFile):
    """Who each open case belongs to, and any handoff waiting on it. One JSON file per shop
    (file handling: JsonFile)."""

    def all(self) -> dict:
        with _LOCK:
            return {did: _shape(a) for did, a in self._read().items()}

    def get(self, did: str) -> dict:
        with _LOCK:
            return _shape(self._read().get(did))

    def update(self, did: str, fn) -> dict:
        """Change one case from its current state: fn gets the entry as get() shows it and returns the
        new one. Read, change and write happen under one lock, so a change made by someone else in
        between is never lost (two reads and a write would let the second writer undo the first)."""
        with _LOCK:
            data = self._read()
            data[did] = _shape(fn(_shape(data.get(did))))
            self._write(data)
            return data[did]

    def assign(self, did: str, to: str | None, handoff: dict | None = None) -> None:
        self.update(did, lambda _: {"to": to, "handoff": handoff})
