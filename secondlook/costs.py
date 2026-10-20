"""What each choice costs, and the shop's position against PayPal's high-volume threshold.

Pure arithmetic on PayPal's published rules; no model. The figures the seller sees come from here.

PayPal's rules used (US User Agreement 14 Sep 2026; fee pages US 1 Oct 2026, IE 7 Sep 2026):
  - No dispute fee while a dispute stays an inquiry, or is settled directly with the buyer.
  - Once it is a claim: the Standard fee if the seller loses (not charged when the seller wins);
    the High Volume fee whatever the outcome, for sellers with a dispute ratio >= 1.5 % and
    more than 100 sales in the previous three full calendar months.
  - A refund does not return the fee PayPal took on the payment.
"""
from __future__ import annotations

import math

# Standard / High Volume dispute fee by currency.
DISPUTE_FEE = {"EUR": (14.00, 28.00), "USD": (15.00, 30.00)}
HIGH_VOLUME_RATIO = 0.015
HIGH_VOLUME_MIN_SALES = 100

# Past the inquiry: a PayPal claim, its appeals, or a card chargeback filed with the bank.
ESCALATED_STAGES = ("CHARGEBACK", "PRE_ARBITRATION", "ARBITRATION")


def escalated(dispute: dict) -> bool:
    """The case went past the inquiry, where the dispute fee and the claim rules apply."""
    return dispute.get("dispute_life_cycle_stage") in ESCALATED_STAGES or dispute.get("dispute_channel") == "EXTERNAL"


def high_volume(claims: int, sales: int) -> dict:
    """The shop against PayPal's high-volume threshold. `claims` = escalated claims + card chargebacks."""
    ratio = claims / sales if sales else 0.0
    above = sales > HIGH_VOLUME_MIN_SALES and ratio >= HIGH_VOLUME_RATIO
    # the smallest number of claims that reaches 1.5 % of these sales
    at = math.ceil(round(HIGH_VOLUME_RATIO * sales, 6))
    return {"claims": claims, "sales": sales, "ratio": ratio, "high_volume": above,
            "counts": sales > HIGH_VOLUME_MIN_SALES, "claims_to_threshold": max(0, at - claims)}


def paths(amount: float, currency: str, paypal_fee, item_cost, postage, is_high_volume: bool) -> dict:
    """The three ways a dispute can end, in money. `paypal_fee` is PayPal's fee on the payment
    (positive number); `item_cost` and `postage` are the seller's own, None when not set."""
    standard, hv = DISPUTE_FEE.get(currency, (None, None))
    claim_fee = hv if is_high_volume else standard
    known = item_cost is not None and postage is not None
    sunk = (item_cost + postage) if known else None          # what the goods and the postage cost you
    fee = abs(paypal_fee) if paypal_fee is not None else None
    out_of_pocket = round(sunk + (fee or 0), 2) if known else None
    return {
        "currency": currency,
        "amount": amount,
        "paypal_fee": fee,
        "costs_known": known,
        "refund_now": {"back_to_buyer": amount, "out_of_pocket": out_of_pocket},
        "settled": {"dispute_fee": 0.0},
        "claim_lost": {"back_to_buyer": amount, "dispute_fee": claim_fee,
                       "out_of_pocket": round(out_of_pocket + claim_fee, 2) if known and claim_fee is not None else None},
        "claim_won": {"dispute_fee": hv if is_high_volume else 0.0},
        "high_volume": is_high_volume,
    }
