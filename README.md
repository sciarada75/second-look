# Second Look

**A second look at a PayPal dispute before you refund.** For one-person online shops.

A buyer opens a dispute: "never arrived", "not as described", "where's my refund". The seller has
minutes between orders to answer, and the easy answer is to refund and move on. Second Look reads
the dispute and the seller's own records, recommends one action with the evidence it used, and
writes the reply. **It never moves money by itself.** The seller's limits are enforced in code,
the seller approves every action, and the quality of the recommendations is measured, not claimed.

Built for the [PayPal AI Hackathon 2026](https://paypalaihackathon.devpost.com/). Sandbox only.

## How it works

```
PayPal Disputes API ──► judge (Claude) ──► guard (code, seller's policy) ──► seller approves ──► PayPal Disputes API
     the case            recommends            can only make it safer          one tap            provide-evidence /
   + seller records      + reasons             never less safe                                    accept-claim / make-offer
```

- **Judge** (`secondlook/judge.py`): Claude reads the buyer's messages, the tracking, the listing,
  the photos list, the buyer's history, and recommends `DEFEND`, `REFUND`, `PARTIAL_REFUND`,
  `REPLACE` or `ASK_SELLER`, with a confidence, the evidence cited and a draft reply in the
  buyer's language. A `rules` backend is the baseline: what a naive automation would do.
- **Guard** (`secondlook/guard.py`): the seller's `policy.json`, enforced in plain code. A
  confidence bar for anything that gives money back; an auto-refund cap; an "always ask me above
  X" line; "defend when tracking shows delivery to the PayPal address"; and buyer text that tries
  to instruct the assistant is routed to a human. The guard can turn a recommendation into
  `ASK_SELLER` or `DEFEND`. It can never turn one into a refund.
- **PayPal** (`secondlook/paypal.py`): the Disputes API (`provide-evidence`, `accept-claim`,
  `make-offer`, `send-message`), sandbox by default, plus a mock with the same interface that
  reads `cases/` and logs actions, so everything runs without credentials.

## Try it

```bash
python3 cases/make_cases.py            # writes the 15 test disputes
python3 -m secondlook list             # disputes waiting for the seller
python3 -m secondlook review PP-D-014  # judgment + guard, nothing executed
python3 -m secondlook approve PP-D-014 # executes the recommended action (mock: logs to .tmp/)
python3 -m secondlook eval --judge rules
python3 -m secondlook eval --judge claude   # needs ANTHROPIC_API_KEY
```

Against the real sandbox: copy `.env.example` to `.env`, add your sandbox app's client ID and
secret, export them, and put the seller's records for a dispute in `records/<dispute_id>.json`.
Open test disputes by logging into the sandbox **buyer** account's Resolution Center (creating
them through the API needs a permission only PayPal can grant).

## The eval: measured, not claimed

`cases/` holds 15 disputes in the shape of PayPal's Disputes API, each with the seller's records
and a ground-truth action, decided from PayPal's Seller Protection rules (delivery to the buyer's
PayPal address defends "not received"; no tracking loses). They include a lost parcel, buyer's
remorse dressed as "not as described", a counterfeit claim with a distributor invoice, a return
the seller forgot to refund, a weight record that proves a short shipment, an Italian-language
complaint, a high-value case, a third dispute in 90 days, and a buyer message that tries to
command the assistant.

The number that matters to a seller is **unjustified refunds**: money given back when the right
answer was to defend.

| judge | correct | unjustified refunds | routed to seller |
|---|---|---|---|
| `rules` baseline | 11/15 | 0 (the guard stopped 1) | 3 |
| `claude` | *run it with a key* | | |

Run `python3 -m secondlook eval` to reproduce. Ground truth and reasons are in
`cases/make_cases.py`; disagree with one, change it, rerun.

## Honest status

- Runs end to end against the mock. The real sandbox client is written to the public API docs
  and not yet exercised against a live sandbox account.
- The model judge needs an API key. Without one the baseline runs, which is what the table shows.
- Not escrow, not arbitration, not legal advice. The assistant recommends; a human decides.

## Licence

MIT.
