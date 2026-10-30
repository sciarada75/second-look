# Case states, moves and one page template: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every case is in exactly one state (Your move · Waiting for the customer · Waiting for PayPal · Done), decided
by one function that Today, the case page and the API all read; every page is built from one template with one look
per voice; a person may choose another fitting move with its own fixed text.

**Architecture:** Two new pure modules: `secondlook/state.py` (the state, from facts) and `secondlook/moves.py` (the
catalog: which moves fit a cause, their fixed texts, what each does next). `guard.py` gains `paypal_can()` (rule 6
moved out, unchanged) and a `template` path in `may_approve`. `web.py` gathers the facts (`case_state`), simulates
PayPal's confirmation in the demo shop only, and renders Today's buckets, the case page's side box, the voices,
"Tracked and verified", and the other moves.

**Tech Stack:** Python 3.9 stdlib only; server-rendered f-string HTML in `secondlook/web.py` (the `PAGE` template is a
`str.format` string: every CSS brace is doubled); tests are plain scripts run with `python3 tests/test_x.py`.

**Spec:** `docs/specs/2026-10-30-case-states-and-moves-design.md` (approved by Claudia 30/10, "go on").

---

## Rules for whoever runs this plan

- Work in a git worktree on branch `case-states` (superpowers:using-git-worktrees). Never commit on `main`.
- Stage files **by name**, never `git add -A`. Every commit message ends with
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Never read or edit `.env`. Never export `ANTHROPIC_API_KEY`. No test may call Claude or PayPal: the benches below
  already make a paid call fail the test.
- Never approve a live sandbox dispute (`PP-…`). Ports 8765/8766/8767 are Claudia's: don't start or stop anything on them.
- The full suite: `for f in tests/test_*.py; do python3 "$f" >/dev/null || echo "FAIL $f"; done` (prints nothing when
  all pass). It has 432 tests before this plan.
- Python 3.9: no backslash inside an f-string's `{…}`; build such pieces in a variable first.

## Not in this plan (cut on purpose, said in "As built")

- **Partial refund as a catalog move.** It needs an amount a person types and the guard checks; the AI's own partial
  refunds work as before. The catalog has reply only, refund in full, exchange or replace, send evidence.
- **Ticketbook's own screens** keep reading `for_person`; they gain the state through the API (`state` on
  `/api/cases/<id>` and `/api/disputes/<id>`) but don't show it yet.
- A colleague's edited text on a move passed over their limit is kept in the handoff, but the head's page pre-fills
  it only when the move is the AI's pick (as today).

## File structure

