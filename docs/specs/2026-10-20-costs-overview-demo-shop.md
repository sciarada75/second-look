# Costs, buyer record, overview, customer card, demo shop — design (2026-10-20)

Why: Claudia's review of film draft 1. The film showed a feature, not a problem: no sizing, no
comparison with how disputes are handled today, no recap, three cases (two alike). Research
(`../reports/dispute-context-research.md`, outside the repo) found the value: **the inquiry is the
cheap moment** — no PayPal dispute fee while it stays an inquiry, messages and offers exist only
then, the seller has 10 days. Claudia: "this math must drop in our system".

Every figure below is PayPal's (fee pages and User Agreement, Sep–Oct 2026) unless marked.

## 1. What each choice costs — `secondlook/costs.py` (pure code, no model)
Per dispute, three outcomes in the dispute's currency:
- **Refund now:** the amount goes back; the seller is out of pocket for the item, the postage and
  PayPal's fee on the payment (not returned on a refund). Fee read from Transaction Search
  `fee_amount` (verified on the sandbox: −1.78 on 42.00 EUR).
- **Settled in the dispute** (reply, evidence, buyer withdraws or lets it lapse): dispute fee 0.
- **It becomes a claim:** lost → refund + out of pocket + dispute fee (EUR 14 / USD 15; EUR 28 /
  USD 30 for high-volume sellers); won → 0, or 28 if high-volume (charged even when you win).
Item and postage costs are the seller's own (`shop.json` → `costs`); when missing, the screen says
"set your cost" instead of guessing. No probabilities are invented: the buyer's own record (2)
says how likely the claim branch is.

## 2. The buyer's escalation record — `evidence._buyer_history`
Adds, for this buyer's earlier disputes with the shop: how many went past the inquiry (stage
CHARGEBACK / PRE_ARBITRATION / ARBITRATION, or channel EXTERNAL) and how each ended; plus the
shop's own escalation rate as the base rate. One neutral sentence, e.g. "This buyer took 2 of 3
earlier disputes to a PayPal claim. Your shop: 1 in 8." Passed to the judge with the costs.

## 3. High-volume watch — `costs.high_volume`
PayPal: dispute ratio ≥ 1.5 % **and** > 100 sales in the previous three full calendar months →
high-volume fee on every claim. Ratio = escalated claims + card chargebacks / sales (unauthorised
claims excluded). Shown on the overview: ratio, threshold, "N more claims and every claim costs 28".

## 4. Overview page — `/overview`
Cases handled (90 days) by how they ended, from `dispute_outcome` + `outcome_reason` + stage:
won · buyer withdrew · lapsed (buyer never escalated: PayPal never says who "wins" this, so it is
its own row) · refunded by you · lost at claim · lost for no reply. Money kept, money refunded,
dispute fees paid, settled before a claim (count). Open: waiting on you (days left of the 10),
waiting on the buyer (days until the 20-day close). Each open case says what happens if nobody
answers, in PayPal's words.

## 5. Customer card — `/customer/<payer_id>` and `GET /api/customers/<payer_id or email>`
Orders, disputes, escalations, outcomes, refunded total, against the shop's base rate. The JSON
endpoint is the integration: a CRM or helpdesk queries it when the customer orders or calls.
Local only (127.0.0.1), like the rest of the app.

## 6. Demo shop — `demo/make_demo.py` → `demo/shop.json`
A made-up two-person shop ("Linen & Paper"): ~1,100 orders in 90 days, 40 disputes — 30 closed with
outcomes, 10 open and varied (delivered-but-"not received", wrong colour, partial-refund demand,
refund never processed — the seller's own fault —, an Italian buyer, a habitual escalator, an
order above the limits, a fit complaint, a message that gives orders, a lost parcel). Generated
by a seeded script so it can be rebuilt. **Labelled "Demo shop — made-up data" on every page.**
The live sandbox disputes stay the proof that it runs on PayPal. Only the 10 open cases get an
AI review (~$0.50).

## Sizes it serves
Solo: knowledge and time. Small/mid (2–10 people, hundreds to thousands of orders): volume, the
high-volume threshold, the customer record in their CRM. Large merchants with teams and
chargeback vendors: not the target.

## Tests
costs (each branch, missing cost, high-volume), threshold arithmetic, outcome bucketing,
escalation count, customer card, API by payer_id and email. Eval re-run after (judge input changed).
