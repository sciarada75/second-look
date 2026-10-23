# Film draft 3 — script (23/10, written by Claude; Claudia: "you do all")

Target about 2:50, about 390 spoken words. **The rule for every scene:** it answers one question the
previous scene raised, the voice names that question or its answer, and the screen shows only what the
voice names (it lights up, the rest dims). A visible cursor makes every click. A small label in the top
corner says where we are. People are introduced before they act. No caption bar: subtitles go to
YouTube as a closed-caption file. No music. Claude is named in the Devpost text, not in the film.

Spec: `docs/specs/2026-10-23-teams-helpdesk-film3-design.md` §4. Draft 2's verdict: `HANDOVER.md`.

---

## 1. What happens? (0:00–0:12)
[A single message card, centred: *"Never received the apron. Refund me or I go to PayPal."*, a small
"PayPal dispute · 58.00 EUR" tag under it.]
- A buyer opens a PayPal dispute. Never received the apron. Refund me, or I go to PayPal.
- What the shop does next decides what it costs.

## 2. Why does it matter? (0:12–0:40) — take stock
[Four figures, one at a time, large, each with its source in small type underneath. Nothing else on screen.]
- Answered while it's still a dispute, it costs no PayPal fee.
  **[0 EUR]** *PayPal User Agreement, 14 Sep 2026*
- Let it become a claim and lose, and the fee is fourteen euros.
  **[14 EUR]** *PayPal fees, 7 Sep 2026*
- For a busy shop, twenty-eight. Even when the shop wins.
  **[28 EUR, even when you win]** *PayPal fees + User Agreement*
- And even big merchants give up on almost half of their card chargebacks without a fight.
  **[46%]** *Mastercard / Datos, 2025: card chargebacks, mid-size and large merchants*

## 3. Who are we following? (0:40–0:52)
[A simple card: "Linen & Paper — a made-up shop · about 2,000 orders a month". Four initials appear as
they are named: Giulia (Customer care manager), Marta, Luca, Sara (Customer care agents, "refunds up to 30 EUR").]
- Meet Linen and Paper, a made-up shop with about two thousand orders a month.
- Marta answers customers, and can give back up to thirty euros on her own. Giulia manages the team.