| File | Responsibility |
|---|---|
| `secondlook/state.py` (new) | `of()`: the one state of a case from plain facts; `LABEL`, `STATES`. Pure. |
| `secondlook/moves.py` (new) | `kind_of()`, `others()`, `text()`, `label()`, `then()`: the catalog. Pure. |
| `secondlook/guard.py` | `paypal_can()` (rule 6's reading of PayPal, moved out); `may_approve(..., template=)`; `TEMPLATE_OK_STOPS` |
| `secondlook/today.py` | `needs_you(..., states=)` skips what isn't Your move; new `waiting()`, `closed_today()` |
| `secondlook/web.py` | `_save` keeps `chosen`/`amount`; `_sent_refund`; demo confirmations; `case_state`; Today buckets, toast, handled line; `crumb`, `state_box`, `needs_after`; voices, `_with_sent_reply`, `tracked_rows`/`tracked_block`; money moved; `_move_facts`, `other_moves`, `approve(..., move=)`; CSS |
| `tests/test_state.py`, `tests/test_moves.py` (new) | the pure modules |
| `tests/test_guard.py`, `tests/test_web.py`, `tests/test_today.py`, `tests/test_intake.py` | as each task says |
| `docs/specs/…`, `README.md`, `../HANDOVER.md`, `../LOG.md` | Task 10 |

---

### Task 0: Baseline

**Files:** Create (scratchpad, not the repo) `$SP/guard_snapshot.py`.

- [ ] **Step 1: Write the snapshot script**

`SP=/private/tmp/claude-501/-Users-claudiamauri-Desktop-hackathons-paypal-ai/7fe40038-1fc8-4bbd-a54c-d74e1e02ecd1/scratchpad`.
Write `$SP/guard_snapshot.py`:

```python
"""Every practice dispute (cases/PP-D-*.json) through the rules judge and the guard, and every shipped demo dispute
review's judgment through the guard again, as JSON. Run before and after a change that touches guard.py: the two
outputs must be byte-identical. Usage: python3 guard_snapshot.py <repo>"""
import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from secondlook import __main__ as cli  # noqa: E402
from secondlook.demo import DemoPayPal  # noqa: E402
from secondlook.guard import Judgment, apply_policy  # noqa: E402
from secondlook.paypal import MockPayPal  # noqa: E402

pp = MockPayPal(root / "cases", Path(tempfile.mkdtemp()) / "actions.jsonl")
out = {f.stem: asdict(cli.review(pp, f.stem, "rules")) for f in sorted((root / "cases").glob("PP-D-*.json"))}
policy = json.loads((root / "policy.json").read_text())
demo = DemoPayPal()
for f in sorted((root / "demo" / "reviews").glob("DEMO-[0-9]*.json")):
    raw = json.loads(f.read_text())
    try:
        case = demo.get_case(f.stem)
    except StopIteration:
        continue
    out[f.stem] = asdict(apply_policy(Judgment(**raw["judgment"]), policy, case["dispute"], case["seller_records"]))
print(json.dumps(out, indent=1, sort_keys=True, default=str))
```

- [ ] **Step 2: Record the baseline and run the suite**

```bash
python3 $SP/guard_snapshot.py "$PWD" > $SP/cs-snap-base.json && wc -c $SP/cs-snap-base.json
for f in tests/test_*.py; do python3 "$f" >/dev/null || echo "FAIL $f"; done
```
Expected: a non-empty JSON file; the suite prints nothing.

---

### Task 1: `state.py`, the one state of a case

**Files:** Create `secondlook/state.py`, `tests/test_state.py`.

- [ ] **Step 1: Write the failing tests** (`tests/test_state.py`)

```python
"""Every case is in exactly one state, decided in one place (spec 2026-10-30, Part 1). Run: python3 tests/test_state.py"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secondlook import state  # noqa: E402

TODAY = date(2026, 10, 20)


def dispute(status="WAITING_FOR_SELLER_RESPONSE", stage="INQUIRY", messages=(), **more):
    return {"dispute_id": "D1", "create_time": "2026-10-19T11:00:00Z", "status": status,
            "dispute_life_cycle_stage": stage, "seller_response_due_date": "2026-11-08T11:00:00Z",
            "dispute_amount": {"value": "29.00", "currency_code": "EUR"},
            "disputed_transactions": [{"buyer": {"name": "Pablo García"}}],
            "messages": [{"posted_by": "BUYER", "time_posted": "2026-10-19T11:00:00.000Z", "content": "Stuck."},
                         *messages], **more}


def case(status="open", money=(), unconfirmed=None, dispute_id=None):
    c = {"id": "C1", "customer": {"name": "Margot Lefèvre"}, "status": status, "dispute_id": dispute_id,
         "money": list(money), "timeline": []}
    if unconfirmed:
        c["unconfirmed"] = unconfirmed
    return c


def test_a_paypal_inquiry_nobody_answered_is_your_move_until_paypal_s_date():
    s = state.of(None, dispute(), TODAY, holder="luca")
    assert (s["state"], s["whose"], s["until"], s["paypal"]) == ("your_move", "luca", date(2026, 11, 8), True)
    assert s["then"].startswith("Answer by 08 Nov") and s["label"] == "Your move"


def test_a_reply_on_an_inquiry_waits_for_the_customer_until_paypal_closes_it():
    s = state.of(None, dispute(), TODAY, answered_at="2026-10-20T05:52")
    assert (s["state"], s["whose"], s["until"]) == ("waiting_customer", "customer", date(2026, 11, 8))
    assert s["then"] == "If Pablo doesn't escalate by 8 Nov, PayPal closes the dispute."


def test_a_refund_waits_for_paypal_and_the_demo_s_confirmation_makes_it_done():
    s = state.of(None, dispute(), TODAY, answered_at="2026-10-20T05:52", money_sent=True)
    assert (s["state"], s["whose"]) == ("waiting_paypal", "paypal") and "Pablo" in s["why"]
    s = state.of(None, dispute(), TODAY, answered_at="2026-10-20T05:52", money_sent=True,
                 confirmed_at="2026-10-30T08:00")
    assert s["state"] == "done" and "demo: simulated" in s["why"]


def test_the_buyer_writing_after_the_answer_makes_it_your_move_again():
    later = {"posted_by": "BUYER", "time_posted": "2026-10-21T09:00:00.000Z", "content": "Still nothing."}
    s = state.of(None, dispute(messages=[later]), TODAY, answered_at="2026-10-20T05:52", holder="giulia")
    assert (s["state"], s["whose"], s["why"]) == ("your_move", "giulia", "Pablo wrote again.")


def test_paypal_s_own_statuses():
    assert state.of(None, dispute(status="UNDER_REVIEW", stage="CHARGEBACK"), TODAY)["state"] == "waiting_paypal"
    s = state.of(None, dispute(status="WAITING_FOR_BUYER_RESPONSE", buyer_response_due_date="2026-10-30T00:00:00Z"), TODAY)
    assert (s["state"], s["until"]) == ("waiting_customer", date(2026, 10, 30))
    assert state.of(None, dispute(status="RESOLVED"), TODAY)["state"] == "done"


def test_evidence_on_a_claim_leaves_the_decision_to_paypal():
    s = state.of(None, dispute(stage="CHARGEBACK"), TODAY, answered_at="2026-10-20T05:52")
    assert (s["state"], s["whose"]) == ("waiting_paypal", "paypal")


def test_a_shop_request_answered_waits_for_the_customer_until_it_closes_itself():
    s = state.of(case(), None, TODAY, answered_at="2026-10-20T05:41", closes_on=date(2026, 10, 23))
    assert (s["state"], s["until"], s["paypal"]) == ("waiting_customer", date(2026, 10, 23), False)
    assert s["then"] == "If Margot doesn't write, it closes itself on 23 Oct."


def test_a_shop_request_is_your_move_with_no_paypal_deadline_said_plainly():
    s = state.of(case(), None, TODAY)
    assert (s["state"], s["until"], s["why"]) == ("your_move", None, "Waiting for your answer.")
    assert s["then"] == "No PayPal deadline: this came to the shop, not to PayPal."
    assert state.of(case(), None, TODAY, answered_at="2026-10-20T05:41")["why"] == "Margot wrote again."


def test_what_keeps_a_shop_request_on_your_move_says_why():
    assert state.of(case(), None, TODAY, holder="giulia", handoff_from="Marta")["why"] == "Passed to you by Marta."
    assert "check the payment in PayPal" in state.of(case(unconfirmed=[{"amount": 9}]), None, TODAY)["why"]
    logged = case(money=[{"kind": "refund", "amount": 64.0}])
    assert state.of(logged, None, TODAY, answered_at="2026-10-20T05:41")["why"] == \
        "A refund is logged: mark it paid, then close the case."
    paid = case(money=[{"kind": "refund", "amount": 64.0, "status": "paid"}])
    assert state.of(paid, None, TODAY, answered_at="2026-10-20T05:41")["why"] == \
        "Refunded or replaced: close the case with what happened."


def test_a_review_out_of_date_is_your_move_whatever_was_sent():
    s = state.of(None, dispute(), TODAY, answered_at="2026-10-20T05:52", money_sent=True, out_of_date=True)
    assert (s["state"], s["why"]) == ("your_move", "Changed since the last look: take a fresh look.")


def test_a_closed_case_is_done_whatever_its_dispute_says():
    assert state.of(case(status="closed"), dispute(), TODAY)["state"] == "done"


def test_every_state_has_a_label():
    assert set(state.LABEL) == set(state.STATES)


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
```

- [ ] **Step 2: Run it to see it fail**

Run: `python3 tests/test_state.py`
Expected: `ImportError: cannot import name 'state'`.

- [ ] **Step 3: Write `secondlook/state.py`**

```python
"""Every case is in exactly one state, decided here and nowhere else (spec docs/specs/2026-10-30-case-states-and-moves-
design.md, Part 1): Your move, Waiting for the customer, Waiting for PayPal, Done.

Before this, whose move it was came from five places that disagreed (web.page_offer, today.needs_you,
ledger.if_nobody_answers, web.close_quiet with _closes_words, web._handoff_waits): a case Giulia refunded stayed in
her Needs you. Pure: no file, no PayPal, no clock. web.case_state() gathers the facts; Today, the case page and the
API read what this returns.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from . import ledger

YOUR_MOVE, WAITING_CUSTOMER, WAITING_PAYPAL, DONE = "your_move", "waiting_customer", "waiting_paypal", "done"
STATES = (YOUR_MOVE, WAITING_CUSTOMER, WAITING_PAYPAL, DONE)
LABEL = {YOUR_MOVE: "Your move", WAITING_CUSTOMER: "Waiting for the customer", WAITING_PAYPAL: "Waiting for PayPal",
         DONE: "Done"}


def _day(iso) -> date | None:
    try:
        return datetime.strptime(str(iso)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _first_name(case: dict | None, dispute: dict | None) -> str:
    name = ((case or {}).get("customer") or {}).get("name") or \
        ((((dispute or {}).get("disputed_transactions") or [{}])[0].get("buyer")) or {}).get("name") or ""
    return name.split(" ")[0] or "the customer"


def _buyer_wrote_since(dispute: dict, at: str) -> bool:
    """The buyer posted on the dispute after the shop's answer (both compared as UTC minutes, "2026-10-20T05:52")."""
    return any(m.get("posted_by") == "BUYER" and str(m.get("time_posted") or "")[:16] > at[:16]
               for m in dispute.get("messages", []))


def of(case: dict | None, dispute: dict | None, today: date, *, answered_at: str | None = None,
       money_sent: bool = False, out_of_date: bool = False, holder: str | None = None,
       handoff_from: str | None = None, closes_on: date | None = None, confirmed_at: str | None = None) -> dict:
    """The one state of a case, first match wins: Done, Waiting for PayPal, Waiting for the customer, Your move.
    `case`: the shop's case, or None for a PayPal dispute no other channel joined; `dispute`: its PayPal dispute, if
    any. `answered_at`: when the shop's answer from Second Look went (UTC minute), None if none did; `money_sent`: that
    answer sent a refund; `out_of_date`: the review changed under it (the case page knows; Today doesn't ask);
    `holder`: the person who has the case (their id); `handoff_from`: the colleague who passed it to them;
    `closes_on`: when an answered shop request closes itself (cases.closes_on); `confirmed_at`: the demo shop's
    simulated PayPal confirmation of a refund (web.demo_confirmed: never on the sandbox or a live shop).
    Returns {state, label, whose, why, until, then, paypal}: whose = a person's id (None: nobody has it yet),
    "customer", "paypal", or None once done; until = the date that matters, or None; paypal = a PayPal dispute is on it."""
    name = _first_name(case, dispute)
    status = (dispute or {}).get("status")
    stage = (dispute or {}).get("dispute_life_cycle_stage")

    def out(state, whose, why, until=None, then=""):
        return {"state": state, "label": LABEL[state], "whose": whose, "why": why, "until": until, "then": then,
                "paypal": dispute is not None}
    if case is not None and case.get("status") != "open":
        return out(DONE, None, "Closed.")
    if status == "RESOLVED":
        return out(DONE, None, "PayPal closed the dispute.")
    if confirmed_at:
        return out(DONE, None, "PayPal confirmed the refund and closed the dispute (demo: simulated).")
    if status == "UNDER_REVIEW":
        return out(WAITING_PAYPAL, "paypal", "PayPal is deciding.", then=ledger.if_nobody_answers(dispute, today))
    # an answer counts until something new comes in: the buyer posting after it, or the review going out of date
    answered = bool(answered_at) and not out_of_date and not (dispute and _buyer_wrote_since(dispute, answered_at))
    if dispute and answered and money_sent:
        return out(WAITING_PAYPAL, "paypal", f"PayPal pays {name} back and closes the dispute.",
                   then="It comes back to you only if PayPal refuses or the refund fails.")
    if dispute and answered and stage != "INQUIRY":
        return out(WAITING_PAYPAL, "paypal", "PayPal is deciding the claim with your answer.",
                   then="PayPal usually decides in about 10 days.")
    if dispute and status == "WAITING_FOR_BUYER_RESPONSE":
        return out(WAITING_CUSTOMER, "customer", f"Answered. Waiting for {name}.",
                   _day(dispute.get("buyer_response_due_date")), ledger.if_nobody_answers(dispute, today))
    if dispute and answered:
        # The demo's PayPal never moves a status; a live one says WAITING_FOR_BUYER_RESPONSE (above). Either way an
        # inquiry the buyer doesn't escalate in 20 days is closed by PayPal.
        opened = _day(dispute.get("create_time"))
        until = opened + timedelta(days=ledger.INQUIRY_DAYS) if opened else None
        when = f" by {until.day} {until:%b}" if until else " within 20 days"
        return out(WAITING_CUSTOMER, "customer", f"Answered. Waiting for {name}.", until,
                   f"If {name} doesn't escalate{when}, PayPal closes the dispute.")
    if case is not None and not dispute and closes_on and not out_of_date:
        return out(WAITING_CUSTOMER, "customer", f"Answered. Waiting for {name}.", closes_on,
                   f"If {name} doesn't write, it closes itself on {closes_on.day} {closes_on:%b}.")
    c = case or {}
    refunds = [m for m in c.get("money", []) if m.get("kind") in ("refund", "partial_refund")]
    if handoff_from:
        why = f"Passed to you by {handoff_from}."
    elif c.get("unconfirmed"):
        why = "PayPal didn't confirm a refund: check the payment in PayPal."
    elif out_of_date:
        why = "Changed since the last look: take a fresh look."
    elif answered_at and any(m.get("status") not in ("paid", "cancelled") for m in refunds):
        why = "A refund is logged: mark it paid, then close the case."
    elif answered_at and c.get("money"):
        why = "Refunded or replaced: close the case with what happened."
    elif answered_at:
        why = f"{name} wrote again."
    else:
        why = "Waiting for your answer."
    if dispute:
        due = _day(dispute.get("seller_response_due_date")) if status == "WAITING_FOR_SELLER_RESPONSE" else None
        return out(YOUR_MOVE, holder, why, due, ledger.if_nobody_answers(dispute, today))
    return out(YOUR_MOVE, holder, why, None, "No PayPal deadline: this came to the shop, not to PayPal.")
```

- [ ] **Step 4: Run it to see it pass**

Run: `python3 tests/test_state.py`
Expected: `12 passed`.

- [ ] **Step 5: Commit**

```bash
git add secondlook/state.py tests/test_state.py
git commit -m "state.of: every case in exactly one state, decided in one place

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `moves.py`, the catalog

**Files:** Create `secondlook/moves.py`, `tests/test_moves.py`.

- [ ] **Step 1: Write the failing tests** (`tests/test_moves.py`)

```python
"""The moves: what fits each cause, what PayPal allows, and fixed texts that never promise money a move doesn't send
(spec 2026-10-30, Part 2). Run: python3 tests/test_moves.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secondlook import moves  # noqa: E402

FACTS = {"first": "Sophie", "carrier": "Local courier", "tracking": " (tracking LC90001IT)", "amount": "64.00 EUR",
         "order": "LP-90001", "delivered": " on 15 Oct", "shop": "Linen & Paper"}


def test_the_cause_comes_from_paypal_s_reason_else_the_shop_s_case():
    assert moves.kind_of(None, {"reason": "CREDIT_NOT_PROCESSED"}) == "refund_missing"
    assert moves.kind_of({"problem": {"kind": "wrong_size"}}, None) == "wrong_size"
    assert moves.kind_of({"problem": {"kind": "something new"}}, None) == "question"


def test_at_most_two_others_that_fit_never_the_pick_never_a_defence_on_a_shop_request():
    assert moves.others("not_received", "REFUND", None, inquiry=False) == ["MESSAGE", "DEFEND"]
    assert moves.others("not_received", "MESSAGE", None, inquiry=True) == ["REFUND", "REPLACE"]
    assert moves.others("wrong_size", "REPLACE", None, inquiry=True) == ["REFUND", "MESSAGE"]
    assert moves.others("question", "MESSAGE", None, inquiry=True) == []


def test_only_what_paypal_allows_on_a_dispute():
    assert moves.others("not_received", "REFUND", {"DEFEND", "REFUND"}, inquiry=False) == ["DEFEND"]
    assert moves.others("not_as_described", "REFUND", set(), inquiry=False) == []


def test_no_text_promises_money_its_move_doesn_t_send():
    for kind in moves.FITS:
        for action in ("MESSAGE", "REPLACE", "DEFEND"):
            assert "refund" not in moves.text(action, kind, FACTS).lower(), (action, kind)
    assert "64.00 EUR" in moves.text("REFUND", "not_received", FACTS)


def test_texts_are_filled_with_the_case_s_facts_and_signed_by_the_shop():
    t = moves.text("MESSAGE", "not_received", FACTS)
    assert t.startswith("Hi Sophie,") and "Local courier" in t and "LC90001IT" in t and t.endswith("Linen & Paper")
    assert moves.text("MESSAGE", "question", {}).startswith("Hi there,")      # a fact missing: never a crash


def test_each_button_says_everything_it_sends_and_what_happens_next():
    assert moves.label("REFUND", False, FACTS) == "Answer and refund 64.00 EUR"
    assert moves.label("REPLACE", True, FACTS) == "Answer and exchange"
    assert moves.label("MESSAGE", False, FACTS) == "Reply only"
    assert moves.then("MESSAGE", FACTS, inquiry=True) == "Sophie gets your reply. No money moves."
    assert "PayPal" in moves.then("REFUND", FACTS, inquiry=False)


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
```

- [ ] **Step 2: Run it to see it fail**

Run: `python3 tests/test_moves.py`
Expected: `ImportError: cannot import name 'moves'`.

- [ ] **Step 3: Write `secondlook/moves.py`**

```python
"""The moves: everything a shop can do on a case now, defined once (spec docs/specs/2026-10-30-case-states-and-moves-
design.md, Part 2). Moves are Second Look's actions: MESSAGE (reply only), REFUND, REPLACE (exchange or replace),
DEFEND (send your evidence). "Decide later" and "pass to a colleague" send nothing and need no entry here.

Second Look's AI recommends one; a person may choose another that fits the cause and that PayPal (on a dispute)
allows. Every move but the AI's own pick comes with a fixed text filled with the case's facts, never the AI's draft:
a draft written for a refund must never go out with a move that sends none (DEMO-034, 21/10). Pure: web gives it the
case's cause, the AI's pick and what PayPal allows (guard.paypal_can).
"""
from __future__ import annotations

REASON_KIND = {"MERCHANDISE_OR_SERVICE_NOT_RECEIVED": "not_received",
               "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED": "not_as_described",
               "CREDIT_NOT_PROCESSED": "refund_missing"}
# Which moves fit each cause, most likely first (the spec's table). The keys are cases.KINDS.
FITS = {"not_received": ("MESSAGE", "DEFEND", "REFUND", "REPLACE"),
        "not_as_described": ("MESSAGE", "REFUND", "REPLACE"),
        "wrong_size": ("REPLACE", "REFUND", "MESSAGE"),
        "refund_missing": ("MESSAGE", "REFUND"),
        "question": ("MESSAGE",)}
OTHERS = 2      # at most two moves beside the AI's pick: more is a menu, not a decision

SIGN = "\n\nBest regards,\n{shop}"
TEMPLATES = {
    "MESSAGE": {
        "not_received": "Hi {first},\n\nthank you for writing, and sorry the parcel hasn't reached you. We're checking "
                        "with {carrier} what happened to it{tracking} and will write to you again within two working days.",
        "not_as_described": "Hi {first},\n\nthank you for telling us, and sorry it isn't what you expected. Could you send "
                            "us a photo of the item and of what doesn't match the listing? Then we can put it right.",
        "wrong_size": "Hi {first},\n\nthank you for writing, and sorry the size isn't right. Tell us the size you need "
                      "and we'll tell you how to send this one back.",
        "refund_missing": "Hi {first},\n\nthank you for writing. We're checking our records for your return and will "
                          "write to you again within two working days.",
        "question": "Hi {first},\n\nthank you for your message. We're looking into it and will write to you again "
                    "within two working days.",
    },
    "REFUND": {"*": "Hi {first},\n\nwe're sorry for the trouble. We have refunded {amount} in full for order {order}. "
                    "You'll see it back on your account in a few days."},
    "REPLACE": {
        "wrong_size": "Hi {first},\n\nwe're sorry the size isn't right. We'll send you the right size as soon as this "
                      "one is on its way back to us; the return details follow in a separate email.",
        "*": "Hi {first},\n\nwe're sorry for the trouble. We're sending you a replacement for order {order}, and will "
             "write with its tracking number as soon as it ships.",
    },
    "DEFEND": {"*": "Hi {first},\n\nour records show your parcel was delivered{delivered}{tracking}. We've shared the "
                    "courier's record with PayPal. If something is still wrong, please write to us and we'll look again."},
}
# When the case has no such fact, the words a text falls back on.
FACT_DEFAULTS = {"first": "there", "carrier": "the courier", "tracking": "", "amount": "the full amount",
                 "order": "your order", "delivered": "", "shop": "the shop"}
LABEL = {"MESSAGE": "Reply only", "REFUND": "Answer and refund {amount}", "REPLACE": "Answer and send a replacement",
         "DEFEND": "Send your evidence"}
INQUIRY_LABEL = {**LABEL, "REPLACE": "Answer and exchange"}
THEN = {"MESSAGE": "{first} gets your reply. No money moves.",
        "REFUND": "{first} gets your reply and {amount} back. PayPal closes the dispute; the case waits for PayPal "
                  "to confirm.",
        "REPLACE": "{first} gets your reply; the replacement is logged for you to send.",
        "DEFEND": "PayPal gets the courier's record and {first} your reply. No money moves."}
INQUIRY_THEN = {**THEN, "REFUND": "{first} gets your reply, and the refund of {amount} is logged on the case."}


def _fill(words: str, facts: dict) -> str:
    return words.format(**{**FACT_DEFAULTS, **{k: v for k, v in facts.items() if v}})


def kind_of(case: dict | None, dispute: dict | None) -> str:
    """The cause, as cases.KINDS names it: PayPal's reason on a dispute, else the shop case's own kind."""
    if dispute and dispute.get("reason") in REASON_KIND:
        return REASON_KIND[dispute["reason"]]
    k = ((case or {}).get("problem") or {}).get("kind")
    return k if k in FITS else "question"


def others(kind: str, pick: str | None, paypal: set | None, inquiry: bool) -> list:
    """The moves to offer beside the AI's pick, in FITS order: ones that fit the cause, that PayPal allows on a dispute
    (`paypal`: guard.paypal_can, None when PayPal didn't say), never a defence on a shop request (there is no claim to
    defend), never the pick itself. At most OTHERS."""
    out = []
    for a in FITS.get(kind, FITS["question"]):
        if a == pick or (inquiry and a == "DEFEND") or (not inquiry and paypal is not None and a not in paypal):
            continue
        out.append(a)
    return out[:OTHERS]


def text(action: str, kind: str, facts: dict) -> str:
    """The fixed reply that goes with a move, filled with the case's facts and signed by the shop. A person may edit it."""
    t = TEMPLATES.get(action) or TEMPLATES["MESSAGE"]
    return _fill((t.get(kind) or t.get("*") or TEMPLATES["MESSAGE"]["question"]) + SIGN, facts)


def label(action: str, inquiry: bool, facts: dict) -> str:
    """The button: everything the move sends ("Answer and refund 29.00 EUR")."""
    return _fill((INQUIRY_LABEL if inquiry else LABEL)[action], facts)


def then(action: str, facts: dict, inquiry: bool) -> str:
    """What happens next, joined under the button."""
    return _fill((INQUIRY_THEN if inquiry else THEN)[action], facts)
```

- [ ] **Step 4: Run it to see it pass**

Run: `python3 tests/test_moves.py`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add secondlook/moves.py tests/test_moves.py
git commit -m "moves: one catalog of what fits each cause, with fixed texts that send no promise

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: the guard reads PayPal once, and lets a person choose a catalog move

**Files:** Modify `secondlook/guard.py` (rule 6 at lines 190–215; `may_approve` at 292–311). Test: `tests/test_guard.py`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_guard.py`, before its `if __name__` block; it already
imports `guard` names — add `paypal_can` to that import line)

