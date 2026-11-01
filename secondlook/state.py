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
       handoff_from: str | None = None, closes_on: date | None = None, confirmed_at: str | None = None,
       answered_stage: str | None = None, answered_due: str | None = None, return_asked: bool = False,
       return_back: bool = False, return_by: date | None = None) -> dict:
    """The one state of a case, first match wins: Done, Waiting for PayPal, Waiting for the customer, Your move.
    `case`: the shop's case, or None for a PayPal dispute no other channel joined; `dispute`: its PayPal dispute, if
    any. `answered_at`: when the shop's answer from Second Look went (UTC minute), None if none did; `money_sent`: that
    answer sent a refund; `out_of_date`: the review changed under it (the case page knows; Today doesn't ask);
    `holder`: the person who has the case (their id); `handoff_from`: the colleague who passed it to them;
    `closes_on`: when an answered shop request closes itself (cases.closes_on); `confirmed_at`: the demo shop's
    simulated PayPal confirmation of a refund (web.demo_confirmed: never on the sandbox or a live shop).
    `answered_stage` / `answered_due`: the dispute's stage and seller_response_due_date when the answer went. An answer
    counts only where it was given: a buyer escalating (no buyer message is posted) or PayPal asking the seller again
    changes one of them and brings the case back to Your move. None = not recorded, no check.
    `return_asked`: the answer on a shop request asked for the item back (refund on return); `return_back`: it is back
    at the shop; `return_by`: when it should be back by (the answer's day plus the shop's return window), if known.
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
    if dispute and status == "WAITING_FOR_BUYER_RESPONSE":
        # PayPal's live status beats our own record. An inquiry's one date is its 20 days, as ledger.days_left counts.
        opened = _day(dispute.get("create_time"))
        until = opened + timedelta(days=ledger.INQUIRY_DAYS) if stage == "INQUIRY" and opened \
            else _day(dispute.get("buyer_response_due_date"))
        return out(WAITING_CUSTOMER, "customer", f"Answered. Waiting for {name}.", until,
                   ledger.if_nobody_answers(dispute, today))
    # an answer counts until something new comes in: the buyer posting after it, or the review going out of date
    answered = bool(answered_at) and not out_of_date and not (dispute and _buyer_wrote_since(dispute, answered_at))
    answered = answered and (answered_stage is None or answered_stage == stage) and \
        (answered_due is None or not dispute or
         str(dispute.get("seller_response_due_date") or "")[:10] == str(answered_due)[:10])
    if dispute and answered and money_sent:
        return out(WAITING_PAYPAL, "paypal", f"PayPal pays {name} back and closes the dispute.",
                   then="It comes back to you only if PayPal refuses or the refund fails.")
    if dispute and answered and stage != "INQUIRY":
        return out(WAITING_PAYPAL, "paypal", "PayPal is deciding the claim with your answer.",
                   then="PayPal usually decides in about 10 days.")
    if dispute and answered:
        # The demo's PayPal never moves a status; a live one says WAITING_FOR_BUYER_RESPONSE (above). Either way an
        # inquiry the buyer doesn't escalate in 20 days is closed by PayPal.
        opened = _day(dispute.get("create_time"))
        until = opened + timedelta(days=ledger.INQUIRY_DAYS) if opened else None
        when = f" by {until.day} {until:%b}" if until else f" within {ledger.INQUIRY_DAYS} days"
        return out(WAITING_CUSTOMER, "customer", f"Answered. Waiting for {name}.", until,
                   f"If {name} doesn't escalate{when}, PayPal closes the dispute.")
    words = [x for x in (case or {}).get("timeline", []) if x.get("direction") in ("in", "out")]
    quiet = not words or words[-1]["direction"] == "out"          # the customer hasn't written since the answer
    if case is not None and not dispute and return_asked and answered_at and not out_of_date and quiet:
        # refund on return: the case waits for the item, then the refund is a person's move (never automatic)
        by = f"{return_by.day} {return_by:%b}" if return_by else ""
        if return_back:
            return out(YOUR_MOVE, holder, f"The return is back: refund {name} now.", None,
                       "No PayPal deadline: this came to the shop, not to PayPal.")
        if return_by and return_by < today:
            return out(YOUR_MOVE, holder, f"The return isn't back by {by}: check with {name}.", None,
                       "No PayPal deadline: this came to the shop, not to PayPal.")
        return out(WAITING_CUSTOMER, "customer", f"Asked {name} to send it back. Waiting for the return.", return_by,
                   f"When it reaches you, it's your move: refund {name}."
                   + (f" If it isn't back by {by}, it comes back to you." if by else ""))
    if case is not None and not dispute and closes_on and closes_on > today and not out_of_date:
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
    elif closes_on and closes_on <= today and not dispute:
        why = f"It was due to close itself on {closes_on.day} {closes_on:%b}; something kept it open: check it."
    elif answered_at:
        why = f"{name} wrote again."
    else:
        why = "Waiting for your answer."
    if dispute:
        due = _day(dispute.get("seller_response_due_date")) if status == "WAITING_FOR_SELLER_RESPONSE" else None
        return out(YOUR_MOVE, holder, why, due, ledger.if_nobody_answers(dispute, today))
    if c.get("dispute_id"):   # a dispute is on the case but wasn't loaded
        r = out(YOUR_MOVE, holder, why, None, "A PayPal dispute is on this case: check it in PayPal.")
        r["paypal"] = True
        return r
    return out(YOUR_MOVE, holder, why, None, "No PayPal deadline: this came to the shop, not to PayPal.")
