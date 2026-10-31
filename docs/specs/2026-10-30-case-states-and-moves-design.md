# Every case in one state, every move from one catalog, every page from one template

Design by Claudia and Claude, 28–30/10/2026. Part 1 (the four states) approved 29/10 ("ok"); Part 2 (the moves)
approved 30/10 ("ok"); Part 3 (the screens) taken forward on 30/10 ("go on with paypal") with two points left for
her review of this document (marked **To confirm**). Mockups: `.superpowers/brainstorm/*/content/` in the hackathon
folder (`one-template.html` is the last). Deadline: Thu 12/11/2026 12:00 PST; build target 04/11.

## Why

Claudia, 27/10, after using the preview: *"the functioning is solid. but the UI is confused, and so the UX. as long
as I enter a section I go lost… to get if me approving a refund means answering as well… what happened? a run of
different fonts and style should address who's speaking, or if it is context, wrap up, recap, next steps… how did I
get here? what was I supposed to do?"*

And 29/10, when the design started bending around one demo case: *"we are not aiming to handle a case, but to create
a proper system… do not manufacture for a fake case that will drop once handled."*

The cause under the confusion is in the code: **whose move it is** is decided in five places that disagree.
`web.page_offer`, `today.needs_you`, `ledger.if_nobody_answers`, `web.close_quiet` with `_closes_words`, and
`web._handoff_waits` each answer part of the question. That is why Sofia Jansen stays in Needs you after Giulia
refunded her, and Margot Lefèvre after Giulia checked the AI's answer.

**The rule for everything below:** each piece is a rule over any case (PayPal inquiry, PayPal claim, shop request
by email, call or form). Demo cases only test it.

## 1. Every case is in exactly one state

| State | Whose move | Ends when | If nobody acts |
|---|---|---|---|
| **Your move** | a person of the shop: the one assigned, or the one a handoff waits for; in a team of one, the seller | someone sends a move | the point of no return, with its date (below) |
| **Waiting for the customer** | the customer | they write (→ Your move) or time runs out (→ Done) | closes itself: a shop request after the shop's quiet days (`cases.closes_on`); a PayPal inquiry PayPal closes if not escalated in 20 days (`ledger.INQUIRY_DAYS`) |
| **Waiting for PayPal** | PayPal | PayPal decides or confirms (→ Done), or refuses / the refund fails (→ Your move) | nothing: PayPal's own clock |
| **Done** | nobody | — | — |

Where each comes from, in this order (the first that matches wins):

1. **Done**: the case is `closed`, or its dispute is `RESOLVED`. Says how and by whom (`cases.outcome_says`).
2. **Waiting for PayPal**: the dispute is `UNDER_REVIEW` (PayPal is deciding a claim), or a move that moves money
   (refund, accept the claim, an offer) was sent and the dispute is not resolved yet.
3. **Waiting for the customer**: the dispute is `WAITING_FOR_BUYER_RESPONSE` after the shop answered, or a shop
   request was answered and `cases.closes_on` gives it a date. An answer Second Look's AI sent on its own lands here
   too; the head of customer care's "check it" is a separate item in their Needs you, not a state of the case.
4. **Your move**: everything else that is open: not reviewed, out of date, a decision ready to send, a handoff
   waiting, a customer who wrote again.

**The point of no return** of Your move: a PayPal dispute's answer date (`seller_response_due_date`, else
`ledger.days_left`); for a shop request, none from PayPal, said plainly ("no PayPal deadline").

**One function decides it**, `state.of(...)` in a new module `secondlook/state.py`: pure, no I/O, given the case,
its PayPal dispute if any, its assignment, the saved decision and what was sent, today and the shop's quiet days. It
returns `{state, whose, why, until, then, moves}`. Today, the case page's side box, Ticketbook's notices and the API's
`for_person` all read it; `needs_you`, `_closes_words` and the page's side box are rewritten on top of it.
`page_offer` stays as the source of the AI's pick and its draft, and becomes one input of `state.of`.

## 2. The moves: one catalog

A move is one thing the shop can do now. Each is defined once (`secondlook/moves.py`) by the same properties:

| Property | Says |
|---|---|
| **Sends** | a message, money, goods, evidence, or nothing |
| **Allowed** | for a PayPal dispute: PayPal's list for that dispute today (`allowed_response_options` and the links, as `guard.py` already reads them: no message while `WAITING_FOR_BUYER_RESPONSE`; at INQUIRY an offer can only be a refund). For a shop request: the shop's channels and terms (`shop.json` `return_policy`: the return window) |
| **Fits** | the causes it makes sense for (below) |
| **Who** | the person's limit (`guard`); over it, the move becomes "Pass to <head>, with <move> suggested" |
| **Text** | the AI's draft only for the AI's own pick; every other move a fixed template filled with the case's facts, editable |
| **Then** | the state it leads to (Part 1), and its cost or risk (from `costs_block`'s figures) |
| **Until** | the date after which it is no longer possible |

The catalog: refund in full · partial refund · exchange or replace · reply only · send evidence · decide later ·
pass to a colleague · close.

| Cause (`cases.KINDS`) | Moves that fit |
|---|---|
| never arrived | reply with the delivery proof · send evidence · refund · reply "we're tracing it" · replace |
| not as described | reply asking for photos · refund on return · partial refund · replace |
| wrong size | exchange · refund on return |
| refund never came | reply with the refund proof · refund |
| a question | reply |

**What the side box shows:** the AI's pick first, as the main button; at most two other moves that are allowed and
fit; "Decide later" whenever a point of no return exists, with its date, or "no PayPal deadline" said plainly;
everything else under "Other moves ▸". Every button is joined to what it does (one piece, no seam).

**Safety, unchanged:** limits, PayPal's allowed list, unconfirmed refunds. **Invariant:** no text promises money its
move does not send. The AI's draft is never sent with a move it was not written for (the DEMO-034 rule, 21/10); the
templates are what make the other moves possible without breaking it. One addition: a reply-only text a person edited
that mentions a refund gets a warning on the page ("Your text mentions a refund, but this move sends none"); it does
not block.

**The guard change:** `guard.may_approve` today lets a person approve only the action shown. It gains: a move is
approvable when it is in `state.of(...).moves` for that person, and its text is the AI's draft for the AI's pick, the
move's own template, or a person's edit of either. Everything that is refused today stays refused.

## 3. The screens: one template

**Case page** (`/c/` and `/d/` alike), the same slots in the same order:

1. **Where you are**: "Today › <the bucket this case is in> › <name>" and "← Back to Today · N more need you".
2. **Title**: name · the cause in words · amount · how it came in.
3. **Tracked and verified**: only facts checked against a record (PayPal, the courier, the shop's orders), one row
   each: mark · source · date · fact. ✓ checked, ◷ sent and not confirmed yet. What the customer says never goes here.
4. **What happened and what was said**: every message on every channel, oldest first, one card each. The reply
   that was sent stays here, tagged with what went with it ("sent · with the refund"). The draft is last, dashed,
   "not sent".
5. **The details**, folded: all ten checks, costs, the case as data.
6. **The side box**, from the state: Your move shows at a glance → the state pill with the date → Second Look's AI's
   advice in words (verdict, why, "Decides it / For you / Can't tell", "▸ All ten checks") → the moves. Any other
   state shows whose move it is, until when, and **"Nothing needs you"**.

**One look per voice**, on every page: the customer in serif italic with a plum bar; the shop (sent) solid with an
ink bar; a draft dashed and tagged "not sent"; Second Look's AI in amber; PayPal, the courier and the orders as blue
source labels; the page guiding in green ("what happens next"); the page warning in orange ("what you risk").

**Right after a move** there is no special page: the side box becomes the new state's box, with a "✓ Done: you
<move>" banner (who, when) and "Next in Needs you →" (or back to Today). In the demo shop: "logged here, nothing was
really sent".

**Today** shows each case once, in its state: Needs you (Your move and yours, nearest date first; the head's checks
of the AI's answers) · Waiting for the customer · Waiting for PayPal · Done (closed today). Each row: name, the last
thing that happened, and on the right the date that matters. A line under the greeting: "today you handled N cases,
about M min". "New since yesterday" and "Your team is on it" stay as they are. After a move, a toast names the case
and its new state.

**To confirm (1): the after-click mockup of 28/10 put a refunded PayPal case under "Done today".** By the rule of
Part 1 it belongs in Waiting for PayPal until PayPal confirms; otherwise one case lives in two places.

## 4. The demo shop: PayPal's confirmation is simulated, and says so

**To confirm (2).** Nothing in the demo reaches PayPal, so a refunded case would wait for PayPal forever. In the demo
shop only, the next look after a money move marks its dispute resolved, with a row "◷ → ✓ PayPal confirmed (demo:
simulated)". Never on the sandbox or a live shop.

## 5. What this fixes

| Seen on the preview, 27–29/10 | Fixed by |
|---|---|
| Sofia Jansen in Needs you after Giulia refunded her | state.of: Waiting for PayPal |
| Margot Lefèvre in Needs you after "Looks right" | state.of: Waiting for the customer; the check is a separate item |
| An accepted claim stays in Needs you | state.of, plus the demo's simulated confirmation |
| The sent reply missing from the case's conversation | slot 4 |
| Cost so far shows 0 money moved after a refund | the sent move's money is read from the move, not the dispute |
| "Approving a refund": does it answer too? | buttons named for everything they send, consequence joined |
| "How did I get here, what was I supposed to do?" | slot 1, the state pill, "Nothing needs you", the banner and "Next" |
| A Ticketbook time of 09:41 against 07:41 on the action | to check while building; not confirmed |

## 6. What does not change

The judge, its prompts and the 12-dispute snapshot (byte-identical). PayPal calls, the limits and every refusal
`guard.py` makes today. Numbers. The API's existing fields (new ones are added, none removed).

## 7. Order of build, and what slips first

1. `state.py` and the Today buckets, with the fixes in section 5.
2. The case page template: slots, voices, side box per state, the after-click banner.
3. `moves.py` with the templates and the guard change (most tests, since it touches what can be sent).

If time runs short, step 3 slips: the page then offers the AI's pick and "Decide later", which is still correct.

## 8. Tests

Plain scripts in `tests/`, as now. `state.of` over a matrix: a PayPal inquiry unanswered, answered, refunded; a claim
under review; a dispute waiting for the buyer; an email request answered, then quiet past its days, then written to
again; an AI answer on its own; a handoff; a closed case. `moves`: allowed per PayPal status and stage, fit per cause,
the limit turning a move into a pass. `guard`: a template move approvable, the AI's draft refused with any other
move, everything refused today still refused. Pages: each state's side box, the banner after a move, Today's buckets.
All 432 current tests keep passing; then a walk through the preview, and Claudia's.

## As built (31/10/2026, branch `case-states`)

Built in ten tasks, each reviewed twice (against this spec, then for quality and safety); 432 tests became
about 520; the guard's decisions on every practice and demo dispute are byte-identical before and after.
Walked in the demo shop (DEMO-039: Today → refund → Waiting for PayPal → Today: Done, *demo: simulated*).

**Changed from the design, after review:**
- *An answer counts only where it was given.* PayPal's live status wins over Second Look's record; an
  answer stops counting when the buyer writes, when PayPal escalates (a new stage) or asks again (a new
  answer-by date). An inquiry waiting for the buyer has one date (opening + 20 days). A shop request
  past its closing day that something kept open is Your move, and says so.
- *Only a full refund is money PayPal pays out at once.* A partial refund on a dispute is an offer the buyer
  accepts: the case waits for the customer.
- *A person's move is judged by every rule as if it were the answer* (`guard.move_stops`). The design reused
  the AI's stops; review showed they describe only the AI's pick (a reply-only pick carries no stop against a
  second refund on an order already refunded). Rule 4 (defend what was delivered to the PayPal address) is
  off for a person's move: it would turn their choice into a defence and skip the money rules. No move is
  offered when the AI's output wasn't recognised or PayPal takes nothing from the shop now.
- *Texts say only what is true*: evidence says "delivered" only with the courier's delivery, and speaks of
  the refund proof when that is what PayPal gets; a shop request's refund is "We're refunding"; a replacement
  on a dispute is an offer.
- *The case page never calls PayPal for its state* and never breaks when Today can't be read.
- *The draft* stays with its button in the side box, styled as the dashed draft card, rather than at the end
  of the conversation: one form, one place to edit.
- *On a phone* a one-line state ("Your move · answer by 8 Nov") sits under the crumb; the customer's message
  still comes before any button.
- *Today*: an AI answer nobody checked yet shows once, as the check; "not taken yet" never flags a case
  waiting for the customer or PayPal.
- *Partial refund* is not a move a person chooses yet (it needs an amount the guard checks); the AI's own
  partial refunds work as before.
- *`state.of` doesn't return `moves`*: web assembles them from `moves.py`, and offers and accepts them only
  where the case page shows moves (`MOVES_SHOWN`). `page_offer` stays the source of the AI's pick and its
  draft beside the state; it is not an input of `state.of`.
- *The disputes inbox reads the state too*: each row's pill, its line and "N cases wait on you" come from
  `case_state`, as on the case page, Today and the API (one out-of-date rule for all: `_out_of_date`).

**Known and left for later:** the /c/ timeline shows stored UTC times beside local "Sent by" times; the /d/
timeline strip still says "Your reply due" after the reply went; on a machine that re-transcribes Sophie's
call locally her shipped review reads as out of date (also on main); a refund logged on an order's shop
request and one on its PayPal dispute at the same instant are under different locks; a dispute PayPal
resolved today with no shop case shows in no Today bucket; Ticketbook shows the state only through the API.

