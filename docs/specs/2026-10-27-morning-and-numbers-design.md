# The morning screen answers "what needs me?", the numbers get their own page, answered requests close themselves

Design approved by Claudia, 27/10/2026 ("ok both", with the numbers moved to a page of their own). Deadline: Thu
12/11/2026 12:00 PST; build target 04/11.

## Why

Claudia, 27/10, on /today: *"crowded and disordered. I know the project but lost a minute orienteering. If a judge
or a demo viewer has less time and interest to do the same we will end badly. I see, I manage, I know is a
reflection behind the scenes, not necessarily a visualization rule."* Three equal columns of small text compete;
nothing says what needs the person looking; the check box for Second Look's AI's answers is cut off.

On the numbers: *"it works as we are in demo, 1 month. On the long run you need to benchmark weeks on weeks or
months on months: better a dedicated space."* A figure alone says nothing; next to the same period before, it does.

On who closes Margot's case: nobody, today. Second Look's AI answered it, and it stays open until a person closes
it by hand: half the saving.

## 1. The morning screen (`/today`): one question, per person

The page answers what the person arrives with, **"what needs me?"**, and nothing else. *I see, I manage, I know*
stays the idea behind the product (README, film) and leaves the layout.

```
Good morning, Giulia.                       Tue 20 Oct · 7 new requests · 141 new orders

NEEDS YOU · 2
 ▸ <case> · <channel/stage> · <amount> · <deadline>
   <why it is yours: assigned to you / passed to you / over everyone else's limit>        [Open]
 ▸ Second Look's AI answered 1 on its own: check it                     (head of customer care)
   Margot · "Where is my order?" · reply sent 07:41 · closes on 23 Oct if she doesn't write
   [Looks right]   [I'd have done it differently]

NEW SINCE YESTERDAY · 7          one line each, nearest PayPal deadline first, who has it
YOUR TEAM IS ON IT               Marta 4 · Luca 2 · Sara 0 · not taken yet 14
                                                              Numbers →   (the nav keeps Disputes, Numbers, Rules)
```

- **Needs you**, in this order: cases assigned to the person; handoffs waiting for them; calls that couldn't be
  transcribed (anyone); for the head of customer care, the answers Second Look's AI sent on its own since
  yesterday. Nearest PayPal deadline first. Empty: *"Nothing needs you. Your team has the rest."*
- **Looks right** (new) marks an AI answer checked, so the count goes down; **I'd have done it differently** works
  as today (that kind off, its count restarts). The "why" field opens only after that button, never a cut-off
  text box.
- **New since yesterday**: the same rows as today's *I see*, one line each (customer · what they asked · amount ·
  deadline · who has it, or Second Look's AI's tag), not the paragraph per row of today.
- **Your team is on it** (head of customer care): one line, a person per name with their open count, and *not
  taken yet*. A colleague (Marta) sees **Your cases** instead, then **Not taken yet**.
- **A team of one** (a seller on their own): *Needs you* is every open case; no team line.
- **Nothing numeric beyond the header line.** PayPal's claim line comes onto the morning screen only as a *Needs
  you* item when the shop is within 3 claims of 1.5% (then it is something to act on); otherwise it lives on
  Numbers.
- **The header** loses the clutter: the demo's "switch person" stays, smaller, in one place.
- `GET /api/today` keeps its data (`see`, `manage`, `autopilot`); `know` moves to `GET /api/numbers`.

## 2. Numbers (`/numbers`, which replaces the Overview)

One place for every figure, each beside the same period before. (The figures in the sketch are illustrative; the page computes them.)

```
Numbers · Linen and Paper                       [ This week | This month ]   (month by default)

October so far (1–20 Oct)  vs  the same days of September (1–20 Sep)
                                   Oct 1–20     Sep 1–20     change
 Requests, every channel              70           61         +15%
   per 100 orders                    5.3          4.9
 Solved before any PayPal dispute     31           27          +4
 Answered by Second Look's AI          1            0          +1
 Staff time (estimated)            ~2 h 10      ~2 h 40      −30 min
 Money given back               314.70 EUR   402.00 EUR      −22%
 PayPal dispute fees              14 EUR       28 EUR        −14 EUR
 [Last 8 weeks: requests and solved, one small bar chart]

RIGHT NOW (no comparison: a snapshot)
 Open cases could still cost · PayPal's high-volume line (meter)
PAYPAL DISPUTES, LAST 90 DAYS   how they ended (as today's Overview)
[Export for accounting (CSV, October 2026)]
```

