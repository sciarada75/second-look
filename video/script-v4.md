# Film draft 10 — script (26/10, written by Claude for Claudia's OK; draft 9 stays in script-v3.md)

Spec: `docs/specs/2026-10-25-inquiry-system-design.md` §5 (Decisions 6 and 7). Voice: **Kokoro `af_heart`**, as
draft 9. Subtitles burned in, cue by cue. No music. Target **≈ 2:48**: draft 9 spoke 390 words in 2:39
(≈ 147 a minute), so this script keeps to **≈ 400 spoken words**.

**Updated 26/10 (Claudia: "you go with update"):** scene 5 gains earned autonomy, trimmed elsewhere.

**The rules, as in draft 9:** each scene answers one question the previous one raised; the screen shows only
what the voice names (it lights up, the rest dims); a visible cursor makes every click; people are introduced
before they act. **New in draft 10:**
- **The value flowchart** (scene 3) is the map of the film. A small copy of it replaces the place label in the
  top corner, and lights the box each later scene is in.
- **Wherever the AI acts, it is "Second Look's AI"**, on screen and in the voice. Claude is named in the Devpost
  text, not in the film.
- **Every person carries their role** on first mention (voice) and on every screen where they appear (a name
  tag): Giulia, *head of customer care*; Marta, *customer care assistant*; Sophie, Dario, Pablo, *customer*.

---

## 1. What happens? (≈ 10 s) — every channel, one morning
[Paper, a darkened shop photo behind. Three cards land one by one, each with its channel icon: **📞 Sophie
(customer) · "My tablecloth never arrived"** · **✉️ Pablo (customer) · "Where is my refund?"** ·
**PayPal dispute · Dario (customer) · 58.00 EUR**.]
- One customer calls. One writes. One goes straight to PayPal.
- What the shop does next decides what it costs.

## 2. What does it cost? (≈ 22 s) — four tiles, each with its source
[The tiles land and stay, the earlier ones dimming. Tile 1 is the PayPal fee ladder in one: **0 EUR**
answered early · **14 EUR** claim lost · **28 EUR** busy shop, even when it wins.]
- A PayPal dispute answered early costs no fee. Lost as a claim, fourteen euros. For a busy shop, twenty-eight, even when it wins.
  *PayPal fees, 7 Sep 2026 · PayPal User Agreement, 14 Sep 2026*
- Every customer-care contact costs about eight dollars.
  **[US$8.01 per live contact]** *Gartner, 2019*
- Every dollar lost to fraud costs about four dollars sixty.
  **[US$4.61 per US$1 of fraud]** *LexisNexis, True Cost of Fraud 2025*
- And big merchants give up on almost half of their card chargebacks.
  **[46% of card chargebacks accepted without a fight]** *Mastercard / Datos 2025*

## 3. So what helps? (≈ 24 s) — Second Look, and the flowchart
[The Second Look mark. Then the flowchart builds box by box as the voice names it:
**Every request** (📞 call · ✉️ email · 📝 web form · PayPal) → **Second Look** (sorts it: who, which order, which case;
its rules first, *Second Look's AI* when they can't settle it · *Second Look's AI* checks the evidence and drafts the answer · *Your limits,
in code,* have the last word) → **A person approves** (within their own limit) → **Everything updated**
(the answer, the same way it came · PayPal · the helpdesk · accounting). Under it: **I see. I manage. I know.**]
- That's where Second Look comes in. Every request, by phone, email, form or PayPal, lands in one place.
- Second Look finds its order. Second Look's AI checks the evidence and drafts the answer. Your limits, written in code, have the last word.
- A person approves, and everything is updated: the reply, PayPal, the helpdesk, the accounts.

## 4. Who are we following? (≈ 10 s)
[The shop card: "Linen & Paper — a made-up shop · about 2,000 orders a month". Name tags appear as named:
**Giulia** *head of customer care* · **Marta**, **Luca**, **Sara** *customer care assistants, refunds up to 30 EUR*.]
- Meet Linen and Paper, a made-up shop with about two thousand orders a month.
- Marta, a customer care assistant, can give back up to thirty euros. Giulia, head of customer care, decides above that.

