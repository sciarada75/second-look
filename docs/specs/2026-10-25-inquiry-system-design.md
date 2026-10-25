# Second Look as an inquiry system: every request, one case, one picture

Design approved section by section by Claudia, 25/10/2026, in a brainstorm with mockups (in
`paypal-ai/.superpowers/brainstorm/`, outside this repo). Deadline: Thu 12/11/2026 12:00 PST.

## Why

Claudia, 25/10: a complaint about a purchase goes to the shop first; people go to the bank only for
fraud. If Second Look handles PayPal disputes only, a real shop needs a second, parallel system for
everything else, and that isn't solid. Second Look must take **every customer request** — email, web
form, phone call, PayPal dispute — and give the business relief: *"everything is here and clear now.
I see, I manage, I know."* The hidden costs (staff hours, fees, write-offs nobody records) are the
point: see the Inspiration text in `paypal-ai/devpost/write-up.md`.

PayPal stays central: PayPal disputes, the PayPal claim line, PayPal refunds, the live sandbox. What's
new is that the shop catches problems **before** they become PayPal disputes, for every customer.

## Decisions (Claudia, 25/10)

1. Option b, widened into an inquiry system. Card chargebacks are **not** built: "what's next".
2. **Approach A: Second Look is the hub.** It holds every case. Agents keep working in their
   helpdesk (Ticketbook); orders, courier, phone system, PayPal and accounting connect through its API.
   Rejected: B (the helpdesk holds the cases — no full picture), C (Second Look replaces the
   helpdesk — the risky switch the write-up warns against).
3. **Phone: a recorded call, transcribed** on the shop's own computer (local whisper). The demo call is
   made up, voiced by Kokoro with two voices; its transcript ships with the demo for judges.
4. **Systems: all six** — orders, helpdesk, phone system, PayPal, courier, accounting.
5. **Accounting gets the facts, never the credit note**: order and invoice number, amount refunded,
   fees, item back or lost, date, who approved, channel. The credit note is a legal document the
   accounting system or the accountant makes.
6. **Film draft 10**, with a value flowchart; wherever the AI appears it is **"Second Look's AI"**.
   A small copy of the flowchart replaces the place label as the "where am I" guide.
7. **Every name carries its role**, on first mention and on every screen where the person appears:
   Giulia, *head of customer care*; Marta, Luca, Sara, *customer care assistants*; Dario, Pablo,
   Sophie, Lena, *customers*. (Roles renamed from "Customer care manager / agent". The tablecloth
   customer is **Sophie**, not Anna: Anna sounded like the staff's Marta.)

## 1. One case, every channel

- A **case** = one customer + one order + one problem. Every contact about it, through any channel,
  joins the same case. A PayPal dispute opened later on the same order joins the case, and the shop's
  earlier answers count as evidence that it responded.
- A case's **timeline** lists every entry with its time, **channel** (📞 call, ✉️ email, 📝 web form,
  PayPal), **direction** (in / out), and who approved what went out. Second Look's AI entries are
  labelled as such.
- A case's **stage**: inquiry → PayPal dispute → PayPal claim. Closed with an outcome: solved before a
  dispute, refunded, replaced, defended (won/lost), withdrawn.
- A case's **cost so far**: contacts; staff time = minutes × the shop's hourly cost (set in the shop's
  rules; a call's minutes are its length, a written reply's minutes a default the shop sets), always
  labelled *estimated*; fees; money moved.

## 2. The morning screen: "I see, I manage, I know"

The first page of a shop (`/today`), three blocks:
- **I see**: everything that came in since yesterday, every channel, one list; each request matched to
  its order and already checked by Second Look's AI; nearest deadline first. New orders are counted
  beside it, so problems read against sales (demo morning: 8 new orders, 1 call, 2 emails, 1 web form,
  3 PayPal disputes).
- **I manage**: who has which cases, what's unassigned, what waits for the head of customer care.
- **I know**: this month across all channels: requests, solved before any dispute, staff time (est.),
  money given back, fees, what open cases could still cost, PayPal's claim line (the existing meter),
  and the export for accounting.

The existing Disputes list and Overview stay, reached from here; the Overview gains the all-channel
figures.

## 3. Connections, and Second Look's AI

**In:**
- **Email and web form** arrive in the helpdesk (Ticketbook), which posts each one to Second Look
  (`POST /api/requests`; the same endpoint any system can use). Ticketbook gains a web-form source.
- **Phone system**: a made-up "call box" — a folder of call recordings (`demo/calls/`). Second Look
  transcribes a new recording locally if whisper is installed; otherwise it uses the transcript that
  ships beside it, labelled "transcript shipped with the demo".
- **PayPal disputes**: read from PayPal's API, as today.

**Second Look's AI, two jobs (both labelled on screen):**
1. **Sort**: read the request — who, which order, what problem — and join it to an open case or open a
   new one. Deterministic first (sender address, order number in the text); the AI only for what that
   can't settle.
2. **Judge**: gather evidence, run the checks, recommend one action, draft the reply. Rulebook by stage:
   **inquiry** = the shop's own terms + the evidence (no legal or card-network rules claimed);
   **PayPal dispute/claim** = PayPal's rules, as today. The ten checks adapt: the address that counts in
   an inquiry is the order's delivery address.

