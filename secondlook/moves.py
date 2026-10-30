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
        "not_received": "Hi {first},\n\nThank you for writing, and sorry the parcel hasn't reached you. We're checking "
                        "with {carrier} what happened to it{tracking} and will write to you again soon.",
        "not_as_described": "Hi {first},\n\nThank you for telling us, and sorry it isn't what you expected. Could you send "
                            "us a photo of the item and of what doesn't match the listing? Then we can put it right.",
        "wrong_size": "Hi {first},\n\nThank you for writing, and sorry the size isn't right. Tell us the size you need "
                      "and we'll tell you how to send this one back.",
        "refund_missing": "Hi {first},\n\nThank you for writing. We're checking what happened with {order} and will "
                          "write to you again soon.",
        "question": "Hi {first},\n\nThank you for your message. We're looking into it and will write to you again soon.",
    },
    # a shop request: the refund is logged now and paid by the shop, so the text never says it already arrived
    "REFUND": {"*": "Hi {first},\n\nWe're sorry for the trouble. We're refunding {amount} for {order}. You'll see it "
                    "back on your account in a few days."},
    "REPLACE": {
        "wrong_size": "Hi {first},\n\nWe're sorry the size isn't right. Reply with the size you need and we'll tell you "
                      "how to send this one back; the right one leaves as soon as it's on its way to us.",
        "*": "Hi {first},\n\nWe're sorry for the trouble. We're sending you a replacement for {order}, and will write "
             "with its tracking number as soon as it ships.",
    },
    # a delivery the courier recorded; without one the evidence is the shipping record, and the text says only that
    "DEFEND": {"delivered": "Hi {first},\n\nOur records show your parcel was delivered{delivered}{tracking}. We've shared "
                            "the courier's record with PayPal. If something is still wrong, please write to us and "
                            "we'll look again.",
               "*": "Hi {first},\n\nWe've shared our shipping record{tracking} with PayPal. If something is still "
                    "wrong, please write to us and we'll look into it."},
}
# On a PayPal dispute: a refund goes through PayPal at once; a replacement is an offer the buyer accepts in PayPal.
DISPUTE_TEMPLATES = {
    "REFUND": {"*": "Hi {first},\n\nWe're sorry for the trouble. We've refunded {amount} through PayPal for {order}. "
                    "You'll see it back on your account in a few days."},
    "REPLACE": {"*": "Hi {first},\n\nWe're sorry for the trouble. We've offered to send you a replacement for {order}. "
                     "Once you accept the offer in PayPal, we'll ship it and send you its tracking number."},
}
# When the case has no such fact, the words a text falls back on.
FACT_DEFAULTS = {"first": "there", "carrier": "the courier", "tracking": "", "amount": "the full amount",
                 "order": "your order", "delivered": "", "shop": "the shop"}
LABEL = {"MESSAGE": "Reply only", "REFUND": "Answer and refund {amount}", "REPLACE": "Offer a replacement",
         "DEFEND": "Send your evidence"}
INQUIRY_LABEL = {**LABEL, "REPLACE": "Answer and exchange"}
THEN = {"MESSAGE": "{first} gets your reply. No money moves.",
        "REFUND": "{first} gets your reply and {amount} back. PayPal closes the dispute; the case waits for PayPal "
                  "to confirm.",
        "REPLACE": "PayPal passes your offer to {first}; if they accept, you send the replacement.",
        "DEFEND": "PayPal gets your shipping record and {first} your reply. No money moves."}
INQUIRY_THEN = {**THEN, "REFUND": "{first} gets your reply, and the refund of {amount} is logged on the case.",
                "REPLACE": "{first} gets your reply; the replacement is logged for you to send."}


def _fill(words: str, facts: dict, defaults: dict = FACT_DEFAULTS) -> str:
    # Values are substituted, never re-parsed as templates: never concatenate data into a template before calling this.
    return words.format(**{**defaults, **{k: v for k, v in facts.items() if v}})


def kind_of(case: dict | None, dispute: dict | None) -> str:
    """The cause, as cases.KINDS names it: PayPal's reason on a dispute, else the shop case's own kind."""
    if dispute:     # a PayPal reason we don't map (e.g. UNAUTHORISED) never borrows the shop case's kind
        return REASON_KIND.get(dispute.get("reason"), "question")
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


def text(action: str, kind: str, facts: dict, inquiry: bool = False) -> str:
    """The fixed reply that goes with a move, filled with the case's facts and signed by the shop. A person may edit it.
    It says only what is true: a dispute and a shop request differ on refunds and replacements, a defence claims a
    delivery only when the courier recorded one, and an unknown action raises KeyError (a money move must never get a
    reply-only text)."""
    t = DISPUTE_TEMPLATES[action] if not inquiry and action in DISPUTE_TEMPLATES else TEMPLATES[action]
    if action == "DEFEND":
        words = t["delivered"] if facts.get("delivered") else t["*"]
    else:
        words = t.get(kind) or t["*"]
    return _fill(words + SIGN, facts)


def label(action: str, inquiry: bool, facts: dict) -> str:
    """The button: everything the move sends ("Answer and refund 29.00 EUR")."""
    return _fill((INQUIRY_LABEL if inquiry else LABEL)[action], facts)


def then(action: str, facts: dict, inquiry: bool) -> str:
    """What happens next, joined under the button."""
    out = _fill((INQUIRY_THEN if inquiry else THEN)[action], facts, {**FACT_DEFAULTS, "first": "the customer"})
    return out[:1].upper() + out[1:]
