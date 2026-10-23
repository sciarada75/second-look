# Film draft 6 — script (23/10, written by Claude; Claudia: "you do all"; drafts 4–6 change it after her verdicts)

Target under 3:00 (draft 4: about 2:45), about 410 spoken words at rate 160. **The rule for every scene:** it answers one question the
previous scene raised, the voice names that question or its answer, and the screen shows only what the
voice names (it lights up, the rest dims). A visible cursor makes every click. A small label in the top
corner says where we are. People are introduced before they act. No caption bar: subtitles go to
YouTube as a closed-caption file. No music. Claude is named in the Devpost text, not in the film.

Spec: `docs/specs/2026-10-23-teams-helpdesk-film3-design.md` §4. Draft 2's verdict: `HANDOVER.md`.

---

## 1. What happens? (0:00–0:10)
[Behind: Claudia's picture of a courier with a parcel, darkened and blurred. A single message card, centred,
with a "PayPal dispute · 58.00 EUR" tag. The buyer's words type out in the silence after the first line,
**not spoken**: *"Never received the apron. Refund me or I go to PayPal."*]
- A buyer has opened a PayPal dispute.
- What the shop does next, decides what it costs.

## 2. What does a dispute cost? (0:10–0:24) — one screen that builds a benchmark
[Behind: money, darkened. Three tiles land side by side and stay, each lit as named, the earlier ones
dimming slightly, each with its source underneath.]
- Answered while it's still a dispute, it costs no PayPal fee.
  **[0 EUR · settled in the dispute]** *PayPal User Agreement, 14 Sep 2026*
- Let it become a claim and lose, and the fee is fourteen euros.
  **[14 EUR · claim lost]** *PayPal fees, 7 Sep 2026*
- For a busy shop, twenty-eight. Even when the shop wins.
  **[28 EUR · busy shop, even when you win]** *PayPal fees + User Agreement*

## 2b. What does it do to a business? (0:24–0:46)
[Behind: a worried shop owner, darkened. Same structure: three tiles land and stay. Currency as the
sources give it: US$.]
- And disputes cost more than fees: a single customer-care contact, by phone, chat or email, costs about eight dollars.
  **[US$8.01 per live customer-care contact, vs US$0.10 self-service]** *Gartner, 2019*
- Every dollar lost to fraud costs a merchant about four dollars sixty.
  **[US$4.61 lost for every US$1 of fraud]** *LexisNexis True Cost of Fraud, 2025, US retail & e-commerce*
- And big merchants give up on almost half of their card chargebacks, and win only one in five of those they fight.
  **[46% of card chargebacks accepted without a fight · won 1 in 5 when fought]** *Mastercard / Datos 2025, midsize & large merchants*

## 2c. So what helps? (Second Look before the shop case: Claudia on draft 4, "it should happen before introducing the shop case")
[Paper. The Second Look mark and name, large; "an AI for PayPal disputes"; three items appear as named — Reads the
dispute and PayPal's evidence · Runs a specialist's ten checks · Drafts the answer — then **You approve**
lit in kraft on the last sentence, with "Nothing is sent before."]
- That's where Second Look comes in. It's an AI that reads every PayPal dispute and the evidence behind it, runs the checks a specialist would, and drafts the answer. Nothing is sent until you approve it.

## 3. Who are we following?
[Behind: Claudia's picture of a linen and paper shop, lightly veiled. A simple card: "Linen & Paper — a made-up shop · about 2,000 orders a month". Four initials appear as
they are named: Giulia (Customer care manager), Marta, Luca, Sara (Customer care agents, "refunds up to 30 EUR").]
- Meet Linen and Paper, a made-up shop with about two thousand orders a month.
- Marta answers customers, and can give back up to thirty euros on her own. Giulia manages the team.

## 4. Where does the case reach the team?
[**Ticketbook › Inbox** → cursor opens Dario's email → **Ticketbook › Ticket #2001**, the Second Look panel lights up.]
- Marta opens her helpdesk, a made-up one, for this film.
- Dario has written. Next to his email, Second Look shows his PayPal dispute, already reviewed. Its answer: defend with evidence.

## 5. How does she know? (1:10–1:35)
[Cursor: "Open in Second Look" → **Second Look › Case**. Light the timeline, then the evidence's delivery
line with its PayPal tag, then the buyer-history line, then "What each way out costs".]
- She opens the case. The courier recorded the apron as delivered three days after it shipped, to the address on Dario's PayPal account.
- Dario has disputed four of his five orders, and took two of them to a claim.
- And what each way out costs: refunding now, twenty-six euros out of pocket. Defending costs nothing, unless PayPal later sides with him.

## 6. What happens when she defends?
[Back to **Ticketbook › Ticket #2001**. Cursor: "Approve as Marta". The note appears; the ticket history
gains "Second Look: answer sent to PayPal by Marta".]
- She defends. No refund: the proof goes to PayPal, the reply goes to Dario, and the ticket records who sent it.

## 7. And when the buyer is right?
[**Ticketbook › Ticket #2004**, Pablo's email. Light "Your call", then the button "Pass to Giulia" and its
sentence "…over your 30.00 EUR limit. Giulia decides; nothing is sent now." Cursor clicks it.]
- Second Look also says when the buyer is right. Pablo sent a shirt back, and the refund never went out.
- It's eighty-nine euros, over Marta's limit. So the case goes to Giulia, and nothing is sent.

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
Then the end card, over a darkened, blurred clip of a seller with parcels: **Second Look** · *Sell without fear.* · claudiaonclaude.com · github.com/sciarada75/second-look]
- The AI recommends. Limits written in code have the last word. You approve.
- Second Look. Sell without fear.

