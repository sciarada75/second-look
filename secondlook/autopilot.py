"""Earned autonomy: Second Look's AI answers a kind of case on its own once the shop's people have trusted it.

A kind is stage · problem · recommended action: "inquiry · not_received · MESSAGE", "paypal ·
MERCHANDISE_OR_SERVICE_NOT_RECEIVED · DEFEND". Its record is the decisions the shop's people made on Second
Look's AI's advice for that kind. A kind is READY when the last `window` decisions (10) were approved as advised:
the action it recommended, the same amount, the reply not edited. Any other decision restarts the count.
Ready is not ON: the head of customer care (a role with no refund limit) switches a ready kind on, and off.

Only people's decisions count, and only on reviews Second Look's AI made (never the rules baseline); its own sends
never count: it can't grade itself. The record holds only for the setup it was earned under: a fingerprint of the
AI's instructions, the model it runs on and the shop's rules. Another fingerprint empties the record and switches
every kind off.

In this version only a shop inquiry's kinds can be switched on: on a PayPal dispute a person sends every answer (its
sends there would not be signed on the case, nor kept out of staff time). Their record still counts.

Nothing here calls a model or PayPal: web.py runs the review and the one approval path. This module keeps the
record (one JSON file per shop, team.JsonFile) and the shop's numbers.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime

from . import judge, team as team_mod

AI_ID = "second-look-ai"
AI_NAME = "Second Look's AI"
# The shop's numbers (its team block "autopilot"): the money it may send on its own, the window, the confidence it
# needs (approval itself needs policy.json's 0.75), and the most cases of one kind it answers in a day.
DEFAULTS = {"refund_up_to": 0.0, "window": 10, "min_confidence": 0.90, "per_day": 20}
# What a setup change is about: what Second Look's AI was told, or the shop's rules (its preferences, its limits and
# the guard's own rules: defending a parcel delivered to PayPal's address, the injection markers).
LIMITS = ("min_confidence", "max_auto_refund", "always_ask_above", "repeat_buyer",
          "defend_if_delivered_to_paypal_address", "injection_markers")
# The stages whose kinds may be switched on in this version.
SWITCHABLE = ("inquiry",)
NOT_YET = "Not in this version: on a PayPal dispute, a person sends every answer."


def settings(t: dict) -> dict:
    """The shop's numbers, each only when it is a real number not below zero (a hand-typed "20" or a yes/no is bad
    data: the default stands). The window is at least 1."""
    given = t.get("autopilot") if isinstance(t.get("autopilot"), dict) else {}
    out = dict(DEFAULTS)
    for k, v in given.items():
        if k in out and isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
            out[k] = int(v) if k in ("window", "per_day") else float(v)
    out["window"] = max(1, out["window"])
    return out


def kind_key(stage: str, problem: str | None, action: str) -> str:
    return f"{stage} · {problem} · {action}"


def split_kind(kind: str) -> tuple:
    stage, problem, action = (kind.split(" · ") + ["", "", ""])[:3]
    return stage, problem, action


def _hash(x) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def fingerprint(policy: dict) -> dict:
    """What the record was earned under: the judge's instructions (both of them), the model they run on (the judge's
    own reading of it), and the shop's rules (policy.json: the preferences the judge follows, the limits and the rules
    the guard enforces). Not staff_time: no rule."""
    return {"instructions": _hash([judge.SYSTEM, judge.SYSTEM_INQUIRY]),
            "model": _hash(judge.model_name()),
            "rules": _hash({"seller_preferences": policy.get("seller_preferences", []),
                            **{k: policy.get(k) for k in LIMITS}})}


def same_words(a: str | None, b: str | None) -> bool:
    """A reply is unedited when its words are the same, whitespace collapsed."""
    return " ".join((a or "").split()) == " ".join((b or "").split())


def heads(t: dict) -> list:
    """The people who may switch Second Look's AI on or off: a role with no refund limit (head of customer care)."""
    return [p for p in team_mod.people(t) if team_mod.limit(t, p["id"]) is None]


def may_switch(t: dict, pid: str | None) -> bool:
    p = team_mod.person(t, pid)
    return bool(p) and p.get("id") != AI_ID and team_mod.limit(t, p.get("id")) is None


