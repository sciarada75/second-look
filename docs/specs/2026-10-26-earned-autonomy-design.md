# Earned autonomy: Second Look's AI runs a kind of case once the shop's people have trusted it

Design approved by Claudia, 26/10/2026 ("ok"), from her idea the same day. Deadline: Thu 12/11/2026 12:00 PST.

## Why

Claudia, 26/10: *"one thing is the seller does not want to. another is our product does not do."* Today Second
Look can only recommend. A shop that would let it answer the routine cases has no way to. The product must be
**able** to act on its own; **whether** it does is the shop's choice. Her mechanism: a trust window. Once people
have approved Second Look's advice unchanged on a number of cases, the shop can let it run that kind of case,
and Second Look's AI itself steps back to a person when it should.

This is the staff time the Inspiration text is about (`paypal-ai/devpost/write-up.md`): the routine answers
("where is my order", "left with a neighbour") stop costing minutes, and the people keep the cases that need them.

## Decisions (Claudia, 26/10)

1. **Second Look's AI earns autonomy one kind of case at a time, from the shop's own people.** Never by a score
   we measured (our cases aren't the shop's), never by value alone ("anything under X EUR" pays small-claim fraud
   automatically).
2. **A kind** = stage + problem + recommended action: e.g. `inquiry · not_received · MESSAGE`, `paypal ·
   MERCHANDISE_OR_SERVICE_NOT_RECEIVED · DEFEND`. The stage is `inquiry` or `paypal` (any PayPal dispute or claim
   stage); the problem is the case's problem kind (inquiry) or PayPal's reason (dispute).
3. **The window: 10.** A kind is **ready** when the last 10 decisions people made on it were *approved as
   advised*: the action Second Look recommended (after the guard), the same amount, the reply not edited
   (compared with whitespace collapsed). Any other decision on that kind (another action, another amount, an
   edited reply) restarts its count.
4. **Ready is not on.** The head of customer care (a role with no refund limit) switches a ready kind on, and off.
   Nobody else can. A kind that isn't ready can't be switched on.
5. **What it may send once on:** replies (MESSAGE) and evidence (DEFEND) on its kinds; **money** (REFUND,
   PARTIAL_REFUND, REPLACE) only up to **its own limit, which starts at 0 EUR** and only the head of customer care
   raises. Over its limit it does exactly what Marta does: passes the case to a person, nothing sent.
6. **Numbers (the shop's, in its team block):** window 10, autopilot confidence 0.90, 20 cases a day per kind,
   money limit 0 EUR. Shown on the Rules page in plain words.

## 1. Second Look's AI in the team

- A team block gains `"autopilot": {"refund_up_to": 0, "window": 10, "min_confidence": 0.90, "per_day": 20}`.
  It is **not** in `people`: it is never assigned a case, never a handoff target, never listed under I manage
  as a person, and nobody signs in as it. (A person in `people` would receive handoffs: `team.handoff_to` takes
  the first colleague whose limit covers the amount.)
- It approves through the **one approval path** (`approve` → `_approve` under `_case_lock`), as the person
  `{"id": "second-look-ai", "name": "Second Look's AI", "role": "Second Look's AI"}`, whose limit is the
  autopilot's `refund_up_to`. So the guard, `page_offer`, team limits, `covers`, Decision 8, rules 9 and 10,
  the unconfirmed-refund marks and the same-channel Outbox all apply unchanged.
- Everything it sends is signed **"Sent by Second Look's AI, under Giulia's setting (since 15 Oct)"** on the
  timeline (`ai: true`), in the action log, in `answer.sent` to the helpdesk and in the books row's "approved by".

## 2. The record and the switch

- One store per shop (`team.JsonFile`, like assignments): `.tmp/autopilot-<shop>.json`, demo seeded from
  `demo/shop.json`. Per kind: the last decisions (case, when, who, as advised or not), on/off, who switched it
  and when, today's count.
- **Only people's decisions count.** A decision is recorded in `_approve` when a person (not Second Look's AI)
  approves a review **made by Second Look's AI** (judge `claude`; the rules baseline never counts). Its own sends
  never count toward its record: it can't grade itself.
