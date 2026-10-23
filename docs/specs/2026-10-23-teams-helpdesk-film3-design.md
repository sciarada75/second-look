# Teams, a partner helpdesk, and film draft 3 — design

Approved by Claudia part by part on 2026-10-22/23. Why it exists: her verdict on film draft 2
("still do not like it") and her decision that Second Look is for shops of any size, with the
build behind that claim.

**The governing rule, in her words:** a judge or a business owner must follow an easy mental
path. If they get lost in the steps, or in where they are, they lose the understanding and the
interest. Every choice below is checked against it: one shop, one morning, one thread of cases,
and the viewer always knows where they are and why the next step follows.

## 1. Team features (Second Look)

**Roles are the shop's own data**, in `policy.json` (live) and the demo shop's config:

```json
"team": {
  "roles": {
    "Customer care agent":   {"refund_up_to": 30.0},
    "Customer care manager": {"refund_up_to": null}
  },
  "people": [
    {"id": "giulia", "name": "Giulia", "role": "Customer care manager"},
    {"id": "marta",  "name": "Marta",  "role": "Customer care agent"}
  ]
}
```

- `refund_up_to: null` means the role sets no cap of its own. The shop's amount limits
  (auto-refund cap 50, always-ask line 200) decide what the **AI** may recommend unasked; above
  them a person decides, and a person with no role cap is that person. A role can only be
  **stricter** than what the guard allows, never looser (`guard.person_limit`, tested).
- A shop with no `team` block is a **team of one** with full rights: nothing extra on screen. The
  live sandbox shop stays this way.

**Who you are.** Header: "You are: Marta ▾". Remembered in a cookie `sl_person`, like `sl_shop`.
No passwords: the README says plainly this is a prototype and real sign-in is not built.