def as_ai(t: dict, signed: str) -> tuple:
    """The team as the one approval path reads it when Second Look's AI approves: its people, plus Second Look's AI
    last, whose role's limit is its own `refund_up_to`. Only for its own approval: in the shop's data it is never in
    `people` (a handoff takes the first colleague whose limit covers, so it must never be a colleague). Returns
    (team, who); who's name is the signature its sends carry."""
    s = settings(t)
    t2 = {k: copy.deepcopy(v) for k, v in t.items() if k != "solo"}
    t2["roles"] = {**(t2.get("roles") if isinstance(t2.get("roles"), dict) else {}),
                   AI_NAME: {"refund_up_to": s["refund_up_to"]}}
    t2["people"] = team_mod.people(t) + [{"id": AI_ID, "name": AI_NAME, "role": AI_NAME}]
    return t2, {"id": AI_ID, "name": signed, "role": AI_NAME}


def _day(at: str | None) -> str:
    try:
        d = datetime.strptime(str(at)[:10], "%Y-%m-%d")
    except ValueError:
        return ""
    return f"{d.day} {d:%b}"


def signature(k: dict, solo: bool = False) -> str:
    """How everything it sends is signed: "Second Look's AI, under Giulia's setting (since 17 Oct)"; for a seller on
    their own, "Second Look's AI, under your setting (since 17 Oct)"."""
    sw = (k or {}).get("switched") or {}
    since = f" (since {_day(sw.get('at'))})" if sw.get("at") else ""
    return f"{AI_NAME}, under {sw['by']}'s setting{since}" if sw.get("by") and not solo \
        else f"{AI_NAME}, under your setting{since}"


def streak(k: dict) -> int:
    """How many decisions in a row, the latest last, people approved as advised."""
    n = 0
    for x in reversed((k or {}).get("decisions", [])):
        if not x.get("as_advised"):
            break
        n += 1
    return n


def ready(k: dict, window: int) -> bool:
    return streak(k) >= window


def _shape(data: dict) -> dict:
    data.setdefault("kinds", {})
    data.setdefault("cases", {})
    data.setdefault("restarted", None)
    return data


def _kind(data: dict, kind: str) -> dict:
    k = _shape(data)["kinds"].setdefault(kind, {})
    k.setdefault("decisions", [])
    k.setdefault("on", False)
    k.setdefault("switched", None)
    k.setdefault("off", None)
    k.setdefault("today", {"day": "", "n": 0})
    return k


