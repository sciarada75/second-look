"""The guard: the seller's limits, enforced in code. The AI cannot override them.

Input:  a Judgment (what the AI recommends) + the seller's policy + the dispute.
Output: a Decision (what the seller is shown), always pending the seller's approval.

Nothing in this module calls a model. That is the point.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

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
AMOUNT_STOPS = {"cap", "always_ask"}


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


def _partial(text) -> float:
    """'20.00 EUR' -> 20.0. Raises ValueError when there is no number."""
    num = re.search(r"\d+(?:[.,]\d{1,2})?", str(text or ""))
    if not num:
        raise ValueError(text)
    return float(num.group(0).replace(",", "."))


def money_out(action: str, j: Judgment, dispute: dict) -> float:
    """The money an action sends: the offer for a partial refund, the whole amount for a refund or a
    replacement, nothing for a reply or a defence. Used to check a person's limit."""
    amount = float(dispute["dispute_amount"]["value"])
    if action == "PARTIAL_REFUND" and j.partial_amount:
        return min(amount, _partial(j.partial_amount))
    return amount if action in MONEY else 0.0


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
    # Recording only: the resulting action is exactly what it was before.
    drafted = action

    amount = float(dispute["dispute_amount"]["value"])
    sends_money = action in MONEY
    # The cap applies to the money actually going out: a partial refund of 20 on a 60 order is 20.
    # (Bug found by the eval, 2026-10-16: the guard compared the whole order with the cap.)
    out_amount = amount
    if action == "PARTIAL_REFUND" and j.partial_amount:
        try:
            out_amount = min(amount, _partial(j.partial_amount))
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
        subject = drafted if action == "ASK_SELLER" else action
        if subject != "ASK_SELLER" and subject not in can:
            notes.append(f"PayPal does not allow {subject} at the {dispute.get('dispute_life_cycle_stage', '?')} stage "
                         f"(allowed: {', '.join(sorted(c for c in can if c))}). Routed to you.")
            action = "ASK_SELLER"
            stops.append("paypal_allowed")

    # Rule 7: if the judge found the evidence itself inconsistent (a timeline that doesn't add up,
    # tracking that may belong to another order), nobody defends or pays on it unseen. This runs
    # after rule 4 on purpose: "delivered to the PayPal address" means nothing if the dates are wrong.
    failed = [c["id"] for c in j.checks if c.get("id") in INTEGRITY_CHECKS and c.get("result") == "INCONSISTENT"]
    subject = drafted if action == "ASK_SELLER" else action
    if failed and (subject == "DEFEND" or subject in MONEY):
        notes.append(f"The judge found the evidence inconsistent ({', '.join(failed)}); check it before anything is sent.")
        action = "ASK_SELLER"
        stops.append("inconsistent")

    # Rule 8: a buyer who disputes far more often than the shop's usual rate (the base rate, not a raw
    # count) gets no money unseen. Only with enough orders to compare, and the numbers are the seller's.
    h, rb = records.get("buyer_history_counts") or {}, policy.get("repeat_buyer") or {}
    subject = drafted if action == "ASK_SELLER" else action
    if h and rb and subject in MONEY and h.get("buyer_orders") \
            and h.get("shop_disputes") and h.get("shop_orders", 0) >= rb.get("min_shop_orders", 20) \
            and h.get("earlier_disputes", 0) >= rb.get("min_earlier_disputes", 2):
        times = (h["buyer_disputes"] / h["buyer_orders"]) / (h["shop_disputes"] / h["shop_orders"])
        if times >= rb.get("times_shop_rate", 3):
            notes.append(f"This buyer disputes {times:.1f} times your shop's usual rate "
                         f"({h['earlier_disputes']} earlier disputes with you). Routed to you.")
            action = "ASK_SELLER"
            stops.append("repeat_buyer")

    return Decision(action=action, reasons=notes, judgment=j, overridden=(action != j.action), stops=stops)


def may_approve(recommended: str, chosen: str, drafted_for: str | None = None, stops=()) -> bool:
    """The seller approves the action they were shown, never "whatever the model says now".
    Two exceptions on "your call" (ASK_SELLER):
    - they may send the drafted question, because a message moves no money. Not when the draft was
      written for a money action the limits stopped (`drafted_for`): it promises the money (DEMO-034, 21/10).
    - they may take the answer the AI drafted when the ONLY reasons it was held back are its size
      (AMOUNT_STOPS): those limits exist to hand the decision to a person, and this person is it.
      Never when it was held back for trust; never with no recorded reasons (reviews before 23/10).
    How much money this person may send is checked after this, against their role (team.covers)."""
    if recommended == "ASK_SELLER" and chosen == "MESSAGE":
        return drafted_for not in MONEY
    if recommended == "ASK_SELLER" and chosen == drafted_for and chosen != "ASK_SELLER" \
            and stops and set(stops) <= AMOUNT_STOPS:
        return True
    return chosen == recommended