## 4. Where does the case reach the team? (0:52–1:10)
[**Ticketbook › Inbox** → cursor opens Dario's email → **Ticketbook › Ticket #2001**, the Second Look panel lights up.]
- Nine in the morning. Marta opens her helpdesk, a made-up one, for this film.
- Dario has written. Next to his email, Second Look shows his PayPal dispute, already reviewed. Its answer: defend with evidence.

## 5. How does she know? (1:10–1:35)
[Cursor: "Open in Second Look" → **Second Look › Case**. Light the timeline, then the evidence's delivery
line with its PayPal tag, then the buyer-history line, then "What each way out costs".]
- She opens the case. The courier recorded the apron as delivered three days after it shipped, to the address on Dario's PayPal account.
- Dario has disputed four of his five orders, and took two of them to a claim.
- And she sees what each way out costs: refunding now, twenty-six euros out of pocket; losing a claim, forty.

## 6. What happens when she approves? (1:35–1:47)
[Back to **Ticketbook › Ticket #2001**. Cursor: "Approve as Marta". The note appears; the ticket history
gains "Second Look: answer sent to PayPal by Marta".]
- She approves. The proof goes to PayPal, the reply goes to Dario, and the ticket records who sent it.

## 7. What if it's more than she may give? (1:47–2:02)
[**Ticketbook › Ticket #2004**, Pablo's email. Light "Your call", then the button "Pass to Giulia" and its
sentence "…over your 30.00 EUR limit. Giulia decides; nothing is sent now." Cursor clicks it.]
- Next, Pablo. He sent a shirt back, and the refund never went out. He's right.
- But it's eighty-nine euros, over Marta's limit. So the case goes to Giulia, and nothing is sent.

## 8. Who decides, and what's the big picture? (2:02–2:22)
[**Second Look › Disputes**, signed in as Giulia: the case marked "passed by Marta" → the case page:
"Marta suggests…", button "Approve: refund in full (89.00 EUR)", cursor clicks. Then **Second Look ›
Overview**: what the open cases could cost; the meter "0.6% claims · PayPal's line 1.5%".]
- Giulia sees Marta's note and her reply, and approves the refund.
- Then the overview: what the open cases could cost, and how far the shop is from PayPal's busy-shop line.

## 9. Is it real? (2:22–2:36)
[**Live: PayPal sandbox** label. Second Look on a one-person shop: the tote-bag dispute PP-R-UCT-10193281,
"What's been said" lit: the reply, then "You sent PayPal: proof of shipment".]
- And it runs on PayPal. This is PayPal's sandbox: a one-person shop, a real dispute. The reply went to the buyer, and the tracking went to PayPal as proof.

## 10. Can I trust it? (2:36–2:50)
[Four boxes build left to right: The AI recommends → Your limits, in code → A person approves → PayPal.
Then the end card: **Second Look** · *Sell without fear.* · claudiaonclaude.com · github.com/sciarada75/second-look]
- The AI recommends. Limits written in code have the last word, and can only make it more careful. Nothing moves until a person approves.
- Second Look. Sell without fear.

---

## Claim check (every spoken claim, and what backs it)
| Spoken | Backed by |
|---|---|
| "Never received the apron. Refund me or I go to PayPal." | DEMO-031's buyer message (demo/shop.json) |
| no PayPal fee while it's a dispute | US User Agreement 14/09/2026: no Standard fee for an inquiry not escalated (reports/dispute-context-research.md) |
| claim lost: 14 EUR | PayPal Ireland merchant fees, 07/09/2026 |
| busy shop 28 EUR, even when it wins | same fee page; User Agreement: High Volume fee charged even when the seller wins |
| big merchants give up on almost half of card chargebacks | Mastercard/Datos 2025 via Chargeback Gurus: 46% accepted; survey of 840 midsize and large merchants. Said as *card chargebacks* |
| made-up shop, about 2,000 orders a month | demo/shop.json: 6,003 orders in 90 days; "made-up data" label on every page |
| Marta can give back up to 30 EUR; Giulia manages | demo team: agent `refund_up_to` 30.0; manager no role cap |
| a made-up helpdesk | Ticketbook header and footer: "a made-up helpdesk, not a real product" |
| already reviewed; answer: defend with evidence | .tmp/reviews/DEMO-031.json: DEFEND, 85% |
| delivered three days after it shipped, to the address on his PayPal account | DEMO-031 tracking: shipped 10 Oct, delivered 13 Oct, `delivered_to_paypal_address: true` |
| disputed four of five orders, took two to a claim | evidence: "4 disputes in 5 orders … Took 2 of 3 earlier disputes … to a PayPal claim" |
| refunding now 26 EUR out of pocket; losing a claim 40 | DEMO-031 costs: refund_now.out_of_pocket 26.22; claim_lost.out_of_pocket 40.22 |
| proof goes to PayPal, reply to Dario, ticket records who sent it | approve DEFEND = provide evidence + message (`execute`); `answer.sent` notification with `by` → Ticketbook history. Demo: logged, not sent (label on screen) |
| Pablo sent a shirt back, refund never went out, he's right | DEMO-034 record (return delivered 8 Oct, refund_issued false); review: AI refund 95%, checks favour the buyer |
| 89 EUR over Marta's limit; goes to Giulia; nothing is sent | `page_offer` → pass; approve → 202 "Nothing was sent." |
| Giulia sees Marta's note and reply, approves | case page for the person a handoff waits for: note + pre-filled reply + "Approve: refund in full (89.00 EUR)" |
| what the open cases could cost; how far from the busy-shop line | Overview: exposure section; meter 37/6,112 = 0.61% vs 1.5% |
| runs on PayPal's sandbox; one-person shop; real dispute; reply to the buyer, tracking to PayPal as proof | PP-R-UCT-10193281: reply sent 18/10, evidence (tracking LC1810260042) submitted 19/10; policy.json has no team |
| limits in code have the last word, only more careful; nothing moves until a person approves | guard.py (only safer); `may_approve` + `page_offer`; every send goes through `web.approve` |

## Not said, on purpose
- No case count or score (decision 17/10: the eval score is quoted only in the README, re-measured).
- No "AI decides": it recommends.
- No claim about how many sellers lose money: no figure exists for PayPal inquiries or small sellers.
- No real brand on screen: Ticketbook is made up; the courier is "Local courier"; PayPal's own screens are not shown (Open 4).