class Record(team_mod.JsonFile):
    """One shop's record (file handling: team.JsonFile). `seed`: the demo shop's starting record, written only when
    the file doesn't exist yet. `fp`: the fingerprint of the setup now; a record earned under another one is emptied,
    every kind off, with the reason kept for the screen."""

    def __init__(self, path, seed: dict | None = None, fp: dict | None = None, today: str | None = None):
        super().__init__(path, seed=seed)
        self.fp = fp or {}
        self.today = today or datetime.utcnow().strftime("%Y-%m-%d")
        data = self.snapshot()
        if data.get("fingerprint") and self.fp and data["fingerprint"] != self.fp:
            self.change(lambda d: None)            # emptied now, and the reason kept, once

    def _refresh(self, data: dict) -> dict:
        data = _shape(data)
        was = data.get("fingerprint")
        if was and self.fp and was != self.fp:
            what = ("Your rules" if was.get("rules") != self.fp.get("rules")
                    else "Second Look's AI's instructions" if was.get("instructions") != self.fp.get("instructions")
                    else "Second Look's AI's model")
            data["kinds"] = {}
            data["restarted"] = {"on": self.today, "why": f"{what} changed on {_day(self.today)}: the record starts again."}
        if self.fp:
            data["fingerprint"] = self.fp
        return data

    def change(self, fn):
        """fn(data) under the store's lock, the fingerprint checked first; returns what fn returns."""
        return self.transact(lambda d: fn(self._refresh(d)))

    def view(self) -> dict:
        return _shape(self.snapshot())

    def kinds_on(self, stage: str, problem: str | None) -> list:
        return [kind for kind, k in self.view()["kinds"].items() if k.get("on") and split_kind(kind)[:2] == (stage, problem)]

    def decide(self, kind: str, entry: dict, window: int) -> dict:
        """A person's decision on Second Look's AI's advice for this kind. One not as advised restarts the count; on
        a kind that is on, it also switches it off (ready is what on needs): the reason is kept."""
        def do(data):
            k = _kind(data, kind)
            k["decisions"] = (k["decisions"] + [entry])[-max(window, 1) * 5:]
            if not entry.get("as_advised") and k["on"]:
                k["on"] = False
                k["off"] = {"by": entry.get("by"), "at": entry.get("at"),
                            "why": f"{entry.get('by')} changed its advice on {entry.get('case')}: the count starts again."}
            return dict(k)
        return self.change(do)

    def switch(self, kind: str, on: bool, by: str, at: str, window: int) -> tuple:
        """The head of customer care switches a kind on (only when ready, and only a stage SWITCHABLE) or off. Who
        may is checked by the caller (may_switch). Returns (status, what happened). A kind with no record yet gets
        none from a switch."""
        def do(data):
            seen = data["kinds"].get(kind) or {}
            if on and split_kind(kind)[0] not in SWITCHABLE:
                return 409, NOT_YET
            if on and not ready(seen, window):
                return 409, f"Not ready: {streak(seen)} of the last {window} approved as advised."
            if on == bool(seen.get("on")):
                return 200, "Already on." if on else "Already off."
            k = _kind(data, kind)
            k["on"] = on
            if on:
                k["switched"], k["off"] = {"by": by, "at": at}, None
            else:
                k["off"] = {"by": by, "at": at, "why": f"Switched off by {by}."}
            return 200, ("On: Second Look's AI answers these on its own." if on else
                         "Off: a person approves every one of these again.")
        return self.change(do)

    def sent_today(self, kind: str, day: str) -> int:
        t = (self.view()["kinds"].get(kind) or {}).get("today") or {}
        return int(t.get("n") or 0) if t.get("day") == day else 0

    def reserve(self, kind: str, day: str, per_day: int) -> bool:
        """Takes one of today's `per_day` slots for this kind before it sends, in one step: two looks at once can't
        both take the last one. False when they are used. A look that sends nothing gives its slot back (release)."""
        def do(data):
            k = _kind(data, kind)
            n = k["today"]["n"] if k["today"].get("day") == day else 0
            if n >= per_day:
                return False
            k["today"] = {"day": day, "n": n + 1}
            return True
        return self.change(do)

    def release(self, kind: str, day: str) -> None:
        def do(data):
            k = _kind(data, kind)
            if k["today"].get("day") == day and k["today"].get("n"):
                k["today"]["n"] -= 1
        self.change(do)

    def handled(self, did: str, kind: str, at: str, what: str) -> bool:
        """It answered this case on its own (its slot taken already: reserve). Once per case: a second time changes
        nothing (and keeps a person's check). False then."""
        def do(data):
            if (data["cases"].get(did) or {}).get("handled"):
                return False
            data["cases"][did] = {"kind": kind, "at": at, "handled": True, "what": what, "checked": None}
            return True
        return self.change(do)

    def stepped_back(self, did: str, kind: str | None, at: str, why: str) -> None:
        def do(data):
            was = data["cases"].get(did) or {}
            if was.get("handled"):
                # the answer it already sent stays on record, with what came after it
                was["later"] = {"at": at, "why": why}
                return
            data["cases"][did] = {"kind": kind, "at": at, "handled": False, "why": why}
        self.change(do)

    def differently(self, did: str, by: str, why: str, at: str, window: int) -> tuple:
        """A person would have done it differently: that kind goes off at once and its count restarts; who and why are
        kept. What was sent stays sent: the person follows up."""
        def do(data):
            c = data["cases"].get(did)
            if not c or not c.get("handled"):
                return 404, "Second Look's AI didn't answer this case on its own."
            if c.get("checked"):
                return 409, f"Already noted by {c['checked']['by']}."
            kind = c["kind"]
            k = _kind(data, kind)
            note = re.sub(r"\s+", " ", why or "").strip()[:300]
            k["decisions"] = (k["decisions"] + [{"case": did, "at": at, "by": by, "as_advised": False,
                                                 "why": note or "I'd have done it differently"}])[-max(window, 1) * 5:]
            k["on"] = False
            k["off"] = {"by": by, "at": at, "why": f"{by} would have done {did} differently" + (f": {note.rstrip('.')}." if note else ".")}
            c["checked"] = {"by": by, "at": at, "differently": True, "why": note}
            return 200, kind
        return self.change(do)

    def looks_right(self, did: str, by: str, at: str) -> tuple:
        """A person checked what it sent on its own, and it looks right: the check is kept, so the answers left to check
        go down. It never counts toward the record: only people's decisions on its advice, before anything is sent, do."""
        def do(data):
            c = data["cases"].get(did)
            if not c or not c.get("handled"):
                return 404, "Second Look's AI didn't answer this case on its own."
            if c.get("checked"):
                return 409, f"Already checked by {c['checked']['by']}."
            c["checked"] = {"by": by, "at": at, "differently": False}
            return 200, c["kind"]
        return self.change(do)