- **Like for like**: the current period *so far* against **the same days** of the previous one (1–20 Oct against
  1–20 Sep; Mon–Tue this week against Mon–Tue last week), never a part-month against a full one. The page says
  which days.
- **Flows compare, snapshots don't.** What happened over a period (requests, solved, staff time, money back, fees)
  has a previous value; what holds right now (open cases could still cost, PayPal's line) is shown once, under
  *Right now*.
- **Requests per 100 orders** beside the count: more requests in a busier month isn't a worse month.
- **No invented zeros.** A period before the shop's first case on record says *"no record yet"*, not 0. The demo
  has shop cases from September, PayPal disputes from July, orders from June: month and week comparisons are real
  from September on.
- **One counting function.** `today.month` becomes `today.period(start, end, ...)` (the same arithmetic, an end
  added); the month and week figures, the CSV month and the API all come from it. The exact figures today's
  *I know* shows for October (as of this spec) must come out the same for 1–20 Oct.
- **The open-cases table** of the Overview leaves: the Disputes list is that list (it keeps a link). `/overview`
  redirects to `/numbers`, so an old link still works.

## 3. An answered request closes itself

- **The rule (code, not AI):** an open shop request (no PayPal dispute) whose **last word is the shop's reply**
  (a message, no money step pending), with **no word from the customer for 3 days** after it, closes as *"Solved
  before any dispute"*, signed **"Closed by Second Look: no reply in 3 days"** on its timeline. It applies to
  every answered request, whoever answered.
- **3 days** is the shop's setting (Rules page, `policy.json`), shown in plain words.
- **When:** at each look at the shop's cases (the morning screen, the lists, the API), against the shop's today
  (the demo's is 20 Oct), as calls in the box are filed now. No timer, no background job.
- **The customer writes again before then:** the case is theirs again, nothing closes. **After:** their message
  opens a new case naming the earlier one (as today).
- **On screen:** an answered case reads *"Answered · closes on 23 Oct if Margot doesn't write"*. A person can still
  close it earlier, by hand, as today.
- **Never:** a PayPal dispute (PayPal closes those); a case with a refund, replacement or exchange still to
  happen; a case a person marked to keep open (not built: say so if asked).
- **The demo's answer time:** Second Look's AI's first-load answer to Margot is stamped on the demo's clock (a
  few minutes after her email, 20 Oct), not the computer's (it read 27 Oct, 06:25).

## 4. Testing (plain scripts, no paid call)

- *Needs you*: per person (Giulia, Marta), per item kind, the order, the empty state, the team of one.
- *Looks right* lowers the count; *I'd have done it differently* unchanged.
- Numbers: like-for-like windows (month, week, on the 1st and on a Monday), the flows match today's October
  figures, "no record yet" before the first case, per 100 orders, `/overview` redirects.
- Closing itself: closes after 3 quiet days; not at 2; not when the customer wrote; not a PayPal dispute; not
  with money pending; the signature; the setting; a later message opens a new case naming it.
- The 12-dispute snapshot stays byte-identical; the full suite passes.

## 5. The film and the README

- Film draft 10: scene 5 opens on *Needs you · 2*, Margot's answer one of them, with *closes on 23 Oct*. Scene 9
  (the month) moves to Numbers and gains the comparison ("October so far against the same days of September").
  The words stay at ≈ 413; the figures are re-read from the screen at capture.
- README: the morning screen, Numbers, the closing rule, the routes.

## Not built (say so)

A custom date range; comparison against the same month last year (no year of data); a per-person numbers view;
keeping a case open on purpose; reopening a closed case in place.
