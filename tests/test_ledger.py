"""The money and the record: what each choice costs, PayPal's high-volume line, how cases ended,
one customer's history. Run: python3 tests/test_ledger.py"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secondlook import costs, evidence, ledger  # noqa: E402
from secondlook.demo import DemoPayPal  # noqa: E402


def d(did, buyer="B1", status="RESOLVED", stage="INQUIRY", code=None, reason=None, amount="40.00",
      opened="2026-09-10T10:00:00Z", refunded=None, channel="INTERNAL"):
    x = {"dispute_id": did, "status": status, "dispute_life_cycle_stage": stage, "dispute_channel": channel,
         "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "create_time": opened,
         "seller_response_due_date": "2026-09-30T10:00:00Z",
         "dispute_amount": {"currency_code": "EUR", "value": amount},
         "disputed_transactions": [{"buyer": {"payer_id": buyer, "name": buyer}}]}
    if code:
        x["dispute_outcome"] = {"outcome_code": code, "outcome_reason": reason}
        if refunded:
            x["dispute_outcome"]["amount_refunded"] = {"currency_code": "EUR", "value": refunded}
    return x


def test_each_way_out_costs_what_paypal_charges():
    c = costs.paths(58.0, "EUR", -2.32, 19.0, 4.90, False)
    assert c["refund_now"]["out_of_pocket"] == 26.22          # item + postage + PayPal's fee, which it keeps
    assert c["settled"]["dispute_fee"] == 0.0                  # an inquiry settled directly costs no fee
    assert c["claim_lost"]["dispute_fee"] == 14.0 and c["claim_lost"]["out_of_pocket"] == 40.22
    assert c["claim_won"]["dispute_fee"] == 0.0                # standard fee only when you lose


def test_high_volume_fee_is_charged_even_when_you_win():
    c = costs.paths(58.0, "EUR", 2.32, 19.0, 4.90, True)
    assert c["claim_lost"]["dispute_fee"] == 28.0 and c["claim_won"]["dispute_fee"] == 28.0


def test_unknown_item_cost_is_never_guessed():
    c = costs.paths(42.0, "EUR", 1.78, None, None, False)
    assert c["refund_now"]["out_of_pocket"] is None and c["claim_lost"]["out_of_pocket"] is None


def test_high_volume_line_needs_both_the_ratio_and_more_than_100_sales():
    assert costs.high_volume(15, 1000)["high_volume"]                   # 1.5 % of 1,000
    assert not costs.high_volume(14, 1000)["high_volume"]
    assert costs.high_volume(14, 1000)["claims_to_threshold"] == 1
    assert not costs.high_volume(2, 100)["high_volume"]                 # 2 %, but not more than 100 sales
    assert costs.high_volume(8, 1750)["claims_to_threshold"] == 19      # 1.5 % of 1,750 = 26.25 -> 27


def test_outcomes_follow_paypals_codes_and_reasons():
    assert ledger.outcome(d("1", code="RESOLVED_SELLER_FAVOUR")) == "won"
    assert ledger.outcome(d("2", code="CANCELED_BY_BUYER")) == "withdrew"
    assert ledger.outcome(d("3")) == "closed"                           # closed with no decision: its own row
    assert ledger.outcome(d("4", code="RESOLVED_BUYER_FAVOUR", reason="PARTIAL_REFUND_OFFER_ACCEPTED")) == "settled_offer"
    assert ledger.outcome(d("5", code="RESOLVED_BUYER_FAVOUR", reason="SELLER_ISSUED_REFUND")) == "refunded"
    assert ledger.outcome(d("6", stage="CHARGEBACK", code="RESOLVED_BUYER_FAVOUR", reason="NO_PROOF_OF_DELIVERY")) == "lost_claim"
    assert ledger.outcome(d("7", stage="CHARGEBACK", code="RESOLVED_BUYER_FAVOUR", reason="NO_SELLER_RESPONSE")) == "lost_no_reply"
    assert ledger.outcome(d("8", status="WAITING_FOR_SELLER_RESPONSE")) is None


def test_a_card_chargeback_counts_as_escalated():
    assert costs.escalated(d("1", channel="EXTERNAL")) and costs.escalated(d("2", stage="CHARGEBACK"))
    assert not costs.escalated(d("3"))


def test_what_happens_if_nobody_answers_is_paypals_rule_for_the_stage():
    today = date(2026, 9, 12)
    assert "PayPal decides for the buyer" in ledger.if_nobody_answers(d("1", status="WAITING_FOR_SELLER_RESPONSE"), today)
    assert "can't be reopened" in ledger.if_nobody_answers(d("2", status="WAITING_FOR_BUYER_RESPONSE"), today)
    assert "buyer's favour" in ledger.if_nobody_answers(d("3", status="WAITING_FOR_SELLER_RESPONSE", stage="CHARGEBACK"), today)


def test_buyer_escalations_are_counted_against_the_shops_own_rate():
    now = d("NOW", status="WAITING_FOR_SELLER_RESPONSE", opened="2026-10-10T10:00:00Z")
    shop = [now, d("A", stage="CHARGEBACK", code="RESOLVED_BUYER_FAVOUR"), d("B", stage="CHARGEBACK", code="RESOLVED_SELLER_FAVOUR"),
            d("C", code="CANCELED_BY_BUYER"), d("D", buyer="B2", code="CANCELED_BY_BUYER")]
    orders = [{"payer_id": "B1", "date": "2026-09-01"}] * 4 + [{"payer_id": "B2", "date": "2026-09-01"}] * 96
    h = evidence.history(now, shop, orders, date(2026, 10, 12))
    assert (h["earlier_disputes"], h["earlier_escalated"], h["shop_closed"], h["shop_escalated"]) == (3, 2, 4, 2)
    assert "Took 2 of 3 earlier disputes" in evidence.describe_history(h)


def test_customer_card_by_email_or_payer_id():
    shop = [d("A", stage="CHARGEBACK", code="RESOLVED_BUYER_FAVOUR", refunded="40.00"), d("B", code="CANCELED_BY_BUYER")]
    orders = [{"payer_id": "B1", "email": "b1@example.com", "name": "Bea", "date": "2026-09-01", "amount": 40.0}] * 2
    by_mail, by_id = ledger.customer("B1@example.com", shop, orders), ledger.customer("B1", shop, orders)
    assert by_mail == by_id and by_mail["escalated"] == 1 and by_mail["refunded"] == 40.0
    assert ledger.customer("nobody@example.com", shop, orders) is None


def test_demo_shop_runs_through_the_same_code():
    pp = DemoPayPal()
    r = pp.get_case("DEMO-031")["seller_records"]
    assert r["costs"]["refund_now"]["out_of_pocket"] is not None and r["buyer_history_counts"]["earlier_escalated"] == 2
    ov = ledger.overview(pp.disputes(), pp.orders(), pp.today)
    assert ov["handled"] == sum(ov["counts"].values()) and ov["open"] == 12



def test_exposure_uses_the_shops_own_record_not_invented_odds():
    from datetime import date
    def d(i, status, amount, outcome=None, refunded=None):
        x = {"dispute_id": f"X{i}", "status": status, "create_time": "2026-10-01T10:00:00Z",
             "dispute_amount": {"currency_code": "EUR", "value": f"{amount:.2f}"}, "dispute_life_cycle_stage": "INQUIRY"}
        if outcome:
            x["dispute_outcome"] = {"outcome_code": outcome}
            if refunded:
                x["dispute_outcome"]["amount_refunded"] = {"currency_code": "EUR", "value": f"{refunded:.2f}"}
        return x
    disputes = [d(1, "RESOLVED", 100, "RESOLVED_SELLER_FAVOUR"), d(2, "RESOLVED", 100, "RESOLVED_BUYER_FAVOUR", 100),
                d(3, "WAITING_FOR_SELLER_RESPONSE", 50), d(4, "WAITING_FOR_BUYER_RESPONSE", 30)]
    ex = ledger.exposure(disputes, date(2026, 10, 20), high_volume_now=False)
    assert ex["at_stake"] == 80 and ex["all_won"] == 0
    assert ex["all_lost"] == 80 + 2 * 14                       # every refund plus the standard claim fee
    assert abs(ex["share"] - ledger.refunded(disputes[1]) / 200) < 1e-9 and ex["like_before"] == round(80 * ex["share"], 2)

if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