## 5. What came in this morning? (≈ 22 s) — I see, I manage, and the routine ones
[**Second Look › Today**, signed in as Giulia. Light **I see**: the channel counts (with Ticketbook running, as captured: 1 call,
5 emails, 1 web form, 3 PayPal disputes; without it: 3 emails) beside 141 new orders, then the list with its *Second Look's AI* lines. Then **I manage**:
who has which cases, and the line **Handled by Second Look's AI: 1 — check them**, with Margot (customer) and
the button *I'd have done it differently*. Cursor opens her case: the reply "Email out · Second Look's AI, under
Giulia's setting (since 17 Oct)". Then **Your rules**: "10 of the last 10 approved as advised · On, switched on
by Giulia on 17 Oct, 09:00".]
- Giulia's morning starts here: everything that came in, every channel, beside the day's orders.
- Each request already matched to its order and checked by Second Look's AI. And who has what.
- And the routine ones? After ten approved unchanged, Giulia let Second Look's AI answer them alone. It signs what it sends, and steps back when it isn't sure.

## 6. A phone call (≈ 22 s) — Sophie's case
[Flowchart corner: *Every request* → *Second Look*. **Second Look › Case DEMO-C001**: light the call on the
timeline (📞, its length, "transcribed on this computer"), then her email under it, then the courier's line
"left with a neighbour (Bianchi, Via Saragozza 12)", then the review "Reply only". Cursor: *Approve: reply only*
as Marta, then *Close: solved before any dispute*.]
- Sophie, a customer, called Marta: her tablecloth never arrived. The call is transcribed on the shop's own computer, and her email joins it. One case.
- The courier left it with a neighbour. Marta sends the reply and closes the case: solved before any dispute.

## 7. A PayPal dispute (≈ 24 s) — Dario's case
[Flowchart corner: *Second Look*. **Ticketbook › Ticket #2001** (a made-up helpdesk): the Second Look panel,
"Defend with evidence". **Second Look › Case DEMO-031**: light the delivery line with its PayPal tag, the
buyer-history line, then "What each way out costs". Cursor: *Approve as Marta*.]
- Dario, a customer, went straight to PayPal. In Marta's helpdesk, Second Look's AI says: defend.
- It was delivered to his PayPal address, and he has disputed four of his five orders.
- Refunding now would cost twenty-six euros. Marta defends: the proof goes to PayPal.

## 8. When the customer is right (≈ 18 s) — Pablo's case
[Flowchart corner: *A person approves*. **Second Look › Case DEMO-C003**: the timeline lights ✉️ his email,
then *PayPal dispute opened*: one case, two channels. Then "Your call", "Pass to Giulia". Then as Giulia:
*Approve: refund in full (89.00 EUR)*.]
- Pablo, a customer, emailed, then opened a PayPal dispute. Still one case.
- He's right: his returned shirt was never refunded. Eighty-nine euros is over Marta's limit, so Giulia approves it.

## 9. I know (≈ 12 s) — the month
[Flowchart corner: *Everything updated*. **Second Look › Today**, **I know**: requests 64, solved before any
dispute 31, staff time (estimated), money given back, fees, what open cases could still cost, PayPal's line;
then *Export for accounting (CSV)* and **Bookbox** (a made-up bookkeeping stand-in) showing the rows it received.]
- And at the end of the month, Giulia knows: requests, how many were solved before a dispute, staff time, money back and fees.
- The accounts get every refund as it happens.

## 10. Is it real? (≈ 12 s)
[**Live: PayPal sandbox** label. The tote-bag dispute PP-R-UCT-10193281, "What's been said" lit: the reply, then
"You sent PayPal: proof of shipment". Then a card: **Refund through PayPal's refund API · 1.00 EUR of 12.00 ·
sandbox, 26 Oct 2026** with the refund id.]
- And it runs on PayPal. On PayPal's sandbox, a real dispute got its reply and proof, and Second Look refunded a payment through PayPal's own refund API.

## 11. Can I trust it? (≈ 10 s)
[The four boxes of draft 9, relabelled: **Second Look's AI recommends** → **Your limits, in code** → **A person
approves** → **PayPal and your systems**. Then the end card: **Second Look** · *Sell without fear.* ·
claudiaonclaude.com · github.com/sciarada75/second-look]
- Second Look's AI recommends. Your limits have the last word. You approve.
- Second Look. Sell without fear.

---

## Claim check (every spoken claim, and what backs it)
| Spoken | Backed by |
|---|---|
| one calls, one writes, one goes to PayPal | demo morning: Sophie's call (demo/calls/), Pablo's email (ticketbook:2004), Dario's dispute DEMO-031 |
| no fee answered early; 14 EUR claim lost; 28 EUR busy shop even when it wins | as draft 9: PayPal fees 07/09/2026, User Agreement 14/09/2026 |
| a contact costs about eight dollars | Gartner, 25 Sep 2019: $8.01 per live contact (phone, chat, email) |
| a dollar of fraud costs about four sixty | LexisNexis True Cost of Fraud, 2 Apr 2025: $4.61 per $1, US retail & e-commerce |
| big merchants give up on almost half of their card chargebacks | Mastercard/Datos 2025: 46% accepted, 840 midsize and large merchants. Said as *card chargebacks* |
| every request by phone, email, web form or PayPal lands in one place | `POST /api/requests` (email, form via Ticketbook), the call box (`file_calls`), PayPal disputes joined to their case (`link_disputes`) |
| Second Look finds its order | `sort.sort`: rules first (sender, order number); Second Look's AI only for a known sender the rules can't settle, its facts matched by code. The demo's requests are all sorted by the rules ("Sorted by Second Look's rules" on screen), so the voice gives the AI only the checks and the draft |
| checks the evidence and drafts the answer | inquiry judge (`SYSTEM_INQUIRY`) and dispute judge (`SYSTEM`): checks + draft |
| limits written in code have the last word | `guard.py` after the AI, can only make it safer (Decision 8: an exchange counts its postage once the item is back) |
| the answer goes back the way it came, to PayPal, the helpdesk and the accounts | Outbox (reply on the customer's channel, `answer.sent` to Ticketbook), PayPal actions, `post_books` to Bookbox. **Not** the orders system: Second Look only reads orders (so the spec's "orders" box became "the helpdesk") |
| made-up shop, about 2,000 orders a month; Marta up to 30 EUR; Giulia above | demo/shop.json, team roles |
| everything that came in, every channel, beside the day's orders | `/today` I see: counts by channel + 141 orders (19–20 Oct) |
| matched to its order and checked by Second Look's AI | each row's order and its review line: the shipped reviews (demo/reviews/, DEMO-C001/C002 since 26/10; disputes since 23/10) |
| who has what | `/today` I manage |
| after ten approved unchanged, Giulia let Second Look's AI answer them alone | earned autonomy (spec 2026-10-26): a kind is ready after its last 10 decisions by people were approved as advised; only the head of customer care switches it on. Demo: `inquiry · not_received · reply only`, seeded record, switched on by Giulia 17 Oct, 09:00; Margot's request (DEMO-C004, LP-90003) answered by it at the demo's first load (`demo/reviews/DEMO-C004.json`, Claude, 26/10). Built on branch autopilot (394 tests) |
| it signs what it sends, and steps back when it isn't sure | every send signed "Sent by Second Look's AI, under Giulia's setting"; steps back on confidence < 0.90, any guard stop, a rules-baseline review, a changed or assigned case (spec §3, one test each) |
| the call is transcribed on the shop's own computer | local whisper (`transcribe_calls`), when installed; otherwise the transcript shipped beside the recording, labelled. **Capture on Claudia's Mac shows whisper's words**; a judge's clone shows "transcript shipped with the demo" |
| her email joins it, one case | DEMO-C001: call 08:31 + email 08:52 |
| left with a neighbour; Marta sends the reply and closes: solved before any dispute | DEMO-C001 tracking; shipped review MESSAGE; any team member may send a reply (no money); close outcome "solved" |
| Dario: Second Look's AI says defend; delivered to his PayPal address; four of five orders disputed | DEMO-031 shipped review DEFEND; tracking `delivered_to_paypal_address`; buyer history |
| refunding now would cost twenty-six euros; the proof goes to PayPal | DEMO-031 costs refund_now 26.22; approve DEFEND = evidence (demo: logged, labelled) |
| Pablo emailed, then opened a PayPal dispute, still one case | DEMO-C003 joined to DEMO-034 (`link_disputes`) |
| returned shirt never refunded; 89 over Marta's limit; Giulia approves | DEMO-034 record + review; `page_offer` pass; Giulia approves |
| at month's end Giulia knows requests, solved before a dispute, staff time, money back, fees | `/today` I know (demo, October: 64 requests, 31 solved before any dispute, staff time est., 314.70 EUR back, 14 EUR fees) |
| the accounts get every refund as it happens | `post_books` in the background on every money event; Bookbox shows them; monthly CSV |
| a real sandbox dispute got its reply and its proof | PP-R-UCT-10193281: reply 18/10, tracking as evidence 19/10 |
| Second Look refunded a payment through PayPal's own refund API | 26/10: `refund_capture` on capture 5WA059709R6842611, 1.00 of 12.00 EUR, refund 7WT94554XS657562E COMPLETED (LOG 26/10). Called directly, not from a case page: the voice doesn't claim the page |
| Second Look's AI recommends, your limits have the last word, you approve | `guard.py` + one approval path (`approve` under `_case_lock`) |

## Not said, on purpose
- No score: the eval (16/16 disputes, 9/9 inquiries, 26/10) is in the README and the write-up, framed as a development score.
- No "AI decides": it recommends.
- No card chargebacks handled: the tile is context (what a dispute at the bank costs), and the write-up says card chargebacks are not built.
- No real brand on screen: Ticketbook and Bookbox are made up; the courier is "Local courier"; PayPal's own screens are not shown.
- No figure for how much Second Look saves: it shows the costs, it doesn't claim a saving.