- **The record restarts when the setup changes:** it carries a fingerprint of what the AI was told (the judge's
  instructions, SYSTEM and SYSTEM_INQUIRY) and the shop's rules (`policy.json`: seller preferences and limits).
  A different fingerprint = an empty record and every kind off, with the reason on screen ("Your rules changed
  on 22 Oct: the record starts again"). Learned 17/10: a score holds only for the setup it was measured with.

## 3. When it runs, and when it steps back

**When:** a request is filed (email, form, call) or a PayPal dispute joins a case, **and** that shop has at least
one kind on for this stage and problem. Then, in the background (like whisper and the books posts, never inside
a request), it runs one review with Second Look's AI and, if the recommended action is a kind that's on, approves
it as itself. A shop with nothing on pays for nothing.

**It steps back to a person** (nothing sent; the case stays in I see with the reason) when any of these holds:

| Steps back when | Risk this project already met |
|---|---|
| the review came from the rules baseline (no key, or the model failed) | the rules refunded a parcel on its way (IQ-004, 26/10) |
| the guard raised any stop or note (injection, repeat buyer, inconsistent evidence, already refunded or replaced, unconfirmed refund, PayPal doesn't allow it) | injection (DEMO-038, IQ-007); double refunds (I1–I3, 25/10) |
| confidence under the autopilot's 0.90 (approval itself needs 0.75) | borderline cases flip between runs (PP-D-002 at 0.70–0.75) |
| the AI's own answer is ASK_SELLER | its own way to step back |
| the case changed since the review (`_changes`: new message, new words, new stage) | stale reviews (18/10, 25/10) |
| the case is assigned to a person, or passed to one (a handoff waits) | a person already holds it |
| today's 20 for this kind are used | a repeated mistake can't spread across a day |
| a person has already answered on this case (it stays theirs) | never talks over a colleague |

A step back is recorded on the case: "Second Look's AI stepped back: <reason>. A person decides."

## 4. On screen

- **I see:** a row handled by Second Look's AI says so ("Handled by Second Look's AI · reply sent"); a step back
  says why.
- **I manage:** a new line, **"Handled by Second Look's AI: 3 — check them"**, linking the list. On each, **"I'd
  have done it differently"** (any person): switches that kind off at once, restarts its count, records who and
  why. The answer already sent stays sent; the person follows up.
- **Rules page:** "Second Look's AI on its own": each kind with its record ("10 of the last 10 approved as
  advised"), ready / on / off, the switch (head of customer care only), the four numbers in plain words.

## 5. The demo

- **The shop's past decisions are seeded** so that `inquiry · not_received · MESSAGE` shows 10 of the last 10
  approved as advised, switched on by Giulia on 15 Oct. Nothing else is on.
- **One new request this morning** (a customer asks where an order is, its parcel on its way on time) ships its
  Second Look's AI review, like Sophie's, and is **handled by Second Look's AI when the demo first loads**,
  through the real autopilot path. So a judge with no key sees it handled, signed, with "I'd have done it
  differently". A judge who posts a new request without a key sees the step back ("the review came from the
  rules baseline"): honest, and itself a demonstration.
- Dario, Pablo, Sophie, Lena stay as they are: the film's cases don't change.

## 6. Testing (plain scripts, no paid call)

- The window, with a fake AI judge: 9 approvals as advised → not ready; the 10th → ready; an edited reply → count
  restarts; a rules-baseline review → not counted; Second Look's AI's own sends → not counted.
- The switch: only the head of customer care; a kind that isn't ready can't be switched on.
- The run: a new request of an on kind → approved as Second Look's AI through `approve` (signed, logged, booked).
- **Every step-back reason in §3**, one test each.
- Money: over its limit (0 EUR) → passed to a person, nothing sent; raised to 30 → sends within it.
- Setup change (prompt or policy) → record empty, kinds off. Daily ceiling. "I'd have done it differently".
- The PayPal side unchanged with nothing on: the 12-dispute snapshot byte-identical.
- Live: autopilot off by default; nothing in the tests touches the live sandbox.

## 7. The film and the write-up

- Film draft 10: scene 5 (the morning) gains one beat (≈ 30 words: cut the same elsewhere, the script is at
  ≈ 405 of ≈ 410): "And the routine ones? After ten approvals unchanged,
  Giulia let Second Look's AI answer 'where is my order' on its own. It signs what it sends, and it steps back
  when it isn't sure." Scene 11 stays "Your limits have the last word. You approve": still true, the approval is
  Giulia's setting.
- Write-up: earned autonomy as built; money on its own as the shop's setting, starting at 0.

## Not built (say so)

Autopilot on money by default; learning from the record beyond the count (it never changes the AI's
instructions); a held-out measure per shop; undoing a sent answer.
