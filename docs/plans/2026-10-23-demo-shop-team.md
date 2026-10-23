# Demo Shop Grows Implementation Plan (plan 2 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The made-up demo shop "Linen & Paper" becomes a mid-size shop with a customer care team — about 6,000 orders in 90 days, a dispute rate near 2%, claims near 0.6% of last quarter's sales, four people with roles — while the 12 open cases (and the 11 AI reviews already paid for) stay valid.

**Architecture:** `demo/make_demo.py` keeps its existing random stream untouched up to the last open case, so every existing order, dispute, buyer, date and tracking number comes out identical. Growth is appended *after* that, from a second seeded random stream: new customers only (so each existing buyer's history is unchanged), extra orders, and extra *closed* disputes with ids from DEMO-043 on. The team, the starting assignments and who handled each closed case are written into `demo/shop.json`, which plan 1's code already reads (`shop.team`, top-level `assignments`).

**Tech Stack:** Python 3.9 standard library. Tests: `python3 tests/<file>.py`.

**Spec:** `docs/specs/2026-10-23-teams-helpdesk-film3-design.md` §3. Depends on plan 1 (merged).

**Why the stream must not move:** each saved review (`.tmp/reviews/DEMO-0xx.json`) records what it saw (`web._seen`: buyer messages, stage, amount, tracking number, address). If any of those change, the page marks the review out of date and a new one costs money. Reviews also quote each buyer's own history ("4 of 5 orders", "1 in 3 orders") and the shop's rate ("your shop's 2%"); new orders therefore come only from new customers, and the rate is held near 2%.

**Two cases change on purpose** and need a new review (~$0.06 each, **Claudia approves before it runs**):
- **DEMO-034** becomes a *Linen shirt, 89 EUR* (was an apron at 58, identical to DEMO-031 next to it in the film: a viewer would take them for one case).
- **DEMO-036** quotes "19 claims away" from PayPal's line; with more claims that number changes.

---

## File structure

| File | Responsibility |
|---|---|
| `demo/make_demo.py` (modify) | `order()` takes a random stream; DEMO-034 turned into a shirt without touching the stream; team, assignments, `handled_by`; growth block from a second stream |
| `demo/shop.json` (regenerated) | the data |
| `tests/test_demo_shop.py` (create) | the invariants: open cases unchanged, size, rates, team |
| `secondlook/web.py` (modify) | customer card shows who handled a closed case |
| `tests/test_web.py` (modify) | that line |
| `README.md` (modify) | the demo shop's description |

Snapshot of the 12 open cases **before** this plan (id, transaction, buyer, amount, tracking), used by the test:

```
DEMO-031 DEMOTX02334 DEMODARIOV7Q  58.00 LC02334IT
DEMO-032 DEMOTX02111 DEMO8PKBESYJ5 42.00 LC02111IT
DEMO-033 DEMOTX02070 DEMOYKXWZM4NR 36.00 LC02070IT
DEMO-034 DEMOTX01828 DEMO993D5SX5F 58.00 LC01828IT   -> becomes 89.00 (Linen shirt)
DEMO-035 DEMOTX02221 DEMOMWS9HXTRW 20.00 LC02221IT
DEMO-036 DEMOTX01961 DEMOCQLTAFLWC 240.00 LC01961IT
DEMO-037 DEMOTX02092 DEMOMQ283EFU7 89.00 LC02092IT
DEMO-038 DEMOTX02093 DEMOHQL9K8M2M 29.00 LC02093IT
DEMO-039 DEMOTX01969 DEMOYX7M6JGFG 29.00 LC01969IT
DEMO-040 DEMOTX01662 DEMOPCUZVYNKA 42.00 LC01662IT
DEMO-041 DEMOTX02126 DEMOAQJFDH4E5 20.00 LC02126IT
DEMO-042 DEMOTX01952 DEMOL6BHLBDT9 58.00 LC01952IT
```

Today (before): 2,334 orders (1,730 in 90 days), 42 disputes (38 in 90 days, 2.2%), 8 claims on 1,750 sales last quarter (0.46%), 19 claims from the line.

---

### Task 1: The invariants, as a failing test

**Files:**
- Create: `tests/test_demo_shop.py`

- [ ] **Step 1: Write the test**

```python
"""The demo shop grows without moving a single open case. Run: python3 tests/test_demo_shop.py"""
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
    closed = [d["dispute_id"] for d in pp.disputes() if d["status"] == "RESOLVED"]
    handled = pp.raw["handled_by"]
    assert set(handled) <= set(closed) and len(handled) >= len(closed) // 2
    assert set(handled.values()) <= {"Giulia", "Marta", "Luca", "Sara"}


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
```

Note: `test_the_named_buyers_keep_their_history` reads the buyers of the 12 open cases from `OPEN`; growth must not add orders for them, for Dario, or for Helga.

- [ ] **Step 2: Run it to see it fail**

Run: `cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && python3 tests/test_demo_shop.py`
Expected: an `AssertionError` in the first test (DEMO-034 amount is 58.00) — the open-case check fails before anything else.

- [ ] **Step 3: Commit the failing test** (it documents the target)

```bash
git add tests/test_demo_shop.py
git commit -m "Demo shop invariants: the open cases stay as reviewed, the shop grows around them"
```

---

### Task 2: The generator grows the shop without moving the open cases

**Files:**
- Modify: `demo/make_demo.py`

- [ ] **Step 1: `order()` takes a random stream** — change the signature and its two `rng` uses:

```python
def order(c, day, item, qty=1, hour=None, r=None):
    global tx
    r = r or rng
    tx += 1
    amount = PRICE[item] * qty
    o = {"transaction_id": f"DEMOTX{tx:05d}", "payer_id": c["payer_id"], "email": c["email"], "name": c["name"],
         "address": c["address"], "date": day.isoformat(),
         "time": iso(day, hour if hour is not None else r.randint(8, 22), r.randint(0, 59)),
         "amount": amount, "fee": fee(amount), "items": [{"item_name": item, "item_quantity": str(qty)}]}
    orders.append(o)
    return o
```

(Argument evaluation order is unchanged — `hour` first, then minutes — so the existing stream is identical.)

- [ ] **Step 2: DEMO-034 becomes a shirt, without a new random draw.** Replace the DEMO-034 block (`o = pick("2026-09-20", "2026-09-24", "Linen apron")` and its `dispute(...)`) with:

```python
o = pick("2026-09-20", "2026-09-24", "Linen apron")
# The film shows this case right after DEMO-031 (also a 58 EUR apron): a viewer would take them for one case.
# It becomes a shirt AFTER the pick, so the random stream (and every case after it) stays as reviewed (23/10).
o["items"] = [{"item_name": "Linen shirt", "item_quantity": "1"}]
o["amount"], o["fee"] = PRICE["Linen shirt"], fee(PRICE["Linen shirt"])
dispute(o, CNP, opened_at(o, 25, 10, 30), "I returned the shirt on 5 October, you received it on the 8th. Still no refund.",
        status="WAITING_FOR_SELLER_RESPONSE", extra=OPEN_INQUIRY,
        rec={"tracking": tracking(o, "DELIVERED", 1, 3, delivered_to_paypal_address=True), "ship_to_paypal": True,
             "return_tracking": {"carrier": "OTHER", "carrier_name_other": "Local courier", "tracking_number": "LCRET40812IT",
                                 "status": "DELIVERED", "shipped_date": "2026-10-05", "last_update": "2026-10-08T11:20:00Z"},
             "refund_issued": False})
```

- [ ] **Step 3: The team, in `SHOP`.** Change `"about"` and add `"team"`:

```python
    "about": "Demo shop, made-up data: handmade linen and art prints from Bologna, about 2,000 orders a month, "
             "four people in customer care.",
    "team": {
        "currency": "EUR",
        "roles": {"Customer care manager": {"refund_up_to": None},
                  "Customer care agent": {"refund_up_to": 30.0}},
        "people": [{"id": "giulia", "name": "Giulia", "role": "Customer care manager"},
                   {"id": "marta", "name": "Marta", "role": "Customer care agent"},
                   {"id": "luca", "name": "Luca", "role": "Customer care agent"},
                   {"id": "sara", "name": "Sara", "role": "Customer care agent"}]},
```

(Giulia first: a handoff goes to the first person whose limit covers it.)

- [ ] **Step 4: Growth, appended after the last open case** (immediately before `OUT.write_text(...)`):

```python
# ---------- growth (23/10): a mid-size shop around the same open cases ----------
# Everything above uses `rng` and is unchanged, so the 12 open cases (and the reviews already paid for)
# stay exactly as they were. Growth uses its own stream: new customers only (each existing buyer's history,
# which the reviews quote, stays the same), more orders, and more CLOSED cases from DEMO-043 on.
rng2 = random.Random(20261023)
new_customers = []
for k in range(4000):
    f, l = rng2.choice(FIRST), rng2.choice(LAST)
    city = rng2.choice(CITIES)
    new_customers.append({"payer_id": "DEMN" + "".join(rng2.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(9)),
                          "name": f"{f} {l}", "email": f"{f.lower()}.{l.lower()[:1]}{1300 + k}@example.com",
                          "address": f"{rng2.choice(STREETS)} {rng2.randint(1, 120)}, {city[1]} {city[0]}, {city[2]}"})
grown = []
d = START
while d <= TODAY:
    for _ in range(rng2.randint(40, 56)):
        c = rng2.choice(new_customers[:900]) if rng2.random() < 0.33 else rng2.choice(new_customers)
        grown.append(order(c, d, rng2.choice(pool), r=rng2))
    d += timedelta(days=1)

window_from = (TODAY - timedelta(days=90)).isoformat()
q_from, q_to = "2026-07-01", "2026-09-30"           # PayPal's previous full quarter, as ledger counts it
in_window = lambda x: x["create_time"][:10] >= window_from  # noqa: E731
orders_90 = sum(1 for o in orders if o["date"] >= window_from)
sales_q = sum(1 for o in orders if q_from <= o["date"] <= q_to)
claims_q = sum(1 for x in disputes if x["dispute_life_cycle_stage"] != "INQUIRY" and q_from <= x["create_time"][:10] <= q_to)
want_disputes = round(0.020 * orders_90) - sum(1 for x in disputes if in_window(x))
want_claims = round(0.006 * sales_q) - claims_q
templates = [p for p in closed_plan]                 # the same mix of reasons, stages and outcomes as the first 25
claims_left = max(0, want_claims)
for k in range(max(0, want_disputes)):
    o = rng2.choice([x for x in grown if x["date"] <= "2026-10-05"])
    month, reason, stage, code, why, share, msg = rng2.choice(templates)
    opened = datetime.strptime(o["date"], "%Y-%m-%d") + timedelta(days=rng2.randint(6, 18), hours=rng2.randint(8, 21))
    in_q = q_from <= opened.strftime("%Y-%m-%d") <= q_to
    if in_q and claims_left:
        stage, claims_left = "CHARGEBACK", claims_left - 1
        code, why = rng2.choice([(WON, "VALID_PROOF_OF_DELIVERY"), (BUYER, "ITEM_NOT_AS_DESCRIBED"),
                                 (BUYER, "NO_PROOF_OF_DELIVERY"), (PAYOUT, "PROTECTED_BY_PAYPAL")])
        share = 1 if code == BUYER else 0
    elif stage == "CHARGEBACK":
        stage = "INQUIRY"
    if opened.date() > TODAY - timedelta(days=3):
        opened = datetime.combine(TODAY - timedelta(days=3), opened.time())
    dispute(o, reason, opened, msg, stage=stage, outcome=(code, why) if code else None,
            refunded=round(o["amount"] * share, 2) if share else None)

# Who handled each closed case (the team signs its work). Not part of PayPal's data: the shop's own record.
handled_by = {}
for x in disputes:
    if x["status"] == "RESOLVED" and (x.get("dispute_outcome") or {}).get("outcome_code") != "CANCELED_BY_BUYER":
        amount = float(x["dispute_amount"]["value"])
        handled_by[x["dispute_id"]] = "Giulia" if amount > 30 and rng2.random() < 0.5 else rng2.choice(["Marta", "Luca", "Sara"])

# Who has each open case this morning (the film follows Marta). Unassigned cases are simply absent.
assignments = {did: {"to": who, "handoff": None} for did, who in
               [("DEMO-031", "marta"), ("DEMO-032", "marta"), ("DEMO-034", "marta"),
                ("DEMO-035", "luca"), ("DEMO-039", "luca")]}
```

**Caution on the claim count:** the `in_q and claims_left` branch only turns cases opened inside Jul–Sep into claims. If after a run `test_a_mid_size_shop…` reports a ratio under 0.005, the window ran out of Jul–Sep cases before `claims_left` reached 0: draw the claim cases first from Jul–Sep orders (a separate loop of `want_claims` iterations picking `o` with `"2026-06-25" <= o["date"] <= "2026-09-12"`), then the rest. Report which way you went.

- [ ] **Step 5: Write the new keys and say what was built.** Replace the `OUT.write_text(...)` and `print(...)` lines with:

```python
OUT.write_text(json.dumps({"_comment": "Demo shop, made-up data. Generated by demo/make_demo.py; do not edit by hand.",
                           "today": TODAY.isoformat(), "shop": SHOP, "orders": orders, "disputes": disputes,
                           "records": records, "assignments": assignments, "handled_by": handled_by},
                          indent=1, ensure_ascii=False) + "\n")
print(f"{OUT.name}: {len(orders)} orders ({orders_90} in 90 days), {len(disputes)} disputes "
      f"({sum(x['status'] == 'RESOLVED' for x in disputes)} closed, {sum(x['status'] != 'RESOLVED' for x in disputes)} open)")
```

Also update the module docstring's first line to: `"""Writes the demo shop: a made-up mid-size shop (about 2,000 orders a month, four people in customer care)`.

- [ ] **Step 6: Regenerate and run every test**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look
python3 demo/make_demo.py
for f in tests/test_*.py; do python3 $f | tail -1; done
```

Expected: the generator prints about `~8,000 orders (~6,000 in 90 days), ~140 disputes (~128 closed, 12 open)`; tests: guard 33, ledger 11, team 14, web 47, demo_shop 6 passed. If `test_web`'s demo tests (they read the demo shop) now see a team and fail, read why before changing anything: they were written when the demo had no team. Adjust the test to the new truth only when the behaviour is right; report each change.

- [ ] **Step 7: Clear the demo's runtime assignments** so the new seed is used: `rm -f .tmp/assignments-demo.json` (the store writes the seed only when the file doesn't exist).

- [ ] **Step 8: Commit**

```bash
git add demo/make_demo.py demo/shop.json tests/test_demo_shop.py
git commit -m "Demo shop grows to a mid-size shop with a customer care team; the open cases stay as reviewed"
```

(Include `tests/test_web.py` only if Step 6 required a justified change.)

---

### Task 3: Which saved reviews are still true

**Files:** none (a check; output goes in the report)

- [ ] **Step 1: List reviews the page now marks out of date**

```bash
python3 - <<'EOF'
import sys; sys.path.insert(0, ".")
from secondlook import web
for n in range(31, 43):
    did = f"DEMO-{n:03d}"
    if web._saved(did):
        print(did, web._changes(did, web._case(did)) or "current")
EOF
```

Expected: `DEMO-034 [...]` (amount changed) and every other reviewed case `current`.

- [ ] **Step 2: Find figures quoted in reviews that the new data contradicts.** For each saved review, list quoted shop-wide figures (percentages, "N claims away", order or dispute counts of the shop) and compare with the case's new `seller_records` (`web._case(did)["seller_records"]`: `buyer_history`, `buyer_history_counts`, `costs`, and `ledger.overview(...)["high_volume"]`). Per-buyer figures ("4 of 5 orders") must be unchanged.

Expected: DEMO-036's "19 claims away" no longer true; the shop rate quoted as "2%" still true. Report the full list.

- [ ] **Step 3: STOP — do not run any review.** Report the list of reviews to redo with the cost (~$0.06 each) to the controller. Claudia approves the spend; the controller runs them.

---

### Task 4: The customer card says who handled a closed case

**Files:**
- Modify: `secondlook/web.py` (`customer_page`)
- Test: `tests/test_web.py`

- [ ] **Step 1: Failing test** — append above the `if __name__` block:

```python
def test_a_closed_case_on_the_customer_card_says_who_handled_it():
    pp = DemoPayPal()
    did, who = next(iter(pp.raw["handled_by"].items()))
    buyer = next(d for d in pp.disputes() if d["dispute_id"] == did)["disputed_transactions"][0]["buyer"]["payer_id"]
    assert f"· {who}" in web.customer_page(buyer, "demo")
```

- [ ] **Step 2: Run, see it fail** — `python3 tests/test_web.py | tail -3` → AssertionError.

- [ ] **Step 3: Implement** — in `customer_page`, after `pp, disputes, orders, today = _shop(src)`, add
`handled = (pp.raw.get("handled_by") or {}) if src == "demo" else {}`, and in the row f-string change the outcome cell to
`<td>{e(x["outcome"])}{(" · " + e(handled[x["dispute_id"]])) if x["dispute_id"] in handled else ""}</td>`.

- [ ] **Step 4: Run all tests** — expected web 48 passed, others unchanged.

- [ ] **Step 5: Commit**

```bash
git add secondlook/web.py tests/test_web.py
git commit -m "Customer card: who in the team handled each closed case"
```

---

### Task 5: Look at it running, and say it in the README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Restart the server and look** (macOS `xargs` has no `-r`):

```bash
PIDS=$(lsof -tiTCP:8765 -sTCP:LISTEN); [ -n "$PIDS" ] && kill $PIDS; sleep 1
nohup python3 -m secondlook serve >/dev/null 2>&1 &
sleep 1
for p in "/?shop=demo&as=marta" "/?shop=demo&as=marta&view=mine" "/overview?shop=demo" "/d/DEMO-034?as=marta" "/d/DEMO-034?as=giulia"; do
  printf "%s %s\n" "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:8765$p")" "$p"; done
curl -s "http://127.0.0.1:8765/?shop=demo&as=marta&view=mine" | grep -o 'Mine <b>[0-9]*' 
curl -s "http://127.0.0.1:8765/overview?shop=demo" | grep -o "[0-9]* more and you cross PayPal's 1.5% line"
```

Expected: five `200`s; `Mine <b>3`; a line like `5x more and you cross PayPal's 1.5% line` with a number near 55.

- [ ] **Step 2: README** — find the demo shop's description (`grep -n -i "linen & paper\|demo shop" README.md`) and update its figures: about 2,000 orders a month (~6,000 in 90 days), dispute rate ~2%, claims ~0.6% of last quarter's sales, a customer care team of four (Giulia, manager; Marta, Luca, Sara, agents; agents send refunds up to 30 EUR). Keep "made-up data". In the Teams section, replace "the demo team arrives with the demo-shop update" with "the demo shop has a team of four: open it and switch who you are at the top".

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "README: the demo shop is a mid-size shop with a customer care team"
```

---

## After this plan
- Controller: ask Claudia to approve the re-reviews listed in Task 3 (~$0.06 each), run them, check the pages.
- Update `HANDOVER.md` and append to `LOG.md`.
- Next: plan 3 (Ticketbook helpdesk).
