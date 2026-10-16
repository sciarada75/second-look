"""The guard: the seller's limits, enforced in code. The AI cannot override them.

Input:  a Judgment (what the AI recommends) + the seller's policy + the dispute.
Output: a Decision (what the seller is shown), always pending the seller's approval.

Nothing in this module calls a model. That is the point.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

ACTIONS = ("DEFEND", "REFUND", "PARTIAL_REFUND", "REPLACE", "ASK_SELLER")


@dataclass
class Judgment:
    action: str                  # one of ACTIONS
    confidence: float            # 0..1
    reasoning: str               # plain-English why, citing evidence
    evidence_cited: List[str] = field(default_factory=list)
    draft_message: str = ""      # what the buyer would read
    partial_amount: Optional[str] = None


@dataclass
class Decision:
    action: str
    reasons: List[str]           # guard notes, shown to the seller
    judgment: Judgment
    overridden: bool = False


def apply_policy(j: Judgment, policy: dict, dispute: dict, records: dict) -> Decision:
    notes: List[str] = []
    action = j.action if j.action in ACTIONS else "ASK_SELLER"
    if action != j.action:
        notes.append(f"Model returned unknown action {j.action!r}; routed to you.")

    amount = float(dispute["dispute_amount"]["value"])
    money_out = action in ("REFUND", "PARTIAL_REFUND", "REPLACE")
    # The cap applies to the money actually going out: a partial refund of 20 on a 60 order is 20.
    # (Bug found by the eval, 2026-10-16: the guard compared the whole order with the cap.)
    out_amount = amount
    if action == "PARTIAL_REFUND" and j.partial_amount:
        try:
            out_amount = min(amount, float(str(j.partial_amount).replace(",", ".")))
        except ValueError:
            notes.append(f"Partial amount {j.partial_amount!r} is not a number; routed to you.")
            action = "ASK_SELLER"

    # Rule 1: never move money below the confidence bar.
    if money_out and j.confidence < policy["min_confidence"]:
        notes.append(f"Confidence {j.confidence:.2f} is below your bar of {policy['min_confidence']:.2f} for giving money back.")
        action = "ASK_SELLER"

    # Rule 2: never refund above the seller's cap without asking.
    cap = policy["max_auto_refund"]
    if money_out and out_amount > cap:
        notes.append(f"Refund of {out_amount:.2f} {dispute['dispute_amount']['currency_code']} is above your auto-refund cap of {cap:.2f}; you decide.")
        action = "ASK_SELLER"

    # Rule 3: any dispute above this is always yours, whatever the model says.
    if amount > policy["always_ask_above"]:
        notes.append(f"Above {policy['always_ask_above']:.2f}: policy says every such case is reviewed by you.")
        action = "ASK_SELLER"

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
        if marker in buyer_text and money_out:
            notes.append(f"Buyer text contains {marker!r}: looks like an attempt to instruct the assistant. Routed to you.")
            action = "ASK_SELLER"
            break

    # Rule 6: only actions PayPal allows at this stage. Learned from a real sandbox dispute
    # (2026-10-16): at the INQUIRY stage make_offer allows only REFUND, so REPLACE is not possible.
    allowed = dispute.get("allowed_response_options")
    if allowed:
        can = set()
        if "provide_evidence" in {l.get("rel") for l in dispute.get("links", [])}:
            can.add("DEFEND")
        for t in allowed.get("accept_claim", {}).get("accept_claim_types", []):
            can.add({"REFUND": "REFUND", "PARTIAL_REFUND": "PARTIAL_REFUND"}.get(t, ""))
        for t in allowed.get("make_offer", {}).get("offer_types", []):
            can.add({"REFUND": "PARTIAL_REFUND", "REPLACEMENT_WITHOUT_REFUND": "REPLACE",
                     "REFUND_WITH_REPLACEMENT": "REPLACE"}.get(t, ""))
        if action != "ASK_SELLER" and action not in can:
            notes.append(f"PayPal does not allow {action} at the {dispute.get('dispute_life_cycle_stage', '?')} stage "
                         f"(allowed: {', '.join(sorted(c for c in can if c))}). Routed to you.")
            action = "ASK_SELLER"

    return Decision(action=action, reasons=notes, judgment=j, overridden=(action != j.action))
