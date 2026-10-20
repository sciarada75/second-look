# Film draft 2 — script for Claudia's review (20/10)

Target under 2:50. Each line is spoken; [brackets] are pictures. Every claim is checked in the
table at the bottom before rendering. Edit freely: your words beat mine.

## 1. The moment (0:00–0:20)
[plain box at a door, daylight · seller writing at her desk among boxes]
- A buyer opens a PayPal dispute. *Never got my parcel.*
- What the seller does in the next few days decides what it costs.

## 2. What it costs (0:20–0:45)
[three cards build one by one; money changing hands in a side panel]
- Refund, and the money goes back, the item is gone, and PayPal keeps its fee.
- Settle it while it's still a dispute, and PayPal charges nothing.
- Let it become a claim and lose, and PayPal adds a fee. Fourteen euros. For a busy shop,
  twenty-eight, even when it wins.

## 3. How it's handled today (0:45–1:05)
[worried owner at a laptop · a customer-service team · a card with the gap]
- A one-person shop does this alone, in PayPal's own dashboard, which PayPal calls the option for a
  small volume of disputes. Bigger shops put someone on it.
- The tools that exist are built for card chargebacks, and many take a quarter of what they win back.
- Even mid-size and large merchants give up on almost half of their card chargebacks without a fight.

## 4. Second Look (1:05–1:20)
[title card · the case page: evidence with PayPal tags, "What each way out costs"]
- Second Look works inside those first days, while a dispute is still cheap. It pulls the evidence
  from PayPal, runs the ten checks a specialist would, and shows what each way out would cost,
  before you choose.

## 5. Live on PayPal (1:20–1:45)
[the live sandbox takes: tote bag, reply, then the tracking sent as proof]
- Here it is live, on PayPal's sandbox. Opened four minutes after paying: a calm reply, no refund.
- When the parcel ships, it takes a fresh look and sends the tracking to PayPal as proof.

## 6. A busier shop (1:45–2:25)
[demo shop, label on screen: inbox · Dario's case · customer card · overview · high-volume line]
- Now a busier shop: two people, seventeen hundred orders in ninety days. Made-up data, same code.
- This buyer took two of his three earlier disputes to a claim. So it doesn't just reply: the
  parcel was delivered to his PayPal address, and that proof goes to PayPal now.
- It tells you when you're wrong, too. A return arrived, and the refund never went out: the buyer
  is right. That refund is above your limit, so it comes back to you.
- A pulled thread on a napkin: first, a photo. A parcel lost for two weeks: refund it, the buyer is right.
- At a glance: how every case ended, what you kept, what you paid, and for every open case, what
  PayPal does if nobody answers.
- When a customer orders or calls, your customer database can show the same record.

## 7. The guard and you (2:25–2:40)
[flow: AI → your limits in code → you approve → PayPal]
- Your limits, written in code, have the last word. They can make an answer more careful, never
  more generous. And nothing moves until you approve.

## 8. End (2:40–2:50)
[end card]
- A few cents a dispute. Second Look. Sell without fear.
- Card: **Second Look** · *Sell without fear.* · claudiaonclaude.com · github.com/sciarada75/second-look

## Claim check
| Spoken | Backed by |
|---|---|
| no PayPal fee while it's a dispute | US User Agreement 14/09/2026: no Standard fee for inquiries not escalated or resolved directly |
| claim lost: 14 EUR; busy shop 28 EUR, even when it wins | IE fee page 07/09/2026; User Agreement: High Volume fee charged regardless of outcome |
| refund: PayPal keeps its fee | US fee page 01/10/2026: "fees … are not returned" |
| PayPal calls its dashboard the option for a small volume | developer.paypal.com "Choose an integration option", 10/07/2026 |
| tools built for card chargebacks; many take a quarter | Chargeflow, Redo pricing pages (25% of recovered); ChargePay is flat: hence "many", not "all" |
| mid-size and large merchants give up on almost half of card chargebacks | Mastercard/Datos 2025 via Chargeback Gurus: 46% accepted, mid-size and large merchants |
| opened four minutes after paying | PP-R-UCT-10193281: paid 18:05:58, opened 18:09:31 |
| two people, ~1,700 orders in 90 days, made-up | demo/shop.json (1,730 orders in the window), label on every page |
| took two of three earlier disputes to a claim; delivered to his PayPal address | DEMO-026/027/028; DEMO-031 tracking DELIVERED to the PayPal address; review = DEFEND |
| what PayPal does if nobody answers | ledger.if_nobody_answers: HELP1083 (10 days), Purchase Protection (20 days), API due-date rules |
| a few cents a dispute | ~$0.05 measured 17/10; inputs grew (costs, history), so "a few cents", not a number |
