"""The demo shop grows without moving a single open case. Run: python3 tests/test_demo_shop.py"""
import collections
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secondlook import ledger, team  # noqa: E402
from secondlook.demo import DemoPayPal  # noqa: E402

OPEN = {  # id: (transaction, buyer, amount, tracking) — as they were before the shop grew (23/10)
    "DEMO-031": ("DEMOTX02334", "DEMODARIOV7Q", "58.00", "LC02334IT"),
    "DEMO-032": ("DEMOTX02111", "DEMO8PKBESYJ5", "42.00", "LC02111IT"),
    "DEMO-033": ("DEMOTX02070", "DEMOYKXWZM4NR", "36.00", "LC02070IT"),
    "DEMO-034": ("DEMOTX01828", "DEMO993D5SX5F", "89.00", "LC01828IT"),   # now a Linen shirt (was a 58.00 apron)
    "DEMO-035": ("DEMOTX02221", "DEMOMWS9HXTRW", "20.00", "LC02221IT"),
    "DEMO-036": ("DEMOTX01961", "DEMOCQLTAFLWC", "240.00", "LC01961IT"),
    "DEMO-037": ("DEMOTX02092", "DEMOMQ283EFU7", "89.00", "LC02092IT"),
    "DEMO-038": ("DEMOTX02093", "DEMOHQL9K8M2M", "29.00", "LC02093IT"),
    "DEMO-039": ("DEMOTX01969", "DEMOYX7M6JGFG", "29.00", "LC01969IT"),
    "DEMO-040": ("DEMOTX01662", "DEMOPCUZVYNKA", "42.00", "LC01662IT"),
    "DEMO-041": ("DEMOTX02126", "DEMOAQJFDH4E5", "20.00", "LC02126IT"),
    "DEMO-042": ("DEMOTX01952", "DEMOL6BHLBDT9", "58.00", "LC01952IT"),
}
pp = DemoPayPal()


def test_the_open_cases_are_the_ones_already_reviewed():
    now = {d["dispute_id"]: d for d in pp.disputes() if d["status"] != "RESOLVED"}
    assert set(now) == set(OPEN)
    for did, (tx, buyer, amount, track) in OPEN.items():
        t = now[did]["disputed_transactions"][0]
        assert (t["seller_transaction_id"], t["buyer"]["payer_id"], now[did]["dispute_amount"]["value"]) == (tx, buyer, amount), did
        assert (pp.raw["records"][did].get("tracking") or {}).get("tracking_number") == track, did


def test_the_two_aprons_are_now_an_apron_and_a_shirt():
    shirt = pp.get_dispute("DEMO-034")
    assert shirt["disputed_transactions"][0]["items"][0]["item_name"] == "Linen shirt"
    assert "shirt" in shirt["messages"][0]["content"] and "apron" not in shirt["messages"][0]["content"]
    o = next(o for o in pp.orders() if o["transaction_id"] == "DEMOTX01828")
    assert o["amount"] == 89.0 and o["fee"] == round(89.0 * 0.034 + 0.35, 2)


def test_a_mid_size_shop_two_percent_disputes_claims_well_under_the_line():
    ov = ledger.overview(pp.disputes(), pp.orders(), pp.today)
    assert 5600 <= ov["orders"] <= 6400, ov["orders"]
    assert 0.017 <= ov["disputes"] / ov["orders"] <= 0.023, ov["disputes"] / ov["orders"]
    hv = ov["high_volume"]
    assert 0.005 <= hv["ratio"] <= 0.007 and not hv["high_volume"], hv


def test_the_named_buyers_keep_their_history():
    by = lambda pid: [o for o in pp.orders() if o["payer_id"] == pid]  # noqa: E731
    assert len(by("DEMODARIOV7Q")) == 5 and len(by("DEMOHELGAB2K")) == 14
    old = {v[1] for v in OPEN.values()} | {"DEMODARIOV7Q", "DEMOHELGAB2K"}
    new_orders = [o for o in pp.orders() if int(o["transaction_id"][6:]) > 2334]
    assert new_orders and not any(o["payer_id"] in old for o in new_orders)   # growth comes from new customers only


def test_a_customer_care_team_of_four():
    t = team.of(pp.shop.get("team"))
    assert [p["name"] for p in team.people(t)] == ["Giulia", "Marta", "Luca", "Sara"]
    assert team.covers(t, "giulia", 240) and team.covers(t, "marta", 30) and not team.covers(t, "marta", 30.01)
    seeded = pp.raw["assignments"]
    assert sorted(d for d, a in seeded.items() if a["to"] == "marta") == ["DEMO-031", "DEMO-032", "DEMO-034"]
    assert sorted(d for d, a in seeded.items() if a["to"] == "luca") == ["DEMO-035", "DEMO-039"]
    assert all(a.get("handoff") is None for a in seeded.values())


def test_closed_cases_say_who_handled_them():
    closed = {d["dispute_id"]: d for d in pp.disputes() if d["status"] == "RESOLVED"}
    handled = pp.raw["handled_by"]
    assert set(handled) <= set(closed) and len(handled) >= len(closed) // 2
    assert set(handled.values()) <= {"Giulia", "Marta", "Luca", "Sara"}
    # nobody signs a case the buyer withdrew or PayPal closed with no decision
    assert not any(ledger.outcome(closed[did]) in ("withdrew", "closed") for did in handled)
    # assistants send refunds up to 30 EUR: a bigger refund or accepted offer the shop sent is the head's
    big = [did for did in handled if ledger.outcome(closed[did]) in ("refunded", "settled_offer") and ledger.refunded(closed[did]) > 30]
    assert big and all(handled[did] == "Giulia" for did in big), [(did, handled[did]) for did in big]