**Code, not AI:** the guard (limits), people and roles, costs, timeline, and the rule that a person
approves everything that goes out. Unchanged.

**Out:**
- The answer goes back by the channel it came from: email/form → through the helpdesk; call → an email
  or a call-back note; PayPal → PayPal's API (message, evidence, refund).
- A refund on an inquiry follows the payment method: **PayPal-paid → PayPal's refund API** (Payments
  v2, captures/{id}/refund; demo: logged; live sandbox: tried once on a sandbox payment, only with
  Claudia's OK, as for any live action), **card or bank →
  handed to the shop's payment provider** (logged; not built).
- **Accounting**: every money event goes live to a made-up bookkeeping stand-in (one page showing what
  it received) and into a monthly CSV export.

**Stand-ins (made up, labelled, small):** orders and courier are data behind the API (order, items,
address, paid with: card / PayPal / bank; tracking: shipped, delivered, where, to whom). Only the
helpdesk has a full screen (it already does).

**Judges without keys:** the demo's sorting and judging results ship in the repo, labelled, as the
demo reviews do now (`demo/reviews/`). With no key, new requests fall back to the rules baseline,
labelled.

## 4. Demo data

The demo shop's generator gains inquiries without moving its existing random streams (open cases and
paid reviews stay valid): a third stream adds orders paid by card or bank, and requests by email, form
and phone linked to orders. Named demo cases:
- **Sophie** (customer), tablecloth, paid by card, **calls** then emails: delivered, left with a
  neighbour → reply, solved before any dispute.
- **Pablo** (customer), shirt returned, never refunded, 89 EUR: he **emailed and opened a PayPal
  dispute** (DEMO-034) — one case, two channels, the demonstration of joining → over Marta's limit →
  Giulia approves.
- **Lena** (customer), wrong size, **web form** → exchange within the 14-day terms.
- **Dario** (customer), PayPal dispute, defend (as today).
- Past months filled so "I know" has real figures.

## 5. Film draft 10 (≈ 2:49)

| # | Scene | | ≈ s |
|---|---|---|---|
| 1 | A customer writes, another calls, a third goes to PayPal | changed | 10 |
| 2 | What it costs: 4 tiles (PayPal fee ladder as one, contact cost, fraud, chargebacks) | shorter | 22 |
| 3 | Second Look comes in + **the value flowchart** | new | 22 |
| 4 | The shop and the team (names with roles) | kept | 10 |
| 5 | **The morning screen** | new | 10 |
| 6 | **Sophie's call**: recording → transcript → sorted → checked → reply → solved | new | 20 |
| 7 | Dario's PayPal dispute: evidence, costs, Marta defends | shorter | 25 |
| 8 | Pablo's email: he's right, over Marta's limit → Giulia approves | shorter | 18 |
| 9 | **I know**: the month in money and hours + export for accounting | changed | 10 |
| 10 | It runs on PayPal: the live sandbox | kept | 12 |
| 11 | "Second Look's AI recommends. Your limits have the last word. You approve." + end card | kept | 10 |

The flowchart: every request (📞 ✉️ 📝 PayPal) → Second Look (Second Look's AI sorts it; Second Look's
AI checks the evidence and drafts the answer; your limits, in code, have the last word) → a person
approves → everything updated (answer by the same channel, PayPal, orders, accounting) → "I see. I
manage. I know." Its small copy lights the current box in each scene. Every person on screen gets a
name tag with their role. Claude stays named in the write-up, not on screen. Voice: Kokoro af_heart.
Subtitles burned in.

## Build order (each step ships complete and true; stop anywhere and what exists is honest)

One implementation plan per step, as with the team features (spec 23/10 → four plans).

1. **Cases + channels + sort + inquiry judge + case page** (timeline, channel, costs) — the core.
2. **Morning screen** + Overview's all-channel figures; roles renamed.
3. **Phone** (Kokoro call, local transcription, shipped transcript), **orders/courier stand-ins**,
   **accounting** (live stand-in + CSV), PayPal refund API for PayPal-paid inquiries.
4. **Eval**: add inquiry cases with known answers (at least 4: delivered/left with neighbour, refund
   owed, exchange in terms, premature); re-run the paid eval (~$1, Claudia's OK) once, on everything.
5. **Film draft 10**, README, write-up, YouTube, submit. Target: build done 04/11, film 07/11,
   submitted by 10/11.

## Testing

Plain-script tests as today (`tests/test_*.py`), no packages. New: case joining (call + email + later
PayPal dispute on one order → one case), sort's deterministic path, inquiry judge's rules baseline,
guard unchanged on inquiries, costs (estimated staff time), channel-matched replies, accounting events
and CSV, shipped transcript/sort fallback with no whisper/no key, demo generator determinism (existing
streams untouched). A judge-style fresh-clone run before each merge.

## Not built (say so)

Card chargebacks and card-network rules; real email/phone/accounting integrations (stand-ins show the
seam); legal rules for inquiries; credit notes; a held-out eval set.