**Cases belong to someone.** Each open case has `assigned_to` (or none). Saved beside the review
(`records/assignments.json`, gitignored: the shop's data; the demo shop seeds its own). The
dispute list gets a filter **Mine · Unassigned · Everyone**; an unassigned case has *Take it*.

**Handoff.** When a person approves an action above their limit, **nothing goes to PayPal**. The
case is assigned to the first person whose limit covers it (the manager), with a note:
"Marta suggests: refund 89.00 EUR" and the draft. The manager approves with one click.

**The manager may approve a refund the limits held back — narrowly.** Today, when the AI's
refund is above the shop's auto-refund cap, the guard turns it into "Your call" and the page
only lets the seller ask a question or act in PayPal. New: a person whose limit covers the amount
may approve the AI's original money action **only when every reason the guard stopped it is an
amount limit** (auto-refund cap or always-ask line). Never when the guard stopped it for hidden
instructions, inconsistent evidence, low confidence, a repeat escalator, or PayPal's allowed
actions. `guard.may_approve(recommended, chosen, drafted_for, person, stop_reasons)` — tested on
each of those reasons.

**Every action is signed.** "Sent by Marta, 09:14" on the case and in "What's been said"; `by` in
the API's case JSON and in the `answer.sent` notification. A handoff is signed too.

**The API needs a name.** `POST /api/disputes/<id>/approve` takes `by` (a person id). In a team
shop, missing or unknown `by` → 400, nothing sent. Same limits, out-of-date check and send-once as
the page (`web.approve` stays the single path).

**Tests:** a role can never be looser than the shop; over-limit approval sends nothing and hands
off to the right person; manager approval of a held refund works for amount limits only and is
refused for each other stop reason; API approve without `by` is refused in a team shop; every
action records who; a team of one behaves exactly as today (existing tests still pass).

## 2. The made-up helpdesk: "Ticketbook"

A separate small app in `helpdesk/` (Python standard library, like Second Look), port **8766**,
with its own name, colours and type so viewers see *another company's tool*. Header label:
"Ticketbook — a made-up helpdesk". No real brand is imitated.

- **Inbox:** made-up buyer emails for Linen & Paper (`helpdesk/tickets.json`, generated with the
  demo shop, matched to its buyers by email address).
- **Ticket page:** the email thread; on the side, a **Second Look panel** drawn by Ticketbook
  from Second Look's JSON (`GET /api/customers/<email>`, `GET /api/disputes/<id>`) — status,
  recommendation, the checks that matter, costs, drafted reply, "Open in Second Look". Drawn from
  JSON, not an iframe, so it proves the API the way a real integration would use it.
- **Approve as Marta:** Ticketbook calls `POST /api/disputes/<id>/approve` with `by`. It shows
  Second Look's answer verbatim: sent, or "passed to Giulia (over your 30 EUR limit)".
- **The other direction:** `SECONDLOOK_NOTIFY_URL=http://127.0.0.1:8766/hooks/secondlook`;
  `answer.sent` and `review.ready` land in the ticket's history ("Second Look: answer sent to
  PayPal by Marta, 09:14").
- **Honest limits:** made-up tickets, no real email, runs on this machine only.
- **Tests:** an approval from Ticketbook meets the same limits as the page (agent over limit →
  handoff, not send); a notification lands on the matching ticket; Second Look down → the panel
  says so, the ticket still opens.

## 3. The grown demo shop

`demo/make_demo.py`, same seed approach, same fixed "today" (2026-10-20), labelled "made-up
data" everywhere as now.

- **~6,000 orders in 90 days** (~2,000 a month). **Dispute rate kept near 2%** (~120 in 90 days),
  so the saved reviews, which cite rates, stay true.
- **Claims ~0.6%** of sales (~35). Not "just under the 1.5% line": that would mean about two in
  three disputes escalated, not believable for a shop that works. The Overview shows the distance:
  "0.6% claims. At 1.5%, every claim costs 28 EUR, even when you win."
- **Team:** Giulia (customer care manager); Marta, Luca, Sara (agents). Closed cases signed
  ("refunded by Luca, 14 Sep").
- **Open cases:** the same 12 kinds. Assigned: Marta 3, Luca 2; the rest unassigned.
- **Two changes for the easy path:** DEMO-031 (Dario, "never received the apron", 58 EUR) and
  DEMO-034 (Pablo, returned item, refund never sent) are **both a 58 EUR Linen apron** — next to
  each other in the film, a viewer would take them for one case. DEMO-034 becomes a **Linen shirt,
  89 EUR**: over Marta's 30, over the shop's 50 cap, within Giulia's limit.
- **AI cost:** re-review DEMO-034 (new item) and DEMO-036 (cites "19 claims away"): ~$0.12.
  **Ask Claudia before running.** Everything else reuses the saved reviews.

## 4. Film draft 3 — "one morning, one journey" (~2:50)

**Rules for every scene (the easy mental path):**
- Each scene answers **one question** the previous scene raised. The narration says the question
  or the answer in plain words; the viewer is never asked to infer a jump.
- **One voice; the screen shows only what the voice names.** The named element is lit, the rest
  dimmed. Never text on screen that differs from what is being said, except short labels.
- A **visible cursor** moves to what is clicked; every click is shown, nothing appears by magic.
- A small **"where you are" label**, top corner, in every app scene ("Ticketbook › ticket",
  "Second Look › case", "Second Look › Overview", "Live: PayPal sandbox").
- **People are introduced before they act** ("Marta answers customers. Giulia manages the team.").
- **No caption bar.** Subtitles go to YouTube as closed captions (`video/out/second-look-v3.srt`,
  generated from the script timings).
- Stock footage only in the opening, if at all. No music. Claude not named on screen (it is named
  in the Devpost text).

| Time | Question it answers | What is on screen | Label |
|---|---|---|---|
| 0:00–0:12 | What happens? | A dispute arrives: "Never received the apron. Refund me or I go to PayPal." | — |
| 0:12–0:40 | Why does it matter? | Take stock: four figures, one at a time, source under each | — |
| 0:40–0:50 | Who are we following? | Linen & Paper: four people in customer care, ~2,000 orders a month; Marta and Giulia introduced | — |
| 0:50–1:10 | Where does the case reach the team? | 9:00, Marta's Ticketbook inbox → the apron ticket → the Second Look panel | Ticketbook › ticket |
| 1:10–1:35 | How does she know what to do? | Click through: timeline, one check lit, the costs | Second Look › case |
| 1:35–1:45 | What happens when she approves? | Approve as Marta → signed → back in the ticket: "answer sent by Marta" | Ticketbook › ticket |
| 1:45–2:00 | What if it's more than she may give? | Next case: the shirt, 89 EUR, buyer is right → "passed to Giulia" | Second Look › case |
| 2:00–2:20 | Who decides, and what's the big picture? | Giulia's list, the handoff, she approves; Overview: what open cases could cost, distance to PayPal's line | Second Look › Overview |
| 2:20–2:35 | Is it real? | Same screen on PayPal's live sandbox, a one-person shop, a real dispute (re-filmed: current labels) | Live: PayPal sandbox |
| 2:35–2:50 | Can I trust it? | Limits in code; nothing moves until a person approves. End card: claudiaonclaude.com | — |

**Take-stock figures** (from `reports/dispute-context-research.md`; type a = official):
1. A claim costs €14; €28 for a high-volume shop, even when it wins. PayPal fees + User Agreement (a).
2. High volume: 1.5% claims with more than 100 sales in three months. PayPal User Agreement (a).
3. Settled while it is still a dispute: no fee. PayPal developer docs + User Agreement (a).
4. Midsize and large merchants accept 46% of **card chargebacks** unfought, and win 20% of those
   they fight. Mastercard/Datos 2025 (b). Said as card chargebacks: no PayPal figure exists.

**Build:** Remotion as now; app scenes filmed live from the running apps (Second Look on 8765,
Ticketbook on 8766) in `IFrame`; cursor, spotlight and label as overlay components. Narration by
Claude in `video/script-v3.md` (Claudia: "you do all"), voice Jamie (Premium). The sandbox scene
is re-filmed from the current app. Output `video/out/second-look-v3.mp4`, checked for length and
frames before it is called done, copy on the Desktop.

## Not in scope (said in the README and write-up)
Real sign-in and passwords; several PayPal accounts per team; hosting; real email in the helpdesk;
a team chat; product/season base rates; a held-out eval set.

## Order of work
1. Team features + tests. 2. Demo shop regenerated + the two re-reviews (after Claudia's OK on
~$0.12). 3. Ticketbook + tests. 4. README. 5. Script v3, scenes, render, frame check.
6. Eval re-run (~$0.85, Claudia's OK) before any score is quoted.