def test_the_new_cases_are_plausible():
    grown = [d for d in pp.disputes() if int(d["dispute_id"][5:]) > 42]
    first = (pp.today - timedelta(days=ledger.WINDOW_DAYS)).isoformat()
    claim_ends = {"MERCHANDISE_OR_SERVICE_NOT_RECEIVED": {"VALID_PROOF_OF_DELIVERY", "NO_PROOF_OF_DELIVERY", "PROTECTED_BY_PAYPAL"},
                  "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED": {"ITEM_SOLD_AS_DESCRIBED", "ITEM_NOT_AS_DESCRIBED"},
                  "CREDIT_NOT_PROCESSED": {"NO_DOCUMENTATION_SUPPORTING_DUE_OF_CREDIT", "VALID_RETURN_DELIVERY_PROOF"}}
    for d in grown:
        assert d["create_time"][:10] >= first, d["dispute_id"]   # inside the shop's 90 days: one rate everywhere
        ended = d.get("dispute_outcome") or {}
        if d["dispute_life_cycle_stage"] == "INQUIRY":
            assert ended.get("outcome_code") != "RESOLVED_WITH_PAYOUT", d["dispute_id"]
        else:
            assert ended.get("outcome_reason") in claim_ends[d["reason"]], d["dispute_id"]
        item, msg = d["disputed_transactions"][0]["items"][0]["item_name"].lower(), d["messages"][0]["content"].lower()
        for word in ("napkin", "shirt", "apron", "frame"):
            assert word not in msg or word in item, (d["dispute_id"], item, msg)


def test_new_customers_are_not_the_team_and_names_rarely_repeat():
    new = {o["payer_id"]: o["name"] for o in pp.orders() if o["payer_id"].startswith("DEMN")}
    assert not any(n.split()[0] in ("Giulia", "Marta", "Luca", "Sara") for n in new.values())
    assert max(collections.Counter(new.values()).values()) <= 5


# ---------- requests by email and web form (25/10) ----------
# The PayPal side of the demo, as it was before requests were added: orders, disputes, records, who has which
# case, who handled what. Shipped reviews and paid-for reviews were made on exactly this.
PAYPAL_SIDE = "2d109ff504445f4270f8971b1d9ec68703d91708ba4dcb56a98f23a22a17e6a8"


def test_adding_requests_moved_nothing_on_the_paypal_side():
    import hashlib
    import json
    keep = {k: pp.raw[k] for k in ("today", "orders", "disputes", "records", "assignments", "handled_by")}
    assert hashlib.sha256(json.dumps(keep, sort_keys=True, ensure_ascii=False).encode()).hexdigest() == PAYPAL_SIDE


def test_the_generator_is_deterministic_and_the_shipped_file_is_its_output():
    import subprocess
    import tempfile
    root = Path(__file__).resolve().parent.parent
    outs = [Path(tempfile.mkdtemp()) / "shop.json" for _ in range(2)]
    for out in outs:
        subprocess.run([sys.executable, str(root / "demo" / "make_demo.py"), str(out)], check=True, capture_output=True)
    assert outs[0].read_bytes() == outs[1].read_bytes() == (root / "demo" / "shop.json").read_bytes()


def test_the_demo_requests_sort_by_rules_to_the_cases_the_film_follows():
    from secondlook import sort
    everything = pp.orders() + pp.other_orders()
    open_orders = {d["disputed_transactions"][0]["seller_transaction_id"] for d in pp.disputes() if d["status"] != "RESOLVED"}
    got = {r["source_id"]: sort.sort(r, everything, open_orders, ai=None) for r in pp.requests()}
    assert {sid: (s["settled"], s["by"], s["order_no"], s["kind"]) for sid, s in got.items()} == {
        "ticketbook:2101": (True, "rules", "LP-90001", "not_received"),     # Sophie, card
        "ticketbook:2102": (True, "rules", "LP-90002", "wrong_size"),       # Lena, bank, web form
        "ticketbook:2004": (True, "rules", "DEMOTX01828", "refund_missing")}  # Pablo: the order of DEMO-034
    paid = {o["order_no"]: o["paid_with"] for o in pp.other_orders()}
    assert paid == {"LP-90001": "card", "LP-90002": "bank"}


def test_the_team_s_roles_are_the_shop_s_own_titles():
    roles = {p["name"]: p["role"] for p in pp.shop["team"]["people"]}
    assert roles == {"Giulia": "Head of customer care", "Marta": "Customer care assistant",
                     "Luca": "Customer care assistant", "Sara": "Customer care assistant"}
    assert set(pp.shop["team"]["roles"]) == {"Head of customer care", "Customer care assistant"}


def test_the_earlier_cases_are_closed_and_touch_nothing_this_morning_or_paypal_holds():
    h = pp.history()
    assert len(h) == 82 and sum(1 for c in h if c["opened"] >= "2026-10-01") == 29
    assert all(c["status"] == "closed" and c["closed_at"] < "2026-10-19" and c["dispute_id"] is None for c in h)
    assert all(c["id"].startswith("DEMO-H") for c in h)              # never a case id the case file could give out
    disputed = {d["disputed_transactions"][0]["seller_transaction_id"] for d in pp.disputes()}
    late = {o["email"] for o in pp.orders() if o["date"] >= "2026-10-10"} | {r["from"]["email"] for r in pp.requests()}
    assert not {c["order_no"] for c in h} & disputed and not {c["customer"]["email"] for c in h} & late
    assert len({c["customer"]["email"] for c in h}) == len(h)        # one case per customer
    tx = {o["transaction_id"]: o["email"] for o in pp.orders()}
    disputing = {tx.get(d["disputed_transactions"][0]["seller_transaction_id"]) for d in pp.disputes()}
    assert not {c["customer"]["email"] for c in h} & disputing          # no customer who ever disputed (by email)


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