```python
def test_paypal_can_reads_what_paypal_allows_once_for_rule_6_and_the_moves():
    d = {"status": "WAITING_FOR_SELLER_RESPONSE", "links": [{"rel": "provide_evidence"}, {"rel": "send_message"}],
         "allowed_response_options": {"accept_claim": {"accept_claim_types": ["REFUND"]},
                                      "make_offer": {"offer_types": ["REFUND"]}}}
    assert paypal_can(d) == {"DEFEND", "MESSAGE", "REFUND", "PARTIAL_REFUND"}
    assert "MESSAGE" not in paypal_can({**d, "status": "WAITING_FOR_BUYER_RESPONSE"})
    assert paypal_can({"status": "WAITING_FOR_SELLER_RESPONSE"}) is None          # PayPal didn't say


def test_a_catalog_move_goes_unless_a_trust_reason_stands_against_it():
    assert may_approve("REFUND", "MESSAGE", "REFUND", [], template=True)
    assert not may_approve("REFUND", "MESSAGE", "REFUND", ["message_not_allowed"], template=True)
    assert may_approve("ASK_SELLER", "REFUND", "REFUND", ["cap", "confidence"], template=True)
    assert not may_approve("ASK_SELLER", "REFUND", "MESSAGE", ["injection"], template=True)
    assert not may_approve("ASK_SELLER", "REPLACE", "MESSAGE", ["already_refunded"], template=True)
    assert may_approve("REFUND", "DEFEND", "REFUND", ["cap"], template=True)
    assert not may_approve("REFUND", "DEFEND", "REFUND", ["refund_logged_on_case"], template=True)
    assert not may_approve("REFUND", "ASK_SELLER", "REFUND", [], template=True)
    assert not may_approve("REFUND", "MESSAGE", "REFUND", [])                      # without the catalog: as before
```

- [ ] **Step 2: Run it to see it fail**

Run: `python3 tests/test_guard.py`
Expected: `ImportError: cannot import name 'paypal_can'`.

- [ ] **Step 3: Move rule 6's reading of PayPal into `paypal_can`**

Add above `apply_policy` (after `money_out`):

```python
def paypal_can(dispute: dict) -> set | None:
    """What PayPal lets the shop do on this dispute now, as Second Look's actions; None when PayPal didn't say
    (no allowed_response_options: a practice case, an old record). Rule 6 and the moves catalog (moves.py) read this
    one function, so a button never offers what PayPal would refuse. Learned from a real sandbox dispute (2026-10-16):
    at the INQUIRY stage make_offer allows only REFUND, so REPLACE is not possible."""
    allowed = dispute.get("allowed_response_options")
    if not allowed:
        return None
    can = set()
    rels = {l.get("rel") for l in dispute.get("links", [])}
    if "provide_evidence" in rels:
        can.add("DEFEND")
    # PayPal keeps the send_message link while it waits for the buyer, but refuses a second seller
    # message then (422, seen live 2026-10-18): one message, then the buyer's turn.
    if "send_message" in rels and dispute.get("status") != "WAITING_FOR_BUYER_RESPONSE":
        can.add("MESSAGE")
    for t in allowed.get("accept_claim", {}).get("accept_claim_types", []):
        can.add({"REFUND": "REFUND", "PARTIAL_REFUND": "PARTIAL_REFUND"}.get(t, ""))
    for t in allowed.get("make_offer", {}).get("offer_types", []):
        can.add({"REFUND": "PARTIAL_REFUND", "REPLACEMENT_WITHOUT_REFUND": "REPLACE",
                 "REFUND_WITH_REPLACEMENT": "REPLACE"}.get(t, ""))
    can.discard("")
    return can
```

Replace rule 6 in `apply_policy` (from `# Rule 6: only actions PayPal allows at this stage.` down to its last
`stops.append("paypal_allowed")`) with:

```python
    # Rule 6: only actions PayPal allows at this stage (paypal_can).
    can = paypal_can(dispute)
    if can is not None:
        # Recorded on its own: PayPal may refuse the AI's answer (DEFEND at INQUIRY) and still take a
        # message, so "paypal_allowed" must not stop the question; this does (PP-R-ZOY-10193120, 23/10).
        if "MESSAGE" not in can:
            stops.append("message_not_allowed")
        subject = _subject()
        if subject != "ASK_SELLER" and subject not in can:
            notes.append(f"PayPal does not allow {subject} at the {dispute.get('dispute_life_cycle_stage', '?')} stage "
                         f"(allowed: {', '.join(sorted(can))}). Routed to you.")
            action = "ASK_SELLER"
            stops.append("paypal_allowed")
```

(The note's list was `sorted(c for c in can if c)`; `paypal_can` already drops the empty string, so the words are
the same.)

- [ ] **Step 4: Add the template path to `may_approve`**

Above `may_approve`:

```python
# What held back the AI's own answer and says nothing against a person choosing a catalog move themselves: its size,
# its confidence, and PayPal refusing the AI's pick (the moves offered are PayPal's allowed ones already).
TEMPLATE_OK_STOPS = SIZE_STOPS | {"confidence", "paypal_allowed"}
```

Change the signature to
`def may_approve(recommended: str, chosen: str, drafted_for: str | None = None, stops: Sequence[str] = (), template: bool = False) -> bool:`,
append to its docstring:

```
    `template`: the person chose a move from the catalog (moves.py) with its own fixed text, never the AI's draft
    (spec 2026-10-30, Part 2). A reply goes unless PayPal takes no message; money or goods only when nothing but
    TEMPLATE_OK_STOPS held the AI back (never past a trust stop); evidence never against a refund or a replacement
    already logged, an unconfirmed refund, or evidence the judge found inconsistent.
```

and make its first lines:

```python
    if template:
        held = set(stops)
        if chosen == "MESSAGE":
            return "message_not_allowed" not in held
        if chosen in MONEY:
            return not (held - TEMPLATE_OK_STOPS)
        if chosen == "DEFEND":
            return not held & {"refund_logged_on_case", "replacement_logged_on_case", "refund_unconfirmed",
                               "inconsistent"}
        return False
```

- [ ] **Step 5: Run the guard tests, the snapshot and the suite**

```bash
python3 tests/test_guard.py
python3 $SP/guard_snapshot.py "$PWD" > $SP/cs-snap-3.json && cmp $SP/cs-snap-base.json $SP/cs-snap-3.json && echo SAME
for f in tests/test_*.py; do python3 "$f" >/dev/null || echo "FAIL $f"; done
```
Expected: the guard tests pass; `SAME`; the suite prints nothing.

- [ ] **Step 6: Commit**

```bash
git add secondlook/guard.py tests/test_guard.py
git commit -m "guard: paypal_can reads what PayPal allows once; a catalog move never passes a trust stop

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: what a case's state is read from

`web.case_state()` gathers the facts `state.of` needs. The saved review starts keeping what was chosen and how much
it sent (it kept only the recommendation, so a refund looked like any answer). The demo shop gets its simulated PayPal
confirmation.

**Files:** Modify `secondlook/web.py` (`_save` ~173, `_approve` ~3795, new functions after `_closes_words` ~1262).
Test: `tests/test_web.py`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_web.py`, before `if __name__`)