---

## Claim check (every spoken claim, and what backs it)
| Spoken | Backed by |
|---|---|
| "Never received the apron. Refund me or I go to PayPal." (on screen, not spoken) | DEMO-031's buyer message (demo/shop.json) |
| no PayPal fee while it's a dispute | US User Agreement 14/09/2026: no Standard fee for an inquiry not escalated (reports/dispute-context-research.md) |
| claim lost: 14 EUR | PayPal Ireland merchant fees, 07/09/2026 |
| busy shop 28 EUR, even when it wins | same fee page; User Agreement: High Volume fee charged even when the seller wins |
| a live customer-care contact (phone, chat, email) costs about eight dollars | Gartner press release, 25 Sep 2019: "$8.01 per contact for live channels (phone, live chat, email)" vs $0.10 self-service. https://www.gartner.com/en/newsroom/press-releases/2019-09-25-gartner-says-only-9--of-customers-report-solving-thei |
| every dollar lost to fraud costs a merchant about four dollars sixty | LexisNexis Risk Solutions, True Cost of Fraud, 2 Apr 2025: US retail & e-commerce, $4.61 per $1 of fraud. https://risk.lexisnexis.com/about-us/press-room/press-release/20250402-tcof-ecommerce-and-retail |
| big merchants give up on almost half of card chargebacks, win one in five of those they fight | Mastercard/Datos 2025 via Chargeback Gurus: 46% accepted; merchants won 20% of those fought; survey of 840 midsize and large merchants. Said as *card chargebacks* |
| made-up shop, about 2,000 orders a month | demo/shop.json: 6,003 orders in 90 days; "made-up data" label on every page |
| Marta can give back up to 30 EUR; Giulia manages | demo team: agent `refund_up_to` 30.0; manager no role cap |
| a made-up helpdesk | Ticketbook header and footer: "a made-up helpdesk, not a real product" |
| already reviewed; answer: defend with evidence | .tmp/reviews/DEMO-031.json: DEFEND, 85% |
| delivered three days after it shipped, to the address on his PayPal account | DEMO-031 tracking: shipped 10 Oct, delivered 13 Oct, `delivered_to_paypal_address: true` |
| disputed four of five orders, took two to a claim | evidence: "4 disputes in 5 orders … Took 2 of 3 earlier disputes … to a PayPal claim" |
| refunding now 26 EUR out of pocket | DEMO-031 costs: refund_now.out_of_pocket 26.22 |
| defending costs nothing, unless PayPal later sides with him | no PayPal fee at the inquiry stage (User Agreement 14/09/2026); DEMO-031 costs: claim_lost.out_of_pocket 40.22 (refund + 14 EUR fee), visible in the lit costs block — the only loss path is a lost claim |
| she defends; no refund | DEMO-031 approve DEFEND = evidence + message (`execute`): no money moves |
| proof goes to PayPal, reply to Dario, ticket records who sent it | approve DEFEND = provide evidence + message (`execute`); `answer.sent` notification with `by` → Ticketbook history. Demo: logged, not sent (label on screen) |
| Pablo sent a shirt back, refund never went out, he's right | DEMO-034 record (return delivered 8 Oct, refund_issued false); review: AI refund 95%, checks favour the buyer |
| 89 EUR over Marta's limit; goes to Giulia; nothing is sent | `page_offer` → pass; approve → 202 "Nothing was sent." |
| Giulia sees Marta's note and reply, approves | case page for the person a handoff waits for: note + pre-filled reply + "Approve: refund in full (89.00 EUR)" |
| what the open cases could cost; how far from the busy-shop line | Overview: exposure section; meter 37/6,112 = 0.61% vs 1.5% |
| runs on PayPal's sandbox; one-person shop; real dispute; reply to the buyer, tracking to PayPal as proof | PP-R-UCT-10193281: reply sent 18/10, evidence (tracking LC1810260042) submitted 19/10; policy.json has no team |
| an AI that reads every PayPal dispute and the evidence behind it, runs a specialist's checks, drafts the answer | `evidence.py` gathers the dispute and PayPal's own records (order, tracking, buyer history) with their sources; `judge.py` runs the ten `CHECKS` and drafts the reply; `guard.py` applies the seller's limits after it |
| nothing is sent until you approve it (s2h); you approve (s10a) | every send goes through `web.approve`, which needs a named person in the team (`may_approve` + `page_offer`); demo actions are logged, never sent |
| limits in code have the last word | `guard.py` runs after the AI and can only make the answer more careful |

## Not said, on purpose
- No case count or score (decision 17/10: the eval score is quoted only in the README, re-measured).
- No "AI decides": it recommends.
- No claim about how many sellers lose money: no figure exists for PayPal inquiries or small sellers.
- No real brand on screen: Ticketbook is made up; the courier is "Local courier"; PayPal's own screens are not shown (Open 4).
