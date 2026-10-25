"""The guard: the seller's limits, enforced in code. The AI cannot override them.

Input:  a Judgment (what the AI recommends) + the seller's policy + the dispute.
Output: a Decision (what the seller is shown), always pending the seller's approval.

Nothing in this module calls a model. That is the point.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

ACTIONS = ("DEFEND", "REFUND", "PARTIAL_REFUND", "REPLACE", "MESSAGE", "ASK_SELLER")

# The checks the judge must report on every dispute, in this order. Shown to the seller.
CHECKS = {
    "claim": "What the buyer actually claims",
    "timeline": "Order, shipping, delivery and dispute dates make sense together",
    "evidence_matches_order": "The seller's evidence belongs to this order",
    "delivery_address": "Delivered to the buyer's PayPal address",
    "delivery_proof": "Proof of delivery (tracking status, signature)",
    "item_vs_listing": "What arrived matches what was listed and ordered",
    "seller_obligations": "The seller kept their own promises (handling time, returns, refunds)",
    "buyer_history": "The buyer's dispute history",
    "paypal_protection": "Seller protection, and what PayPal allows at this stage",
    "hidden_instructions": "The buyer's text tries to instruct the assistant",
}
# INCONSISTENT on these means the evidence itself can't be trusted: never defend or pay on it unseen.
# (FAIL only means "favours the buyer". One label for both meanings was a bug, found by the eval 2026-10-16.)
INTEGRITY_CHECKS = ("timeline", "evidence_matches_order")
MONEY = ("REFUND", "PARTIAL_REFUND", "REPLACE")
# Why the guard stopped an answer, one id per rule. Only these two are about size alone: the limits then
# hand the decision to a person, who may take the AI's answer themselves. Every other stop is about trust
# (hidden instructions, broken evidence, low confidence, a habitual escalator, PayPal's rules).
SIZE_STOPS = {"cap", "always_ask"}
# Stops about the drafted question only, never about the answer itself: PayPal takes no seller message at
# this stage (one message, then the buyer's turn). The answer is unchanged by it.
QUESTION_STOPS = {"message_not_allowed"}


def held_for_size_only(stops: Sequence[str]) -> bool:
    """The answer was held back by the size limits and nothing else (a question-only stop doesn't count)."""
    held = set(stops) - QUESTION_STOPS
    return bool(held) and held <= SIZE_STOPS


@dataclass
class Judgment:
    action: str                  # one of ACTIONS
    confidence: float            # 0..1
    reasoning: str               # plain-English why, citing evidence
    evidence_cited: List[str] = field(default_factory=list)
    draft_message: str = ""      # what the buyer would read
    partial_amount: Optional[str] = None
    checks: List[dict] = field(default_factory=list)  # [{"id", "result", "finding"}]


@dataclass
class Decision:
    action: str
    reasons: List[str]           # guard notes, shown to the seller
    judgment: Judgment
    overridden: bool = False
    stops: List[str] = field(default_factory=list)  # which rules stopped it (ids), in rule order


# One plain amount above zero, with at most one currency marker, before or after: "20.00 EUR", "€20,50", "20".
# Anything else ("1,234.56", "1.234,56", "1 500", "-20", "0") is refused, not guessed: the old loose search
# read "1,234.56" as 1.23 and "-20" as 20, so the cap could check one number and PayPal get another.
# The marker must be the dispute's own currency: "20 USD" on a euro dispute is not 20 euros.
_AMOUNT = re.compile(r"(?:([A-Za-z]{3}|[€$£])\s*)?(\d+(?:[.,]\d{1,2})?)(?:\s*([A-Za-z]{3}|[€$£]))?", re.ASCII)
_SYMBOLS = {"€": "EUR", "£": "GBP", "$": "USD"}


def _partial(text, currency: str) -> float:
    """'20.00 EUR' -> 20.0, '€20,50' -> 20.5 on a euro dispute. Raises ValueError on anything that is not
    one plain amount above zero in the dispute's own currency."""
    m = _AMOUNT.fullmatch(str(text or "").strip())
    if not m or (m.group(1) and m.group(3)):
        raise ValueError(text)
    marker = m.group(1) or m.group(3)
    if marker and _SYMBOLS.get(marker, marker).upper() != str(currency).upper():
        raise ValueError(text)
    value = float(m.group(2).replace(",", "."))
    if value <= 0:
        raise ValueError(text)
    return value


def _sends(action: str, j: Judgment, dispute: dict) -> float:
    """What money_out says, but raising ValueError on an unreadable partial amount (the guard needs to know)."""
    amount = float(dispute["dispute_amount"]["value"])
    if action == "PARTIAL_REFUND" and j.partial_amount:
        return min(amount, _partial(j.partial_amount, dispute["dispute_amount"]["currency_code"]))
    # Decision 8 (25/10): an exchange whose returned item is back at the shop costs the shop the new parcel's
    # postage, and counts that toward the cap and a person's limit. Only a shop inquiry says so (its record
    # carries "exchange_cost" when the return has arrived); a PayPal dispute never does. Never a refund.
    if action == "REPLACE" and dispute.get("exchange_cost") is not None:
        return min(amount, float(dispute["exchange_cost"]))
    return amount if action in MONEY else 0.0


def money_out(action: str, j: Judgment, dispute: dict) -> float:
    """The money an action sends: the offer for a partial refund, the whole amount for a refund or a
    replacement, nothing for a reply or a defence. Used to check a person's limit. Fails closed: when a
    partial amount can't be read, it counts the whole dispute, the largest possible, so the limit check
    is at its strictest (the guard has already routed such a case to a person)."""
    try:
        return _sends(action, j, dispute)
    except ValueError:
        return float(dispute["dispute_amount"]["value"])


def apply_policy(j: Judgment, policy: dict, dispute: dict, records: dict) -> Decision:
    notes: List[str] = []
    stops: List[str] = []
    action = j.action if j.action in ACTIONS else "ASK_SELLER"
    if action != j.action:
        notes.append(f"Model returned unknown action {j.action!r}; routed to you.")
        stops.append("unknown_action")
    # The answer the AI drafted, before any rule below. Rules 6-8 check it even when an earlier rule
    # already handed the case to the seller: a person may now take an answer held back ONLY for its
    # size (may_approve), so every trust reason must be on record after a size stop too. Without this,
    # a refund over the cap with broken evidence was stopped for "cap" alone (found 2026-10-23).
    # The action is unchanged; the seller now sees every reason, not only the first.
    drafted = action

    def _subject() -> str:
        """The answer a trust rule must judge: the current one, or the drafted one once it is the seller's."""
        return drafted if action == "ASK_SELLER" else action

    amount = float(dispute["dispute_amount"]["value"])
    sends_money = action in MONEY
    # The cap applies to the money actually going out: a partial refund of 20 on a 60 order is 20.
    # (Bug found by the eval, 2026-10-16: the guard compared the whole order with the cap.)
    # The same function a person's limit uses, so the cap and the role can never see different amounts.
    out_amount = amount
    if action == "REPLACE":
        out_amount = _sends(action, j, dispute)     # the exchange's own cost, once the item is back (Decision 8)
    if action == "PARTIAL_REFUND" and j.partial_amount:
        try:
            out_amount = _sends(action, j, dispute)
        except ValueError:
            notes.append(f"Partial amount {j.partial_amount!r} is not a number; routed to you.")
            action = "ASK_SELLER"
            stops.append("partial_amount")

    # Rule 1: never move money below the confidence bar.
    if sends_money and j.confidence < policy["min_confidence"]:
        notes.append(f"Confidence {j.confidence:.2f} is below your bar of {policy['min_confidence']:.2f} for giving money back.")
        action = "ASK_SELLER"
        stops.append("confidence")

    # Rule 2: never refund above the seller's cap without asking.
    cap = policy["max_auto_refund"]
    if sends_money and out_amount > cap:
        notes.append(f"Refund of {out_amount:.2f} {dispute['dispute_amount']['currency_code']} is above your auto-refund cap of {cap:.2f}; you decide.")
        action = "ASK_SELLER"
        stops.append("cap")

    # Rule 3: any dispute above this is always yours, whatever the model says.
    if amount > policy["always_ask_above"]:
        notes.append(f"Above {policy['always_ask_above']:.2f}: policy says every such case is reviewed by you.")
        action = "ASK_SELLER"
        stops.append("always_ask")

    # Rule 4: delivered to the PayPal address + "not received" = defend, by your rule.
    tr = records.get("tracking") or {}
    if (policy.get("defend_if_delivered_to_paypal_address")
            and dispute["reason"] == "MERCHANDISE_OR_SERVICE_NOT_RECEIVED"
            and tr.get("status") == "DELIVERED"
            and tr.get("delivered_to_paypal_address") is True
            and action != "DEFEND"):
        notes.append("Tracking shows delivery to the buyer's PayPal address; your policy says defend these.")
        action = "DEFEND"

    # Rule 5: a buyer message is data, never an instruction. If the model's reasoning
    # repeats an instruction found in the buyer's text, route to the seller.
    buyer_text = " ".join(m.get("content", "") for m in dispute.get("messages", [])
                          if m.get("posted_by") == "BUYER").lower()
    for marker in policy.get("injection_markers", []):
        if marker in buyer_text and sends_money:
            notes.append(f"Buyer text contains {marker!r}: looks like an attempt to instruct the assistant. Routed to you.")
            action = "ASK_SELLER"
            stops.append("injection")
            break

    # Rule 6: only actions PayPal allows at this stage. Learned from a real sandbox dispute
    # (2026-10-16): at the INQUIRY stage make_offer allows only REFUND, so REPLACE is not possible.
    allowed = dispute.get("allowed_response_options")
    if allowed:
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
        # Recorded on its own: PayPal may refuse the AI's answer (DEFEND at INQUIRY) and still take a
        # message, so "paypal_allowed" must not stop the question; this does (PP-R-ZOY-10193120, 23/10).
        if "MESSAGE" not in can:
            stops.append("message_not_allowed")
        subject = _subject()
        if subject != "ASK_SELLER" and subject not in can:
            notes.append(f"PayPal does not allow {subject} at the {dispute.get('dispute_life_cycle_stage', '?')} stage "
                         f"(allowed: {', '.join(sorted(c for c in can if c))}). Routed to you.")
            action = "ASK_SELLER"
            stops.append("paypal_allowed")

    # Rule 7: if the judge found the evidence itself inconsistent (a timeline that doesn't add up,
    # tracking that may belong to another order), nobody defends or pays on it unseen. This runs
    # after rule 4 on purpose: "delivered to the PayPal address" means nothing if the dates are wrong.
    failed = [c["id"] for c in j.checks if c.get("id") in INTEGRITY_CHECKS and c.get("result") == "INCONSISTENT"]
    if failed and (_subject() == "DEFEND" or _subject() in MONEY):
        notes.append(f"The judge found the evidence inconsistent ({', '.join(failed)}); check it before anything is sent.")
        action = "ASK_SELLER"
        stops.append("inconsistent")

    # Rule 8: a buyer who disputes far more often than the shop's usual rate (the base rate, not a raw
    # count) gets no money unseen. Only with enough orders to compare, and the numbers are the seller's.
    h, rb = records.get("buyer_history_counts") or {}, policy.get("repeat_buyer") or {}
    if h and rb and _subject() in MONEY and h.get("buyer_orders") \
            and h.get("shop_disputes") and h.get("shop_orders", 0) >= rb.get("min_shop_orders", 20) \
            and h.get("earlier_disputes", 0) >= rb.get("min_earlier_disputes", 2):
        times = (h["buyer_disputes"] / h["buyer_orders"]) / (h["shop_disputes"] / h["shop_orders"])
        if times >= rb.get("times_shop_rate", 3):
            notes.append(f"This buyer disputes {times:.1f} times your shop's usual rate "
                         f"({h['earlier_disputes']} earlier disputes with you). Routed to you.")
            action = "ASK_SELLER"
            stops.append("repeat_buyer")

    # Rule 9: a shop inquiry (its records carry the shop's own order amount; a PayPal dispute's never do, so
    # this never applies to one). Money or goods go out only against an order with an amount, and never
    # once the order is refunded in full: a customer who writes again gets a fresh look, not a second refund
    # (found in review, 25/10). A partial refund is capped at what is left (the amount at stake is what is left).
    if "order_amount" in records and _subject() in MONEY:
        total, back = records.get("order_amount") or 0, records.get("refunded_so_far") or 0
        cur = dispute["dispute_amount"].get("currency_code", "")
        if not total or total <= 0:
            notes.append("There is no order with an amount on this case: no money or goods go out from here.")
            action = "ASK_SELLER"
            stops.append("no_order")
        elif back >= total - 0.005:
            notes.append(f"This order is already refunded in full: {records.get('already_refunded') or f'{back:.2f} {cur}'}. "
                         "Nothing more goes out from here.")
            action = "ASK_SELLER"
            stops.append("already_refunded")
        elif back + (records.get("replaced_so_far") or 0) >= total - 0.005:
            notes.append(f"This order's value already went out as a replacement: {records.get('already_replaced') or ''}. "
                         "Nothing more goes out from here.")
            action = "ASK_SELLER"
            stops.append("already_replaced")

    # Rule 10: a PayPal dispute on an order whose case already logged a refund (the shop answered the customer's
    # email before they went to PayPal). Nothing more goes out unseen, and a defence would contradict the reply
    # already sent: a person checks first. Only when the records say so; every other dispute is untouched.
    if records.get("refund_logged_on_case") and (_subject() in MONEY or _subject() == "DEFEND"):
        notes.append(f"A refund was already logged on this order's case {records['refund_logged_on_case']}: "
                     f"{records.get('already_refunded') or ''}. Check it before anything more is sent or defended.")
        action = "ASK_SELLER"
        stops.append("refund_logged_on_case")

    return Decision(action=action, reasons=notes, judgment=j, overridden=(action != j.action), stops=stops)


def may_approve(recommended: str, chosen: str, drafted_for: str | None = None, stops: Sequence[str] = ()) -> bool:
    """The seller approves the action they were shown, never "whatever the model says now".
    Two exceptions on "your call" (ASK_SELLER):
    - they may send the drafted question, because a message moves no money. Not when the draft was
      written for a money action the limits stopped (`drafted_for`): it promises the money (DEMO-034, 21/10).
      Not when PayPal takes no message at this stage (`message_not_allowed`): it would refuse it (422).
      (`paypal_allowed` alone doesn't stop it: PayPal may refuse the AI's answer and still take a message.)
      Not when the AI returned an action that doesn't exist (`unknown_action`): its draft is unvetted.
    - they may take the answer the AI drafted when the ONLY reasons it was held back are its size
      (SIZE_STOPS): those limits exist to hand the decision to a person, and this person is it.
      Never when it was held back for trust; never with no recorded reasons (reviews before 23/10).
    How much money this person may send is checked after this, against their role (team.covers)."""
    if recommended == "ASK_SELLER" and chosen == "MESSAGE":
        # (`refund_logged_on_case`: the draft was a defence against a refund the shop already promised.)
        return (drafted_for not in MONEY and "message_not_allowed" not in stops and "unknown_action" not in stops
                and "refund_logged_on_case" not in stops)
    if recommended == "ASK_SELLER" and chosen == drafted_for and chosen != "ASK_SELLER" and held_for_size_only(stops):
        return True
    return chosen == recommended