```python
def test_a_sent_answer_keeps_what_was_chosen_and_how_much_it_sent():
    with approval_bench():
        web.approve("X", "REFUND", "Here is your refund", by="giulia")
        raw = web._raw("X")
        assert (raw["chosen"], raw["amount"], raw["action"]) == ("REFUND", 45.0, "REFUND") and web._sent_refund(raw)
    assert web._sent_refund({"sent": "Refund accepted and reply sent."})                 # a review saved before 30/10
    assert not web._sent_refund({"sent": "Reply sent."}) and not web._sent_refund({})


def test_the_state_of_a_dispute_follows_what_was_sent():
    with approval_bench():
        assert web.case_state("X")["state"] == "your_move"
        web.approve("X", "REFUND", "Here is your refund", by="giulia")
        s = web.case_state("X")
        assert (s["state"], s["decision_id"]) == ("waiting_paypal", "X")
    with approval_bench(action="ASK_SELLER", ai="MESSAGE", stops=["always_ask"], amount="20.00"):
        web.approve("X", "MESSAGE", "We're on it", by="giulia")
        assert web.case_state("X")["state"] == "waiting_customer"


def test_a_handoff_is_the_receiver_s_move_and_says_who_passed_it():
    with approval_bench():
        assert web.approve("X", "REFUND", "Here is your refund", by="marta")[0] == 202      # 45 EUR: over Marta's 30
        s = web.case_state("X")
        assert (s["state"], s["whose"], s["why"]) == ("your_move", "giulia", "Passed to you by Marta.")


def test_the_demo_s_paypal_confirms_a_refund_at_the_next_look_and_only_in_the_demo():
    tmp = Path(tempfile.mkdtemp())
    kept = web.REVIEWS
    try:
        web.REVIEWS = tmp / "reviews"
        web.REVIEWS.mkdir()
        refund = {"sent": "Refund accepted and reply sent.", "chosen": "REFUND", "at": "2026-10-30T08:00"}
        (web.REVIEWS / "DEMO-039.json").write_text(json.dumps(refund))
        (web.REVIEWS / "DEMO-031.json").write_text(json.dumps({"sent": "Reply sent.", "chosen": "MESSAGE"}))
        (web.REVIEWS / "PP-R-ABC-1.json").write_text(json.dumps(refund))
        assert web.confirm_demo_refunds() == ["DEMO-039"] and web.confirm_demo_refunds() == []
        assert list(web.demo_confirmed()) == ["DEMO-039"]
    finally:
        web.REVIEWS = kept
```

- [ ] **Step 2: Run them to see them fail**

Run: `python3 tests/test_web.py`
Expected: `KeyError: 'chosen'` in the first new test.

- [ ] **Step 3: Keep the choice in the review**

In `web.py`, change `_save` to:

```python
def _save(dispute_id: str, d: Decision, sent=None, seen=None, by=None, at=None, judge=None, chosen=None,
          amount=None) -> None:
    REVIEWS.mkdir(parents=True, exist_ok=True)
    extra = {"judge": judge} if judge else {}
    if chosen:      # what went out, and the money it sent: the review itself keeps showing what was recommended
        extra.update(chosen=chosen, amount=amount)
    (REVIEWS / f"{dispute_id}.json").write_text(json.dumps({**asdict(d), "sent": sent, "seen": seen,
                                                            "by": by, "at": at, **extra}, ensure_ascii=False))
```

In `_approve`, change the `_save(...)` call after `seen` is settled to:

```python
    _save(did, dec, sent, seen, by=by_name, at=now.isoformat(timespec="minutes"), judge=judged, chosen=chosen,
          amount=round(amount, 2) if amount else None)
```

- [ ] **Step 4: Add `_sent_refund`, the demo confirmations and `case_state`**

Add `from . import state as state_mod` to the `from . import …` line (alphabetical: after `sort as sort_mod`). Then,
after `_closes_words`:

```python
REFUNDS = ("REFUND", "PARTIAL_REFUND")


def _sent_refund(raw: dict | None) -> bool:
    """The answer that went out sent money back. A review sent before 30/10 doesn't say what was chosen: its own
    sentence does ("Refund accepted…", "Partial refund…", "Refund of 64.00 EUR logged…")."""
    raw = raw or {}
    if not raw.get("sent"):
        return False
    if raw.get("chosen"):
        return raw["chosen"] in REFUNDS
    return str(raw["sent"]).startswith(("Refund", "Partial refund"))


def _confirmed_file() -> Path:
    # beside the reviews: every test bench that moves them moves this too
    return REVIEWS.parent / "paypal-demo-confirmed.json"


def demo_confirmed() -> dict:
    """The demo shop's PayPal confirmations of refunds sent from Second Look: {dispute id: when}. Simulated, and every
    page that shows one says so (spec 2026-10-30, Part 4). Only the demo's disputes (DEMO-031…) are ever here."""
    try:
        return json.loads(_confirmed_file().read_text())
    except (OSError, ValueError):
        return {}


def confirm_demo_refunds() -> list:
    """The look after a refund in the demo shop: its PayPal "confirms" it, as a real one would within minutes, so the
    film can show a case reach Done. Nothing in the demo reaches PayPal, so without this a refunded case waited for
    PayPal forever. Never on the sandbox or a live shop. Returns the ids confirmed now."""
    done, new = demo_confirmed(), []
    for f in sorted(REVIEWS.glob("DEMO-*.json")) if REVIEWS.exists() else []:
        if re.fullmatch(r"DEMO-\d+", f.stem) and f.stem not in done and _sent_refund(_raw(f.stem)):
            done[f.stem] = cases_mod.minute(None)
            new.append(f.stem)
    if new:
        _confirmed_file().parent.mkdir(parents=True, exist_ok=True)
        _confirmed_file().write_text(json.dumps(done))
    return new


def case_state(did: str, dispute: dict | None = None, c: dict | None = None, out_of_date: bool = False,
               today=None) -> dict:
    """The one state of a case (state.of), from what Second Look holds: the review and what was sent, who has the case,
    its shop case and its PayPal dispute. `did`: the decision id (the PayPal dispute's, else the shop case's).
    `dispute`, `c`: when the caller has them already (Today reads every case once). `out_of_date`: the case page's own
    finding (_changes); Today doesn't ask. Returns state.of's dict plus "decision_id"."""
    if cases_mod.is_case_id(did):
        src = shop_of_case(did)
        c = c if c is not None else case_store(src).get(did)
        if c is not None and c.get("dispute_id"):
            return case_state(c["dispute_id"], None, c, out_of_date, today)   # a dispute on it: PayPal's rules
    else:
        src = src_of_case(did, "live")
        if dispute is None:
            dispute = _case(did)["dispute"]
        if c is None and src in CASE_FILES:
            c = find_case_of_dispute(did)
    raw = _raw(did) or {}
    # sent with no time recorded (a review older than its `at`): nothing the buyer said can be "since" it
    answered_at = ((_utc_minute(raw["at"]) if raw.get("at") else "9999-12-31T23:59") if raw.get("sent") else None)
    t = team_for(did)
    a = None if t.get("solo") else assignments_for(did).get(did)
    hand = (a or {}).get("handoff") if isinstance((a or {}).get("handoff"), dict) and not raw.get("sent") else None
    frm = None
    if hand:
        p = team_mod.person(t, hand.get("from"))
        frm = (p or {}).get("name") or hand.get("from_name") or "a colleague"
    closes = cases_mod.closes_on(c, quiet_days()) if c is not None and dispute is None and not hand else None
    confirmed = demo_confirmed().get(did) if is_demo(did) and not cases_mod.is_case_id(did) else None
    st = state_mod.of(c, dispute, today or shop_today(src if src in ("demo", "live") else "live"),
                      answered_at=answered_at, money_sent=_sent_refund(raw), out_of_date=out_of_date,
                      holder=(a or {}).get("to"), handoff_from=frm, closes_on=closes, confirmed_at=confirmed)
    return {**st, "decision_id": did}
```

- [ ] **Step 5: Run the tests and the suite**

Run: `python3 tests/test_web.py` then the full suite.
Expected: all pass; the suite prints nothing.

- [ ] **Step 6: Commit**

```bash
git add secondlook/web.py tests/test_web.py
git commit -m "case_state: the facts a case's state is read from; the demo's PayPal confirms a refund, labelled simulated

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Today's data reads the state

**Files:** Modify `secondlook/today.py` (`needs_you` ~260; new `waiting`, `closed_today`), `secondlook/web.py`
(`today_view` ~2644, `api_case` ~4153, `api_case_of` ~853, the `/api/today` route). Test: `tests/test_today.py`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_today.py`, before `if __name__`)

```python
def test_needs_you_holds_only_what_is_your_move_and_the_rest_waits_in_its_own_bucket():
    with morning():
        v = web.today_view("demo", "giulia")
        assert all(n["state"]["state"] == "your_move" for n in v["needs"] if n["kind"] == "case")
        assert [x["id"] for x in v["waiting"]["waiting_customer"]] == ["DEMO-C004"]    # Margot: the AI answered
        assert web.approve("DEMO-039", "REFUND", "Your refund is on its way.", by="giulia")[0] == 200
        v = web.today_view("demo", "giulia")
        assert [x["id"] for x in v["waiting"]["waiting_paypal"]] == ["DEMO-039"]
        assert "DEMO-039" not in [n.get("id") for n in v["needs"]]
        assert v["handled"]["cases"] == 1 and v["handled"]["minutes"] == 6


def test_a_case_closed_today_is_done_and_one_closed_before_is_not():
    cases = [case("C1", ("2026-10-19T08:00", "email", "in"), status="closed", closed_at="2026-10-20T09:00"),
             case("C2", ("2026-10-10T08:00", "email", "in"), status="closed", closed_at="2026-10-12T09:00")]
    done = today.closed_today(cases, [], TODAY, keep=lambda i: True)
    assert [x["id"] for x in done] == ["C1"] and done[0]["link"] == "/c/C1"
    assert today.closed_today(cases, [], TODAY, keep=lambda i: False) == []


def test_the_api_says_each_case_s_state():
    with morning():
        s = web.api_case_of("DEMO-C004")["state"]
        assert s["state"] == "waiting_customer" and s["until"] == "2026-10-23"
        assert web.api_case("DEMO-039")["state"]["state"] == "your_move"
```

- [ ] **Step 2: Run them to see them fail**

Run: `python3 tests/test_today.py`
Expected: `KeyError: 'state'` in the first new test.

- [ ] **Step 3: `today.py`: needs filtered by state, and the other buckets**

In `needs_you`, add the parameter `states=None` (last), add to its docstring "`states`: decision id -> case state
(web.case_state); a case that isn't the person's move waits in its own bucket (waiting())", and in its loop, right
after `a = assigned.get(it["id"]) or {}`:

```python
        st = (states or {}).get(it["id"])
        if st is not None and st["state"] != "your_move":
            continue            # answered, or PayPal's move: it waits in its own bucket, not here
```

and add `"state": st,` to the dict appended to `mine`. Then add after `needs_you`:

```python
def waiting(me: str | None, head: bool, items: list, assigned: dict, team: dict, states: dict, ai_ids=()) -> dict:
    """Today's other buckets (spec 2026-10-30, Part 3): this person's cases that wait for the customer or for PayPal,
    or are done though still open in PayPal's list (the demo's simulated confirmation). The head of customer care also
    sees what Second Look's AI answered (`ai_ids`): it answers for them. In a team of one, every case is the seller's.
    Each row is open_items' row with its "state"; the nearest date first."""
    solo = bool(team.get("solo"))
    out = {"waiting_customer": [], "waiting_paypal": [], "done": []}
    for it in items:
        st = states.get(it["id"])
        if not st or st["state"] not in out:
            continue
        if solo or (me and (assigned.get(it["id"]) or {}).get("to") == me) or (head and it["id"] in ai_ids):
            out[st["state"]].append({**it, "state": st})
    for k in out:
        out[k].sort(key=lambda x: (x["state"]["until"] is None, x["state"]["until"] or date.max))
    return out


def closed_today(cases: list, orders: list, today: date, keep) -> list:
    """Cases closed on the shop's today or later (the demo's clicks are stamped with the computer's date, after the
    demo's fixed today), as open_items rows. `keep(decision id)`: whether this person sees it (web decides)."""
    amount_of, currency_of = _amounts(orders), _currencies(orders)
    out = []
    for c in cases:
        did = c.get("dispute_id") or c["id"]
        if c.get("status") == "open" or _closed_at(c)[:10] < today.isoformat() or not keep(did):
            continue
        out.append({"id": did, "link": f"/c/{c['id']}",
                    "who": c["customer"].get("name") or c["customer"].get("email"),
                    "summary": c["problem"].get("summary") or "", "amount": amount_of.get(c.get("order_no"), 0.0),
                    "currency": currency_of.get(c.get("order_no")) or "EUR", "days_left": None,
                    "state": {"state": "done", "label": "Done", "whose": None, "why": "Closed.", "until": None,
                              "then": "", "paypal": bool(c.get("dispute_id"))}})
    return out
```

(`date` is already imported in `today.py`: `from datetime import date, timedelta`.)

- [ ] **Step 4: `web.today_view` computes every open case's state once**

In `today_view`, after `items = today_mod.open_items(cases, disputes, orders, today)`:

```python
    dmap = {d["dispute_id"]: d for d in disputes}
    held, cmap = today_mod.links(cases, disputes, orders), {c["id"]: c for c in cases}
    states = {it["id"]: case_state(it["id"], dmap.get(it["id"]), held.get(it["id"]) or cmap.get(it["id"]), today=today)
              for it in items}
```

After `unchecked = …`, add:

```python
    ai_ids = {h["id"] for h in autopilot_handled(src, today, rec, since=False)}
    me_id = who["id"] if who else None
    waiting = today_mod.waiting(me_id, head, items, assigned, t, states, ai_ids)
    waiting["done"] += today_mod.closed_today(
        cases, orders, today,
        lambda i: solo or (assigned.get(i) or {}).get("to") == me_id or (head and i in ai_ids))
    # today you handled: the answers this person sent today (the computer's day: the demo's clicks are real), at the
    # shop's reply minutes each, the same estimate as a case's cost
    name = (who or {}).get("name")
    sent_today = [i for i in [*states, *(x["id"] for x in waiting["done"])]
                  if (_raw(i) or {}).get("sent") and str(_saved_by(i).get("at") or "")[:10] == _local_now().date().isoformat()
                  and (solo or _saved_by(i).get("by") == name)]
    handled_n = len(set(sent_today))
```

and in the returned dict: change `needs` to pass `states=states` as the last argument of `today_mod.needs_you(...)`,
and add

```python
            "waiting": waiting,
            "handled": {"cases": handled_n, "minutes": handled_n * cases_mod.staff_time(_policy())["reply_minutes"]},
```

In the `/api/today` route, add `"waiting": v["waiting"], "handled": v["handled"]` to the JSON (dates become strings
through `_json`'s `default=str`).

- [ ] **Step 5: The API carries the state**

In `api_case`, before `return out`:

```python
    st = case_state(did, d, out_of_date=bool(saved) and bool(_changes(did, case)))
    out["state"] = {**st, "until": st["until"].isoformat() if st["until"] else None}
```

In `api_case_of`, add to the returned dict:

```python
            "state": (lambda s: {**s, "until": s["until"].isoformat() if s["until"] else None})(
                case_state(v["decision_id"], v["dispute"], c)),
```

- [ ] **Step 6: Run the tests and the suite**

Run: `python3 tests/test_today.py`, then the full suite.
Expected: all pass. If `test_the_demo_morning_needs_giulia_for_one_check_and_marta_for_her_four_cases` or another
morning test now counts differently, read why before changing it: a count may only change because a case moved to
another state by the rules of `state.of`, and the test's comment must then say which case and why.

- [ ] **Step 7: Commit**

```bash
git add secondlook/today.py secondlook/web.py tests/test_today.py
git commit -m "Today reads each case's state: Needs you holds only your move, the rest waits in its own bucket

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: the Today page shows the buckets

**Files:** Modify `secondlook/web.py` (`PAGE` CSS, new `bucket_block`, `today_page`, the `/today` route).
Test: `tests/test_today.py`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_today.py`)

```python
def test_after_a_refund_today_says_so_and_the_demo_s_paypal_closes_it_labelled_simulated():
    with morning():
        web.approve("DEMO-039", "REFUND", "Your refund is on its way.", by="giulia")
        page = web.today_page("demo", "giulia", done="DEMO-039")
        assert "✓ Pablo García:" in page and "Now: Done" in page                          # the toast
        assert "Done · 1" in page and "demo: simulated" in page
        assert "Waiting for the customer · 1" in page and "closes itself on 23 Oct" in page   # Margot
        assert "Today you handled 1 case, about 6 min." in page
        assert web.today_page("demo", "sara").count('class="bucket') == 0                 # nothing of hers waits
```

- [ ] **Step 2: Run it to see it fail**

Run: `python3 tests/test_today.py`
Expected: `TypeError: today_page() got an unexpected keyword argument 'done'`.

- [ ] **Step 3: Add the CSS** (inside `PAGE`'s `<style>`, before `.api{{…}}`; braces doubled)

```css
/* states (spec 2026-10-30): one pill per state, the same on Today and on the case page */
.state-pill{{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:#fff;vertical-align:1px}}
.state-pill.your_move{{background:#B07A2A}} .state-pill.waiting_customer,.state-pill.waiting_paypal{{background:#3F5677}} .state-pill.done{{background:var(--pass)}}
section.bucket{{background:#fff;border:1px solid var(--rule);border-left:4px solid #3F5677;padding:14px 20px;margin-top:16px}}
section.bucket.done{{border-left-color:var(--pass)}}
.toast{{background:#E8F0EA;border:1px solid #CFE3D4;padding:10px 16px;margin:0 0 14px}} .toast b{{color:var(--pass)}}
```

- [ ] **Step 4: Render the buckets, the toast and the handled line**

Add before `today_page`:

```python
BUCKETS = (("waiting_customer", "Waiting for the customer", ""), ("waiting_paypal", "Waiting for PayPal", ""),
           ("done", "Done", " done"))


def _until_words(st: dict) -> str:
    """The right-hand column of a waiting or done row: the date that matters, said for what it means."""
    u = st.get("until")
    if st["state"] == "done":
        return "closed"
    if st["state"] == "waiting_paypal":
        return "PayPal's move"
    if u and "closes itself" in st.get("then", ""):
        return f"closes itself on {u.day} {u:%b}"
    return f"until {u.day} {u:%b}" if u else "the customer's move"


def bucket_block(rows: list, title: str, cls: str, q: str) -> str:
    """One of Today's other buckets: a case once, in its state, with the last thing that happened and its date."""
    if not rows:
        return ""
    lis = "".join(f'<li><a href="{e(r["link"])}{q}"><span class="what"><b>{e(r["who"] or "")}</b>, <i>customer</i> · '
                  f'{e(r["summary"])}<span class="t-sub">{e(r["state"]["why"])}</span></span>'
                  f'<span class="due soft">{e(_until_words(r["state"]))}</span></a></li>' for r in rows)
    return (f'<section class="bucket{cls}"><h2>{e(title)} · {len(rows)}</h2>'
            f'<ul class="needs-list">{lis}</ul></section>')


def _toast(v: dict, done: str, q: str) -> str:
    """After a move, back on Today: which case, what went, and the state it is in now."""
    rows = [*v["needs"], *(r for k, _, _ in BUCKETS for r in v["waiting"][k])]
    r = next((x for x in rows if x.get("id") == done), None)
    sent = ((_raw(done) or {}).get("sent") or "").split(". Sent by ")[0].rstrip(".")
    if not r or not sent:
        return ""
    now = (r.get("state") or {}).get("label") or "Your move"
    return (f'<p class="toast"><b>✓ {e(r["who"] or "")}:</b> {e(sent)}. Now: {e(now)}. '
            f'<a href="{e(r["link"])}{q}">Open the case</a></p>')
```

Change `today_page`'s signature to `def today_page(src: str, me: str | None = None, done: str = "") -> str:`, add
"`done`: the case just acted on (the case page's way back says which): a toast names it and its state now." to its
docstring, make its first lines

```python
    demo = src == "demo"
    if demo:
        confirm_demo_refunds()          # the demo's PayPal "confirms" a refund at the next look (spec Part 4)
    v = today_view(src, me)
```

change `line` to add the handled count, and the body:

```python
    h = v["handled"]
    handled = (f'Today you handled {h["cases"]} case{"s" if h["cases"] != 1 else ""}, about {_hours(h["minutes"])}.'
               if h["cases"] else "")
    buckets = "".join(bucket_block(v["waiting"][k], title, cls, q) for k, title, cls in BUCKETS)
    body = (f'<div class="morning">{_toast(v, done, q) if done else ""}<h1 class="page">{e(hello)}.</h1>'
            f'<p class="who">{e(line)}</p>' + (f'<p class="t-sub">{e(handled)}</p>' if handled else "")
            + f'{needs_block(v["needs"], q, me, src, bool(t.get("solo")))}{buckets}'
            f'<section class="new">{see_block(s, q, v["phone"], v["calls_pending"])}</section>'
            f'{team_block(v["manage"], v["head"], q)}<p class="t-sub rule-line">{e(rule)}</p></div>')
```

In the GET route for `/today`: `return self._send(today_page(src, me=me, done=(qs.get("done") or [""])[0]))`.

- [ ] **Step 5: Run the tests and the suite**

Run: `python3 tests/test_today.py`, then the full suite. Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add secondlook/web.py tests/test_today.py
git commit -m "Today: each case once, in its state; a toast after a move; what you handled today

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: the case page's side box

Where you are (a crumb and the way back), the state with its date, and after a move a "✓ Done" line, "Nothing needs
you" and the next case. When the case isn't this person's move, the review and its checks fold away. The AI's pick
gets its "What happens next" joined under its button.

**Files:** Modify `secondlook/web.py` (CSS; new `_move_facts`, `crumb`, `state_box`, `needs_after`;
`case_file_page` ~3104, `case_page` ~3479, `review_column` ~3509). Test: `tests/test_web.py`.

- [ ] **Step 1: Keep the approval bench offline**

`needs_after` reads Today's list for the shop, and the bench's case "X" belongs to the live shop: in
`approval_bench`, add `"needs_after"` to the names tuple it saves, and next to `web.notify = …` add
`web.needs_after = lambda src, me, did: []`.

- [ ] **Step 2: Write the failing tests** (append to `tests/test_web.py`)

```python
def test_the_side_box_says_whose_move_and_after_a_move_what_went_and_that_nothing_needs_you():
    with approval_bench():
        page = web.case_page("X", me="giulia")
        assert 'class="state-pill your_move"' in page and 'class="crumb"' in page and "Today</a> › Needs you" in page
        assert '<p class="then"><b>What happens next:</b>' in page
        web.approve("X", "REFUND", "Here is your refund", by="giulia")
        page = web.case_page("X", me="giulia")
        assert "✓ Done: Refund accepted and reply sent" in page and "Giulia, " in page
        assert 'class="state-pill waiting_paypal"' in page and "Nothing needs you." in page
        assert '<details class="fold">' in page and "Today</a> › Waiting for PayPal" in page
        assert "done=X" in page                                     # the way back names the case for Today's toast
```

- [ ] **Step 3: Run it to see it fail**

Run: `python3 tests/test_web.py`
Expected: AssertionError on `state-pill your_move`.

- [ ] **Step 4: Add the CSS** (inside `PAGE`'s `<style>`, after the state-pill lines of Task 6; braces doubled)

```css
.crumb{{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:14px;color:var(--soft);margin:0 0 14px}} .crumb a{{color:var(--ink)}}
.state-box{{background:#fff;border:1px solid var(--rule);padding:14px 18px;margin:0 0 18px}} .state-box p{{margin:0 0 6px}}
.done-line{{background:#E8F0EA;border-left:4px solid var(--pass);padding:12px 16px;margin:0 0 12px}} .done-line b{{display:block;color:var(--pass)}}
.demo-line{{font-size:13px;color:#6E4F27;background:var(--kraft-bg);padding:6px 12px;margin:0 0 12px}}
.band{{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--soft);margin:12px 0 4px}}
a.next{{display:block;background:var(--ink);color:#fff;font-weight:700;text-decoration:none;padding:10px 14px;margin:6px 0}}
details.fold{{margin-top:18px}} details.fold>summary{{cursor:pointer;color:var(--soft)}}
p.then{{background:#E8F0EA;margin:8px 0 0;padding:8px 12px;font-size:15px}} p.then b{{color:var(--pass)}}
```

- [ ] **Step 5: Add the facts, the crumb, the state box and the next case**

Add `from . import moves as moves_mod` to the imports (alphabetical, after `ledger,`), and `quote` to the
`urllib.parse` import. Then, before `case_page`:

```python
def _move_facts(did: str, case: dict, c: dict | None) -> dict:
    """What a move's text and button say about this case (moves.py): the customer's first name, the courier and its
    tracking, the amount, the order, the shop's name."""
    d, r = case["dispute"], case["seller_records"]
    buyer = ((d.get("disputed_transactions") or [{}])[0].get("buyer") or {}).get("name")
    name = ((c or {}).get("customer") or {}).get("name") or buyer or ""
    tr = r.get("tracking") or {}
    carrier = tr.get("carrier_name_other") or (tr.get("carrier") if tr.get("carrier") != "OTHER" else None)
    when = _t(tr.get("last_update")) if tr.get("status") == "DELIVERED" else None
    amt = d["dispute_amount"]
    shop = (DemoPayPal().shop if is_demo(did) else _live_shop()).get("name")
    return {"first": name.split(" ")[0], "carrier": carrier,
            "tracking": f' (tracking {tr["tracking_number"]})' if tr.get("tracking_number") else "",
            "amount": f'{float(amt["value"]):.2f} {amt.get("currency_code", "EUR")}',
            "order": (c or {}).get("order_no"), "delivered": f" on {when.day} {when:%b}" if when else "", "shop": shop}


BUCKET = {"your_move": "Needs you", "waiting_customer": "Waiting for the customer",
          "waiting_paypal": "Waiting for PayPal", "done": "Done"}


def needs_after(src: str, me: str | None, did: str) -> list:
    """What else needs this person (the same list as Today's), for the case page's way back and its "Next" button."""
    if src not in ("demo", "live"):
        return []
    return [n for n in today_view(src, me)["needs"] if n["kind"] == "case" and n["id"] != did]


def _today_link(src: str, did: str) -> str:
    return "/today?" + urlencode({**({"shop": "demo"} if src == "demo" else {}), "done": did})


def crumb(st: dict, name: str, src: str, did: str, more: int) -> str:
    """Where you are (spec Part 3, slot 1): Today › the bucket this case is in › its customer; and the way back, which
    says how many more need you and names this case, so Today can say what just happened to it."""
    q = "?shop=demo" if src == "demo" else ""
    left = f'{more} more need{"s" if more == 1 else ""} you' if more else "nothing else needs you"
    return (f'<nav class="crumb"><span><a href="/today{q}">Today</a> › {e(BUCKET[st["state"]])} › <b>{e(name)}</b></span>'
            f'<a href="{e(_today_link(src, did))}">← Back to Today · {e(left)}</a></nav>')


def state_box(st: dict, did: str, src: str, nxt: list) -> str:
    """The top of the side box (spec Part 3, slot 6): the state, until when, and what happens then. After a move, a
    "✓ Done" line says what went, who and when (in the demo: that nothing really went). When it isn't this person's
    move: "Nothing needs you", and the next case that does."""
    q = "?shop=demo" if src == "demo" else ""
    raw, sb = _raw(did) or {}, _saved_by(did)
    done = ""
    if raw.get("sent"):
        what = str(raw["sent"]).split(". Sent by ")[0].split(" (Demo shop")[0].rstrip(".")
        who = ", ".join(x for x in (sb.get("by"), _when(str(sb.get("at") or "")[:16])) if x)
        done = (f'<div class="done-line"><b>✓ Done: {e(what)}</b><span class="t-sub">{e(who)}</span></div>'
                + ('<p class="demo-line">Demo shop: logged here. Nothing was really sent.</p>' if is_demo(did) else ""))
    pill = f'<span class="state-pill {e(st["state"])}">{e(st["label"])}</span>'
    u = st["until"]
    if st["state"] == "your_move":
        when = (f' Answer by <b>{u:%a} {u.day} {u:%b}</b>' if u else "" if st["paypal"] else " No PayPal deadline")
        return (done + f'<div class="state-box move"><p>{pill}{when}</p>'
                f'<p class="t-sub">{e(st["why"])} {e(st["then"])}</p></div>')
    nothing = "" if st["state"] == "done" else "<b>Nothing needs you.</b> "
    nxt_html = ""
    if nxt:
        n = nxt[0]
        nxt_html = (f'<p class="band">Next in Needs you · {len(nxt)}</p>'
                    f'<a class="next" href="{e(n["link"])}{q}">{e(n["who"] or "")} · {e(n["summary"])} →</a>')
    nxt_html += f'<a href="{e(_today_link(src, did))}">or back to Today</a>'
    return (done + f'<div class="state-box"><p>{pill} {e(st["why"])}</p><p>{nothing}{e(st["then"])}</p>'
            f'{nxt_html}</div>')


def side_box(did: str, case: dict, c: dict | None, me: str | None, flash: str = "", plain_owner: bool = True) -> tuple:
    """(crumb, side box) for a case page: the state first, then the review. Off this person's move, the review and its
    checks fold away: what happened is above, what's left to do is said."""
    src = src_of_case(did, "live") if not cases_mod.is_case_id(did) else shop_of_case(did)
    saved = _saved(did)
    st = case_state(did, case["dispute"] if not cases_mod.is_case_id(did) else None, c,
                    out_of_date=bool(saved) and not saved[1] and bool(_changes(did, case)))
    nxt = needs_after(src, me, did)
    name = ((c or {}).get("customer") or {}).get("name") or \
        ((case["dispute"].get("disputed_transactions") or [{}])[0].get("buyer") or {}).get("name") or did
    col = review_column(did, case, me, flash, plain_owner)
    if st["state"] != "your_move":
        col = f'<details class="fold"><summary>Second Look\'s review and the ten checks</summary>{col}</details>'
    return crumb(st, name, src, did, len(nxt)), state_box(st, did, src, nxt) + col
```

- [ ] **Step 6: Use it on both case pages, and join "What happens next" to the AI's pick**

In `case_page`, replace the `body = …` assignment with:

```python
    top, side = side_box(dispute_id, case, find_case_of_dispute(dispute_id) if not practice else None, me, flash)
    body = (f'{top}<div class="case"><section>{left}</section>'
            f'<section class="look">{side}</section></div>')
```

In `case_file_page`, in the `if d:` branch, replace `review_column(d["dispute_id"], _case(d["dispute_id"]), me, plain_owner=False)`
with a call through `side_box`, keeping the crumb for the top:

```python
        top, side = side_box(d["dispute_id"], _case(d["dispute_id"]), c, me, plain_owner=False)
        right = (f'<div class="judged"><b>This case is a PayPal dispute now: {e(d["dispute_id"])}.</b> PayPal\'s rules '
                 f'apply, and the answer goes to PayPal. <a href="/d/{e(d["dispute_id"])}">The dispute\'s own page</a>.</div>'
                 + side)
```

and in the `else:` (sorted inquiry) branch:

```python
        case = _case(cid)
        left += f'<h2>What the evidence says</h2>{evidence(case["seller_records"], inquiry=True)}' if o else ""
        top, side = side_box(cid, case, c, me, plain_owner=False)
        right = (ai_check_form(v["src"], cid, me, f"/c/{cid}") + side
                 + (_close_form(cid, me) if c["status"] == "open" else ""))
```

Set `top = ""` before the `if d:` (so the unsorted branch has none), and make the body
`body = (f'{top}<div class="case">…` (the rest as it is).

In `review_column`, in the `elif via == "form":` branch, join the consequence under the button:

```python
    elif via == "form":
        action_part = _send_form(did, o["label"], o["draft"], o["action"], o["button"], o["says"], me,
                                 o["outcome"] == "pass", TEACH if o["_teach"] and o["outcome"] != "pass" else "")
        if o["outcome"] == "send" and o["action"] in moves_mod.THEN:
            c_ = case_store(shop_of_case(did)).get(did) if cases_mod.is_case_id(did) else find_case_of_dispute(did)
            nxt = moves_mod.then(o["action"], _move_facts(did, case, c_), cases_mod.is_case_id(did))
            action_part += f'<p class="then"><b>What happens next:</b> {e(nxt)}</p>'
```

- [ ] **Step 7: Run the tests and the suite**

Run: `python3 tests/test_web.py`, then the full suite. Expected: all pass. A test that splits a page on a string that
moved (for example `'<ol class="talk">'`) still finds it: nothing here renames the conversation.

- [ ] **Step 8: Commit**

```bash
git add secondlook/web.py tests/test_web.py
git commit -m "Case page: where you are, the state and its date, a Done line after a move, the next case

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: voices, the sent reply, "Tracked and verified", the money moved

**Files:** Modify `secondlook/web.py` (CSS; `timeline_block` ~3015; `case_view` ~799; `conversation` ~3197;
`case_page`'s `signed`; `_send_form` ~3224; new `_with_sent_reply`, `tracked_rows`, `tracked_block`).
Tests: `tests/test_web.py`, `tests/test_intake.py:152`, `tests/test_inquiry.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_inquiry.py` (it has the demo `morning()` bench):

```python
def test_a_dispute_s_case_shows_the_reply_sent_tracked_facts_and_the_money_it_moved():
    with morning():
        assert web.approve("DEMO-039", "REFUND", "Your refund of 29.00 EUR is on its way.", by="giulia")[0] == 200
        d = web.DemoPayPal().get_dispute("DEMO-039")
        tl = web._with_sent_reply(web.cases_mod.timeline({"timeline": [], "customer": {"name": "Pablo García"}}, d),
                                  "DEMO-039")
        sent = [x for x in tl if x["direction"] == "out"]
        assert sent[-1]["text"] == "Your refund of 29.00 EUR is on its way." and sent[-1]["sent_with"] == "with the refund"
        rows = web.tracked_rows(d, web._case("DEMO-039")["seller_records"], [], web._raw("DEMO-039"), None)
        facts = [r[3] for r in rows]
        assert any(f.startswith("Shipped with Local courier, LC01969IT") for f in facts)
        assert any(f.startswith("Last scan: in transit") for f in facts)
        assert any(f.startswith("Refund of 29.00 EUR sent to PayPal") for f in facts)
        assert [r[0] for r in rows if r[3].startswith("Refund")] == ["◷"]


def test_the_customer_s_words_and_the_shop_s_wear_different_voices():
    with morning():
        page = web.case_file_page("DEMO-C001", me="marta")
        assert "What happened and what was said" in page and '<li class="buyer">' in page
        assert 'class="tracked"' in page and "✓ = checked against" in page
```

Append to `tests/test_web.py`:

```python
def test_the_money_a_refund_moved_on_a_dispute_counts_in_its_case_s_cost():
    assert web._dispute_money({"sent": "Refund accepted.", "chosen": "REFUND", "amount": 29.0}) == 29.0
    assert web._dispute_money({"sent": "Reply sent.", "chosen": "MESSAGE"}) == 0.0
```

Change `tests/test_intake.py:152`'s `"Everything said, every channel"` to `"What happened and what was said"`.

- [ ] **Step 2: Run them to see them fail**

Run: `python3 tests/test_inquiry.py; python3 tests/test_web.py`
Expected: `AttributeError: module 'secondlook.web' has no attribute '_with_sent_reply'` (and `_dispute_money`).

- [ ] **Step 3: Add the CSS** (inside `PAGE`'s `<style>`, after Task 7's lines; braces doubled)

```css
/* voices: the customer in their own serif, the shop plain, Second Look's AI in amber, PayPal's events small and blue */
.talk li.you q,.talk li.ai q{{font-family:"Schibsted Grotesk",system-ui,sans-serif;font-style:normal;font-size:16px}}
.talk li.ai{{border-color:var(--kraft);background:#FBF3E4}} .talk li.proof{{font-size:14px;color:#3F5677}}
.tag{{display:inline-block;margin-left:8px;padding:0 7px;font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase}}
.tag.sent{{background:#E8F0EA;color:var(--pass)}} .tag.draft{{background:#FFF3D6;color:#7A5410;margin:0 0 6px}}
.draft-card{{border:1.5px dashed var(--ink);padding:10px;background:#fff}} .draft-card textarea{{border:0;min-height:160px}}
/* tracked and verified: what a record holds, one row each */
.tracked{{list-style:none;padding:0;margin:0 0 8px;background:#fff;border:1px solid var(--rule);max-width:640px}}
.tracked li{{display:grid;grid-template-columns:20px 110px 60px 1fr;gap:8px;padding:6px 14px;border-top:1px solid var(--rule);font-size:15px}}
.tracked li:first-child{{border-top:0}} .tracked .mk{{color:var(--pass);font-weight:700}} .tracked .mk.wait{{color:#3F5677}}
.tracked .from{{font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:#3F5677;padding-top:3px}}
.tracked .on{{color:var(--soft)}} .tracked-foot{{font-size:13px;color:var(--soft);margin:0 0 28px}}
@media (max-width:700px){{.tracked li{{grid-template-columns:20px 1fr}} .tracked .from,.tracked .on{{grid-column:2}}}}
```

- [ ] **Step 4: The sent reply joins the timeline; the money it moved counts**

Add after `case_view`:

```python
SENT_WITH = {"REFUND": "with the refund", "PARTIAL_REFUND": "with the partial refund", "DEFEND": "with your evidence",
             "REPLACE": "with the replacement"}


def _with_sent_reply(tl: list, did: str) -> list:
    """The answer sent from Second Look on a PayPal dispute, on its case's timeline: PayPal's own record may not hold
    it yet (and the demo's never does), and a person must see what was said (Claudia, 28/10: the reply was missing)."""
    raw = _raw(did) or {}
    text = (raw.get("judgment") or {}).get("draft_message")
    if not raw.get("sent") or not text or any(x["direction"] == "out" and x.get("text") == text for x in tl):
        return tl
    at = _utc_minute(raw["at"]) if raw.get("at") else (tl[-1]["at"] if tl else None)
    sent = cases_mod.entry(at, "paypal", "out", text, raw.get("by") or "You",
                           sent_with=SENT_WITH.get(raw.get("chosen"), ""))
    return sorted(tl + [sent], key=lambda x: x["at"])


def _dispute_money(raw: dict | None) -> float:
    """What a refund sent on a PayPal dispute moved: it is PayPal's to record, not the case's, so the case's cost
    counted 0 (Claudia, 28/10). From the review, which keeps the amount since 30/10."""
    raw = raw or {}
    return float(raw.get("amount") or 0) if raw.get("sent") and raw.get("chosen") in REFUNDS else 0.0
```

In `case_view`, after `c = store.get(cid)` and `d = …`, build the timeline and costs once:

```python
    tl = cases_mod.timeline(c, d)
    costs = cases_mod.costs_so_far(c, d, _policy())
    if d:
        tl = _with_sent_reply(tl, d["dispute_id"])
        costs["money_moved"] = round(costs["money_moved"] + _dispute_money(_raw(d["dispute_id"])), 2)
```

and in its returned dict use `"timeline": tl` and `"costs": costs`.

- [ ] **Step 5: One look per voice in the conversation**

In `timeline_block`, change the heading to `What happened and what was said`, and replace the line
`cls = {"in": "buyer", "out": "you", "note": "proof"}[x["direction"]]` with:

```python
        # one look per voice (spec Part 3): the customer, the shop, Second Look's AI, PayPal's and the shop's events
        cls = ("buyer" if x["direction"] == "in" else "proof" if x["direction"] == "note"
               else "ai" if x.get("ai") or x.get("autopilot") else "you")
        if x.get("sent_with"):
            head = head.replace("</b>", f'<span class="tag sent">sent · {e(x["sent_with"])}</span></b>', 1)
```

In `_send_form`, wrap the reply box as the draft it is:

```python
            f'<label class="reply" for="reply">{label}</label>'
            f'<div class="draft-card"><span class="tag draft">draft · not sent</span>'
            f'<textarea id="reply" name="message">{e(draft)}</textarea></div>'
```

On the `/d/` page, sign the sent reply for a seller on their own too: in `case_page`, replace the `signed` block with

```python
    signed = None
    if saved and saved[1]:
        sb = _saved_by(dispute_id)
        signed = {"by": sb.get("by") if a is not None else None, "at": sb.get("at"),
                  "text": saved[0].judgment.draft_message or saved[1]}
```

and in `conversation`, replace `if signed and signed.get("by"):` / `who = f"Sent by {signed['by']}"` with

```python
    if signed and signed.get("text"):
        who = f"Sent by {signed['by']}" if signed.get("by") else "You"
```

- [ ] **Step 6: Tracked and verified**

Add before `case_file_page`:

```python
TRACK_SAYS = {"DELIVERED": "delivered", "IN_TRANSIT": "in transit", "SHIPPED": "shipped",
              "ON_HOLD": "on hold", "RETURNED": "returned to sender"}


def tracked_rows(d: dict | None, records: dict, money: list, raw: dict | None, order: dict | None) -> list:
    """Tracked and verified (spec Part 3, slot 3): only what a record holds, one (mark, source, ISO date, fact) row
    each, oldest first: the payment (PayPal, or the shop's own orders), the parcel (the courier), the dispute
    (PayPal), the money logged on the case or sent to PayPal. ✓ is checked against that record; ◷ was sent and isn't
    confirmed yet. What the customer says is never here: it is in the conversation, in their words."""
    rows = []
    if order and order.get("date"):
        amt = _num(order.get("amount"))
        items = ", ".join(i["name"] for i in order.get("items", []) if i.get("name"))
        paid = f"Paid: {amt:.2f} {order.get('currency') or 'EUR'}" if amt is not None else "Ordered"
        rows.append(("✓", "PayPal" if order.get("paid_with") == "paypal" else "Your orders", str(order["date"])[:10],
                     paid + (f", {items}" if items else "")))
    elif d and records.get("order_date"):
        items = ", ".join(i["name"] for i in records.get("items", []) if i.get("name"))
        a = d["dispute_amount"]
        rows.append(("✓", "PayPal", str(records["order_date"])[:10],
                     f'Paid: {float(a["value"]):.2f} {a.get("currency_code", "EUR")}' + (f", {items}" if items else "")))
    tr = (order or {}).get("tracking") or records.get("tracking") or {}
    carrier = tr.get("carrier_name_other") or (tr.get("carrier") if tr.get("carrier") != "OTHER" else None) or "the courier"
    if tr.get("shipped_date"):
        rows.append(("✓", "Courier", tr["shipped_date"][:10],
                     f"Shipped with {carrier}" + (f', {tr["tracking_number"]}' if tr.get("tracking_number") else "")))
    if tr.get("last_update"):
        status = TRACK_SAYS.get(tr.get("status"), str(tr.get("status") or "").lower().replace("_", " "))
        rows.append(("✓", "Courier", tr["last_update"][:10],
                     f"Last scan: {status}" + (f', {tr["delivered_to"]}' if tr.get("delivered_to") else "")))
    if d:
        rows.append(("✓", "PayPal", str(d.get("create_time") or "")[:10],
                     f'Dispute opened: {ledger.REASON_SHORT.get(d.get("reason"), d.get("reason")).lower()}'))
        if _dispute_money(raw):
            confirmed = demo_confirmed().get(d["dispute_id"])
            rows.append(("✓" if confirmed else "◷", "PayPal", str((raw or {}).get("at") or "")[:10],
                         f'Refund of {_dispute_money(raw):.2f} {d["dispute_amount"].get("currency_code", "EUR")} sent to '
                         "PayPal: " + ("confirmed (demo: simulated)" if confirmed else "waiting for PayPal to confirm")))
    for m in money:
        kind = books_mod.KIND.get(m.get("kind"))
        if kind:
            rows.append(("✓" if m.get("status") == "paid" else "◷", "Your shop", str(m.get("at") or "")[:10],
                         f'{kind.capitalize()} {float(m.get("amount") or 0):.2f} {m.get("currency") or "EUR"}: '
                         f'{m.get("status") or "logged"}'))
    return sorted(rows, key=lambda r: r[2])


def tracked_block(rows: list) -> str:
    if not rows:
        return ""
    lis = []
    for mark, src, day, fact in rows:
        t = _t(day)
        lis.append(f'<li><span class="mk{" wait" if mark == "◷" else ""}">{e(mark)}</span><span class="from">{e(src)}</span>'
                   f'<span class="on">{e(f"{t.day} {t:%b}" if t else "")}</span><span>{e(fact)}</span></li>')
    return (f'<h2>Tracked and verified</h2><ul class="tracked">{"".join(lis)}</ul>'
            '<p class="tracked-foot">✓ = checked against PayPal\'s records, the courier\'s tracking or your orders. '
            '◷ = sent, not confirmed yet.</p>')
```

(`_t` is the existing time parser at ~1594: it reads a bare `YYYY-MM-DD` too.)

In `case_file_page`, put the block right before the timeline: replace `f'{timeline_block(v)}')` at the end of `left`
with

```python
            + tracked_block(tracked_rows(d, (_case(d["dispute_id"])["seller_records"] if d else {}), c.get("money", []),
                                         _raw(d["dispute_id"]) if d else None, o))
            + f'{timeline_block(v)}')
```

In `case_page`, put it before the conversation: in `left`, replace `f'{conversation(d, signed)}{timeline(case)}'` with
`f'{tracked_block(tracked_rows(d, r, [], _raw(dispute_id), None))}{conversation(d, signed)}{timeline(case)}'`.

- [ ] **Step 7: Run the tests and the suite**

Run: `python3 tests/test_inquiry.py; python3 tests/test_web.py; python3 tests/test_intake.py`, then the full suite.
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add secondlook/web.py tests/test_web.py tests/test_inquiry.py tests/test_intake.py
git commit -m "Case page: one look per voice, the sent reply in the conversation, tracked and verified facts, the money moved

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: the other moves (slips first if time runs short)

**Files:** Modify `secondlook/web.py` (CSS; `outcome` ~3699; `approve`/`_approve` ~3729/3795; new
`_offered_moves`, `_move_form`, `other_moves`, `MOVE_WARN`; `review_column`; the approve routes). Test:
`tests/test_web.py`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_web.py`)

```python
def test_beside_the_ai_s_pick_two_moves_that_fit_with_their_own_texts():
    with approval_bench():                                     # the AI says refund, on a "never arrived" dispute
        page = web.case_page("X", me="giulia")
        assert "Reply only" in page and "Send your evidence" in page and "Answer and send a replacement" not in page
        moves = page.split('<section class="moves">')[1]
        assert "refund" not in moves.split("<textarea")[1].split("</textarea>")[0].lower()
        assert "Your text mentions a refund" in page              # the warning, shown only when a text says so


def test_a_catalog_move_sends_its_own_text_never_the_ai_s_draft_for_another_answer():
    with approval_bench() as b:
        assert web.approve("X", "MESSAGE", "Hello", by="giulia", move=True)[0] == 409       # "Hello" is the AI's draft
        assert web.approve("X", "REPLACE", "We'll send another.", by="giulia", move=True)[0] == 409  # not offered here
        assert web.approve("X", "MESSAGE", "We're checking with the courier.", by="giulia")[0] == 409  # no catalog: as before
        assert b.sent == []
        assert web.approve("X", "MESSAGE", "We're checking with the courier.", by="giulia", move=True)[0] == 200
        assert b.sent == ["MESSAGE"] and b.drafts == ["We're checking with the courier."]
        assert web._raw("X")["chosen"] == "MESSAGE" and web.case_state("X")["state"] == "waiting_customer"


def test_a_money_move_never_passes_a_trust_stop():
    with approval_bench(action="ASK_SELLER", ai="MESSAGE", stops=["injection"]) as b:
        assert web.approve("X", "REFUND", "Your refund is on its way.", by="giulia", move=True)[0] == 409
        assert b.sent == []


def test_over_the_limit_a_move_passes_to_the_head_with_its_text():
    with approval_bench(action="MESSAGE", ai="MESSAGE") as b:
        assert web.approve("X", "REFUND", "Your refund is on its way.", by="marta", move=True)[0] == 202
        assert b.sent == [] and b.store.get("X")["handoff"]["action"] == "REFUND"
```

- [ ] **Step 2: Run them to see them fail**

Run: `python3 tests/test_web.py`
Expected: `TypeError: approve() got an unexpected keyword argument 'move'` (and the page test fails on "Reply only").

- [ ] **Step 3: `outcome` takes the catalog path**

Change `outcome`'s signature to `def outcome(dec, chosen, dispute, t, who, template: bool = False) -> tuple:` and its
first check to `if not may_approve(dec.action, chosen, dec.judgment.action, dec.stops, template=template):`.

- [ ] **Step 4: What a case offers, the move forms and the warning**

Add after `held_action`:

```python
def _offered_moves(did: str, case: dict, dec: Decision) -> list:
    """The catalog's moves beside Second Look's AI's pick on this case (moves.others): the one list the page shows and
    approve() accepts, so a move it refuses is never on screen and one not on screen is never sent."""
    inquiry = cases_mod.is_case_id(did)
    c = case_store(shop_of_case(did)).get(did) if inquiry else find_case_of_dispute(did)
    kind = moves_mod.kind_of(c, None if inquiry else case["dispute"])
    pick = dec.judgment.action if dec.action == "ASK_SELLER" else dec.action
    return moves_mod.others(kind, pick, None if inquiry else paypal_can(case["dispute"]), inquiry)


# A reply that sends no money but whose words promise some: said under the box as it is typed (spec Part 2).
MOVE_WARN = ('<script>document.querySelectorAll("form.move[data-money=\'0\'] textarea").forEach(t=>{'
             'const w=t.form.querySelector(".warn");t.addEventListener("input",()=>{'
             'w.hidden=!/refund|money back|rimbors/i.test(t.value);});});</script>')


def _move_form(did: str, action: str, draft: str, button: str, then: str, me: str | None) -> str:
    """One move: its fixed text in a draft box (editable), its button named for everything it sends, and what happens
    next joined under it. Posts to the same approve as the AI's pick, marked as a catalog move."""
    by = f'<input type="hidden" name="by" value="{e(me)}">' if me else ""
    mark = review_mark(did)
    by += f'<input type="hidden" name="review" value="{e(mark)}">' if mark else ""
    money = action in MONEY
    warn = "" if money else '<p class="warn" hidden>Your text mentions a refund, but this answer sends none.</p>'
    return (f'<details class="move"><summary>{e(button)}</summary>'
            f'<form class="send move" method="post" action="/d/{e(did)}/approve" data-money="{1 if money else 0}">'
            f'<div class="draft-card"><span class="tag draft">draft · not sent</span>'
            f'<textarea name="message" aria-label="{e(button)}">{e(draft)}</textarea></div>{warn}'
            f'<input type="hidden" name="action" value="{e(action)}"><input type="hidden" name="move" value="1">{by}'
            f'<div class="approve"><button>{e(button)}</button></div><p class="then">{e(then)}</p></form></details>')


def other_moves(did: str, case: dict, me: str | None) -> str:
    """The moves beside Second Look's AI's pick (moves.py), each with its own fixed text, never the AI's draft; over
    this person's limit a move passes to the colleague who may send it, and says so. Only on a case reviewed and not
    answered yet. "Decide later" closes the list: until when it can wait, and what happens then."""
    saved = _saved(did)
    if not saved or saved[1]:
        return ""
    dec, d = saved[0], case["dispute"]
    inquiry = cases_mod.is_case_id(did)
    c = case_store(shop_of_case(did)).get(did) if inquiry else find_case_of_dispute(did)
    kind = moves_mod.kind_of(c, None if inquiry else d)
    facts = _move_facts(did, case, c)
    t = team_for(did)
    who = None if t.get("solo") else team_mod.person(t, me)
    forms = []
    for a in _offered_moves(did, case, dec):
        kind_, to = outcome(dec, a, d, t, who, template=True)
        if kind_ == "refused":
            continue
        name = moves_mod.label(a, inquiry, facts)
        if kind_ == "pass":
            button, then = f"Pass to {to['name']}, with “{name.lower()}” suggested", _pass_says(a, dec, d, to["name"], t, me)
        else:
            button, then = name, moves_mod.then(a, facts, inquiry)
        forms.append(_move_form(did, a, moves_mod.text(a, kind, facts), button, then, me))
    st = case_state(did, None if inquiry else d, c)
    u = st["until"]
    later = (f'<p class="later"><b>Decide later</b>' + (f": until {u:%a} {u.day} {u:%b}." if u else ".")
             + f' {e(st["then"])}</p>')
    if not forms:
        return later
    lock = LOCK.replace("Sending to PayPal…", _words(did)["sending"])
    return f'<section class="moves"><h3>Or another answer</h3>{"".join(forms)}</section>{later}{MOVE_WARN}{lock}'
```

Add the CSS (inside `PAGE`'s `<style>`, after Task 8's lines; braces doubled):

```css
/* the other moves: each a draft and a button, with what happens next joined under it */
.moves{{margin-top:18px}} .moves h3{{font-size:15px;margin:0 0 6px;color:var(--soft)}}
details.move{{border:1px solid var(--ink);margin:8px 0;background:#fff}} details.move>summary{{cursor:pointer;font-weight:700;padding:10px 14px}}
details.move form{{padding:0 14px 12px}} p.warn{{color:#A8551F;font-weight:700;margin:6px 0 0}}
p.later{{background:#FBEEE6;border-left:4px solid #A8551F;padding:10px 14px;margin:14px 0 0;font-size:15px}} p.later b{{color:#A8551F}}
```

In `review_column`, add the moves after the AI's pick: change its last line to

```python
    moves = other_moves(did, case, me) if via in ("form", "promise", "draft_refused", "no_draft") else ""
    return (f'{owner}{banner}{flash}{verdict}{action_part}{moves}{costs}'
            f'<h2 style="margin-top:34px">The ten checks</h2>{ten}')
```

- [ ] **Step 5: `approve` accepts a catalog move**

Add `move: bool = False` to `approve`'s keyword-only parameters (after `report`), document it ("`move`: the person
chose a move from the catalog (moves.py) with its own text: it must be one this case offers now, and its text never
the AI's draft for another answer"), pass it on: `return _approve(did, chosen, message, rule, t, who, execute, review, ai, move)`.

Change `_approve`'s signature to `def _approve(did, chosen, message, rule, t, who, execute, review=None, ai=None, move=False)`,
and right after `case = _case(did)` and the `_changes` check, before `kind, to = outcome(...)`:

```python
    if move:
        # a catalog move: one this case offers now, with its own words, never the AI's draft for another answer
        # (a draft written for a refund promises it: DEMO-034, 21/10)
        if chosen not in _offered_moves(did, case, dec):
            return 409, "That answer isn't one Second Look offers on this case now. Look again."
        if not (message or "").strip():
            return 400, "Write a message first."
        if chosen != dec.judgment.action and autopilot_mod.same_words(message, dec.judgment.draft_message):
            return 409, "That reply was written for another answer: send it with that one, or write this one's."
    kind, to = outcome(dec, chosen, case["dispute"], t, who, template=move)
```

(delete the old `kind, to = outcome(dec, chosen, case["dispute"], t, who)` line). For a catalog move of evidence, the
note PayPal gets is the shop's own words, never the AI's reasoning for another answer: replace
`result = execute(client, dec, case["dispute"], case["seller_records"])` with

```python
        run = dec
        if move and chosen == "DEFEND":
            run = dataclasses.replace(dec, judgment=dataclasses.replace(dec.judgment, reasoning=message))
        result = execute(client, run, case["dispute"], case["seller_records"])
```

and add `import dataclasses` to the imports (beside `from dataclasses import asdict`).

In the POST routes: the page's approve passes `move=form.get("move", [""])[0] == "1"`; `_case_api` and the disputes
API's approve pass `move=bool(data.get("move"))`.

- [ ] **Step 6: Run the tests, the snapshot and the suite**

```bash
python3 tests/test_web.py
python3 $SP/guard_snapshot.py "$PWD" > $SP/cs-snap-9.json && cmp $SP/cs-snap-base.json $SP/cs-snap-9.json && echo SAME
for f in tests/test_*.py; do python3 "$f" >/dev/null || echo "FAIL $f"; done
```
Expected: pass; `SAME`; nothing printed.

- [ ] **Step 7: Commit**

```bash
git add secondlook/web.py tests/test_web.py
git commit -m "Other moves: two that fit the cause, each with its own text and what happens next; decide later says until when

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: see it, and write down what was built

**Files:** `docs/specs/2026-10-30-case-states-and-moves-design.md` (an "As built" section), `README.md` (one section),
`../HANDOVER.md`, `../LOG.md`.

- [ ] **Step 1: Walk it in a browser** on a preview server of the worktree, on a free port (never 8765–8767):
`python3 -c "from secondlook import web; web.serve(8785)"` in the background, then with Playwright, at 1280 and 390 px:
1. `/today?shop=demo&as=giulia`: Needs you, Waiting for the customer (Margot), the new-since-yesterday list.
2. `/d/DEMO-039`: crumb, Your move with "Answer by Sun 8 Nov", the AI's pick with "What happens next", "Or another
   answer" with two moves, "Decide later". Approve the refund as Giulia.
3. The same page: "✓ Done", Waiting for PayPal, "Nothing needs you", the next case, the reply in the conversation
   tagged "sent · with the refund", the ◷ refund row in Tracked and verified.
4. Back to Today: the toast, Pablo García under Done "(demo: simulated)", "Today you handled 1 case".
5. `/c/DEMO-C001` as Marta: the call and the email in the customer's voice, Tracked and verified with "left with a
   neighbour".
Then stop the preview server. Screenshots go in `film/` only if Claudia asks; otherwise in the scratchpad.

- [ ] **Step 2: Write "As built"** at the end of the spec: what differs from the design and why (for example the
draft stays with its button in the side box, styled as the dashed draft card, rather than at the end of the
conversation: one form, one place to edit), and anything the walk found.

- [ ] **Step 3: README**: one short section under the product description: the four states and that one function
decides them; the moves beside the AI's pick; "demo: simulated" PayPal confirmation in the demo shop only.

- [ ] **Step 4: HANDOVER and LOG** per `~/.claude/handover-protocol.md`: the "UX rebuild" entry in HANDOVER's Now
becomes what was built (branch, commits, test count, snapshot SAME); LOG gets one dated entry (built, measured).

- [ ] **Step 5: Final suite, snapshot, and commit**

```bash
for f in tests/test_*.py; do python3 "$f" >/dev/null || echo "FAIL $f"; done
python3 $SP/guard_snapshot.py "$PWD" > $SP/cs-snap-end.json && cmp $SP/cs-snap-base.json $SP/cs-snap-end.json && echo SAME
git add docs/specs/2026-10-30-case-states-and-moves-design.md README.md
git commit -m "Spec as built, README: the four states and the moves

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
(`HANDOVER.md` and `LOG.md` are in the hackathon folder, outside this repo: not committed here.)

Then superpowers:finishing-a-development-branch. Merging into `main` and pushing are Claudia's calls.
