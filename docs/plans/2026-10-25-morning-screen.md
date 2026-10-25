# Morning Screen Implementation Plan (build step 2: "I see, I manage, I know", every channel; roles renamed)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A shop opens Second Look on its morning screen, `/today`, which has three blocks:
- **I see**: everything that came in since yesterday, from every channel, in one list, nearest PayPal deadline first, each row matched to its order and carrying Second Look's recommendation in one line, with the new orders counted beside it.
- **I manage**: who has which open case, what nobody has, and what waits after a handoff.
- **I know**: this month, every channel, in money and hours, with PayPal's claim line.

The Overview gains the same month figures. The team's titles become "Head of customer care" and "Customer care assistant", and every screen where a colleague's name appears shows their role. Approving "Your call" (`ASK_SELLER`) itself is refused.

**Architecture:** A new pure module, `secondlook/today.py`, does the grouping and the arithmetic over what the shop already holds: its cases (the case file, plus, in the demo, the closed cases of the weeks before), PayPal's disputes, its orders, and who has which case. Nothing in it calls PayPal or a model. `web.py` reads the data once (`today_view`), renders three blocks (`see_block`, `manage_block`, `month_block`), and reuses the Overview's claim-line meter (extracted as `claim_line_box`). The demo generator gains the shop's earlier cases from a **new random stream**, `rng3`, drawn after everything else: the PayPal side and the 12 open disputes stay byte-for-byte the same, and the shipped reviews stay valid.

**Tech Stack:** Python 3.9 standard library. Tests are plain scripts run as `python3 tests/test_x.py` (pytest is not installed). No test calls a model: each fakes Second Look's AI and fails if the real one is reached.

**Spec:** `docs/specs/2026-10-25-inquiry-system-design.md`: §2 (the morning screen), Decision 7 (every name carries its role), §4 ("Past months filled so 'I know' has real figures"). Build step 2. Step 1 is merged (c3fc6fc, 265 tests).

## Design decisions (made while planning, from what the code and the demo data show)

1. **"Since yesterday"** runs from 00:00 on the day before the shop's today, with no end (`today.since`). In the demo shop (today = 20 Oct 2026) that is everything from 19 Oct, including anything a person does now, whatever the clock says. The live shop uses the UTC date. Times are compared as Second Look saves them (`2026-10-19T08:52`, UTC like PayPal's).
   - A **row** is a problem with something new on it: a case with a message in since then, or a PayPal dispute opened since then. A case and its dispute are one row.
   - The **chips** count messages in by channel, disputes opened, and orders placed (both payment ledgers) over the same time.
2. **"This month"** runs from 00:00 on the 1st of the shop's today's month, with no end (`today.month_start`): in the demo, from 1 Oct 2026.
3. **What "I know" counts**, every channel:
   - **Requests**: cases opened this month, plus PayPal disputes opened this month that no case holds. A case and its dispute count as one.
   - **Solved before any PayPal dispute**: shop inquiries closed this month that never became a dispute. Cases now record `closed_at`; older ones fall back to their last entry.
   - **Staff time, estimated**: written answers this month (a case's "out" entries, plus answers to PayPal disputes sent from Second Look, read from their saved reviews) × the shop's reply minutes (`policy.json` → `staff_time`) + calls' own minutes (step 3) × the hourly cost.
   - **Money given back**: refunds logged on cases this month (an inquiry's refunds are logged, never moved, since step 1), plus PayPal refunds on disputes resolved this month (`ledger.refunded`; a dispute without `update_time` counts by its opening).
   - **Fees**: PayPal dispute fees on claims resolved this month, estimated from PayPal's fee table exactly as the Overview does, plus any fee logged on a case.
   - **Open cases could still cost, at most**: every open PayPal dispute lost at claim (the Overview's `exposure.all_lost`), plus every open inquiry refunded in full (its order's value less what already went out on it).
   - **PayPal's claim line**: the Overview's own meter.
   - **No accounting export** until step 3: no dead button.
4. **The Overview gains the month figures through the same function.** `month_block(today.month(...))` sits at the top of the Overview with a link to `/today`. Below it, the Overview keeps PayPal's own 90-day window, labelled "PayPal disputes only". One function and one set of numbers, so the two pages can't disagree. Linking without showing was rejected: the Overview is where the owner looks at money, so the month belongs there too.
5. **`/` stays the Disputes list; `/today` is the shop's first page.** It is the first item of the navigation, and the Second Look logo links to it. `/` doesn't move because the film's capture script (`video/capture.mjs`), the README and many links open `/?shop=demo` expecting the list. Of the texts that script asserts ("Approve as Marta", "Pass to Giulia", "passed to Giulia by Marta", "Marta suggests", "Sent by Giulia", "answer sent to PayPal by Marta"), none changes. The film is not touched; `video/script-v3.md` and `video/src/Scenes3.tsx` keep draft 3's old titles.
6. **Roles.** The titles live in the shop's data (`demo/make_demo.py` → `demo/shop.json` → `team`), and every page reads them from there; the live shop has no team block (a team of one). The rename changes that data, the tests' own team fixtures, Ticketbook's list of agents (now generated with each role) and the README. Names gain their role where a list shows whose a case is:
   - the Disputes list's owner tags ("Giulia, Head of customer care · passed by Marta");
   - a dispute page's owner line ("Giulia's case (Head of customer care).");
   - Ticketbook's "Signed in as Marta, Customer care assistant";
   - every row of I manage.

   Sentences that name a colleague twice keep the name alone after the role has been shown on the screen ("Marta suggests…", "Sent by Giulia", "Pass to Giulia"), so the film's assertions hold.
7. **The demo shop's earlier cases** go in `demo/shop.json` → `history`: 82 closed shop inquiries, 1 Sep to 16 Oct, 29 of them in October. They are read only, for "I know", and never written into the case file, so case ids, the morning's three cases (`DEMO-C001`–`C003`) and every step-1 test stay as they are. Their ids are `DEMO-H001`…, which no case page or case file can give out.
   - Each is on an order of a customer with no other request, no PayPal dispute and no order after 9 Oct, so nothing this morning (a ticket, a request, a dispute) can land on one. Guard rules 9/10 never see them.
   - The 12-dispute snapshot (`scratchpad/disputes_snapshot.py`) is identical before and after this plan (Task 10 proves it).
8. **The spec's "8 new orders"** can't be shown truthfully. The demo shop takes about 65 orders a day (2,000 a month), and its orders are on the PayPal side, which must not move. Since yesterday it shows **141 new orders** (68 on 19 Oct, 73 on 20 Oct). The other counts are what the spec asks: **2 emails, 1 web form, 3 PayPal disputes** (DEMO-034, 039 and 036; with Ticketbook running, its two dispute emails make 4 emails). The phone chip says **"Phone: not connected yet"** until step 3.
9. **A recommendation in one line** comes from the decision's saved review:
   - labelled "Second Look's AI" (Claude, here or shipped ahead of time) or "Rules baseline";
   - "Answered: …" once sent;
   - "Not reviewed yet" otherwise.

   The morning screen never runs a review by itself: a review on a page view would cost money with a key, and write files without one. So on a fresh clone with no key, Sophie's and Lena's rows read "Not reviewed yet" until someone opens them. That's honest, but not "already checked by Second Look's AI" as the spec words it. The paid demo-inquiry reviews to ship are a later step, with Claudia's OK.
10. **`ASK_SELLER` is not an answer.** `approve()` refuses it with 400 before anything else, for the page and both APIs. Until now, approving "Your call" itself marked the review sent with nothing done.

**Not in this plan:** calls and the phone chip's count, orders/courier stand-ins, accounting and its export (step 3); the eval (step 4); the film (step 5).

## Rules the code must keep

- **No paid call in any test**; never `export ANTHROPIC_API_KEY`; never open or edit `.env`.
- **Nothing is approved on a live sandbox dispute (`PP-*`)**; the fresh-clone check approves nothing at all.
- **Stage files by name**; check the staged list before each commit.
- **The PayPal side of the demo never moves**: `tests/test_demo_shop.py`'s fingerprint, the generator's determinism test, and the 12-dispute snapshot (Task 10).
- **Never the repo's real `.tmp/`** in a test (every bench redirects case files, reviews, logs); scratch work only under `/private/tmp/claude-501/-Users-claudiamauri-Desktop-hackathons-paypal-ai/7fe40038-1fc8-4bbd-a54c-d74e1e02ecd1/scratchpad/`; free ports only, never 8765 or 8766. Scratch folder names ignore case on this Mac: never create or delete one whose name differs from another only by case.

## File structure

| File | Responsibility |
|---|---|
| `demo/make_demo.py` (modify), `demo/shop.json` (regenerate) | the new titles; the shop's earlier cases (`history`, stream `rng3`) |
| `secondlook/demo.py` (modify) | `history()` |
| `secondlook/today.py` (create) | since yesterday, this month; I see (`came_in`), I manage (`open_items`, `who_has`), I know (`month`) |
| `secondlook/cases.py` (modify) | a case closed by PayPal records `closed_at` |
| `secondlook/web.py` (modify) | `shop_cases`, `review_line`, `sent_answers`, `today_view`; the page (`see_block`, `manage_block`, `month_block`, `claim_line_box`, `today_page`); `/today`, `/api/today`; navigation; the Overview's month block; names with roles in owner tags; `closed_at` when a person closes; `ASK_SELLER` refused |
| `helpdesk/make_tickets.py`, `helpdesk/tickets.json` (modify, regenerate), `helpdesk/app.py` (modify) | agents with their roles; "Signed in as Marta, Customer care assistant" |
| `tests/test_today.py` (create) | the morning screen, pure and through the web |
| `tests/test_demo_shop.py`, `tests/test_web.py`, `tests/test_helpdesk.py`, `tests/test_intake.py`, `tests/test_team.py`, `tests/test_cases.py` (modify) | titles, roles shown, earlier cases, `ASK_SELLER`, `closed_at` |
| `README.md` (modify) | the morning screen; the titles; `/api/today` |

Run all tests at any point:

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && for f in tests/test_*.py; do python3 $f | tail -1; done
```

Expected before Task 1 (alphabetical): cases `11`, demo_shop `11`, guard `33`, helpdesk `35`, inquiry `39`, intake `27`, ledger `11`, sort `15`, team `16`, web `66` (265).

## Before you start

- [ ] Work on a branch, from a clean main:

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && git switch main && test -z "$(git status --porcelain)" && git switch -c morning-screen && echo READY
```

Expected: `Switched to a new branch 'morning-screen'`, then `READY`.

- [ ] Record the 12 open disputes as the review, the guard and the API see them today (Task 10 compares):

```bash
S=/private/tmp/claude-501/-Users-claudiamauri-Desktop-hackathons-paypal-ai/7fe40038-1fc8-4bbd-a54c-d74e1e02ecd1/scratchpad
python3 "$S/disputes_snapshot.py" /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look > "$S/snap-before-morning.json" 2> "$S/snap-before-morning.err" && echo SNAPSHOT-SAVED
```

Expected: `SNAPSHOT-SAVED` (it runs in the tests' temporary bench: nothing real is written).

---

### Task 1: The team's new titles

**Files:**
- Modify: `demo/make_demo.py:31-36` (the team), `:381-382` (a comment); regenerate `demo/shop.json`
- Modify: `tests/test_team.py`, `tests/test_web.py`, `tests/test_intake.py` (their own team fixtures and the titles they expect), `tests/test_demo_shop.py:78` (a comment)
- Test: `tests/test_demo_shop.py`

- [ ] **Step 1: Write the failing test.** In `tests/test_demo_shop.py`, add above `if __name__ == "__main__":`

```python
def test_the_team_s_roles_are_the_shop_s_own_titles():
    roles = {p["name"]: p["role"] for p in pp.shop["team"]["people"]}
    assert roles == {"Giulia": "Head of customer care", "Marta": "Customer care assistant",
                     "Luca": "Customer care assistant", "Sara": "Customer care assistant"}
    assert set(pp.shop["team"]["roles"]) == {"Head of customer care", "Customer care assistant"}
```

- [ ] **Step 2: Run it, see it fail**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && python3 tests/test_demo_shop.py 2>&1 | tail -1
```

Expected: `AssertionError`

- [ ] **Step 3: Implement.** In `demo/make_demo.py`, the team:

Replace:

```python
        "roles": {"Customer care manager": {"refund_up_to": None},
                  "Customer care agent": {"refund_up_to": 30.0}},
        "people": [{"id": "giulia", "name": "Giulia", "role": "Customer care manager"},
                   {"id": "marta", "name": "Marta", "role": "Customer care agent"},
                   {"id": "luca", "name": "Luca", "role": "Customer care agent"},
                   {"id": "sara", "name": "Sara", "role": "Customer care agent"}]},
```

with:

```python
        "roles": {"Head of customer care": {"refund_up_to": None},
                  "Customer care assistant": {"refund_up_to": 30.0}},
        "people": [{"id": "giulia", "name": "Giulia", "role": "Head of customer care"},
                   {"id": "marta", "name": "Marta", "role": "Customer care assistant"},
                   {"id": "luca", "name": "Luca", "role": "Customer care assistant"},
                   {"id": "sara", "name": "Sara", "role": "Customer care assistant"}]},
```

Replace:

```python
# Nobody signs a case the buyer withdrew or PayPal closed with no decision. Agents send refunds up to 30 EUR,
# so a bigger refund or accepted offer the shop sent is the manager's.
```

with:

```python
# Nobody signs a case the buyer withdrew or PayPal closed with no decision. Assistants send refunds up to 30 EUR,
# so a bigger refund or accepted offer the shop sent is the head of customer care's.
```

In `tests/test_demo_shop.py`, the comment:

Replace:

```python
    # agents send refunds up to 30 EUR: a bigger refund or accepted offer the shop sent is the manager's
```

with:

```python
    # assistants send refunds up to 30 EUR: a bigger refund or accepted offer the shop sent is the head's
```

The tests' own team fixtures and the titles they expect (a plain rename, no other change):

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && python3 - <<'EOF'
from pathlib import Path
for f in ("tests/test_team.py", "tests/test_web.py", "tests/test_intake.py"):
    p = Path(f)
    s = p.read_text()
    n = s.count("Customer care manager") + s.count("Customer care agent")
    p.write_text(s.replace("Customer care manager", "Head of customer care").replace("Customer care agent", "Customer care assistant"))
    print(f, n)
EOF
```

Expected: `tests/test_team.py 6`, `tests/test_web.py 6`, `tests/test_intake.py 3` (titles renamed in each).

- [ ] **Step 4: Regenerate the demo shop and run the tests**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && python3 demo/make_demo.py && git diff --stat demo/shop.json | tail -1
```

Expected: the same counts as before, then `1 file changed, 6 insertions(+), 6 deletions(-)` (the six titles only).

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && for f in tests/test_*.py; do python3 $f | tail -1; done
```

Expected: cases `11`, demo_shop `12`, guard `33`, helpdesk `35`, inquiry `39`, intake `27`, ledger `11`, sort `15`, team `16`, web `66`.

- [ ] **Step 5: Commit**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && git add demo/make_demo.py demo/shop.json tests/test_demo_shop.py tests/test_team.py tests/test_web.py tests/test_intake.py && git diff --cached --name-only && git commit -q -m "Team: Head of customer care and Customer care assistants (Decision 7)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>" && test -z "$(git status --porcelain)" && echo CLEAN
```

Expected: the six file names, then `CLEAN`.

---

### Task 2: Every list that says whose a case is names the role too; Ticketbook as well

**Files:**
- Modify: `secondlook/web.py:1395-1401` (`owner_tag`), `:2177-2178` (`review_column`'s owner line)
- Modify: `helpdesk/make_tickets.py:78-79` (agents with roles), regenerate `helpdesk/tickets.json`; `helpdesk/app.py:328-339` (`_page`)
- Test: `tests/test_web.py`, `tests/test_helpdesk.py`

- [ ] **Step 1: Write the failing tests.** In `tests/test_web.py`:

Replace:

```python
    assert web.owner_tag(TEAM, store.get("D2")) == "Giulia · passed by Marta"
```

with:

```python
    assert web.owner_tag(TEAM, store.get("D2")) == "Giulia, Head of customer care · passed by Marta"
```

Replace:

```python
"Giulia's case." in sent
```

with:

```python
"Giulia's case (Head of customer care)." in sent
```

In `tests/test_helpdesk.py`, add above `if __name__ == "__main__":`

```python
def test_every_agent_s_name_carries_their_role():
    roles = {**TICKETS, "agents": [{"id": "marta", "name": "Marta", "role": "Customer care assistant"},
                                   {"id": "giulia", "name": "Giulia", "role": "Head of customer care"}]}
    html = bench(FakeSL(), roles).inbox_page("marta")
    assert "Signed in as <b>Marta</b>, Customer care assistant" in html and "Giulia <small>Head of customer care</small>" in html
    shop = json.loads((Path(__file__).resolve().parent.parent / "demo" / "shop.json").read_text())
    team = {p["id"]: p["role"] for p in shop["shop"]["team"]["people"]}
    tickets = json.loads((Path(__file__).resolve().parent.parent / "helpdesk" / "tickets.json").read_text())
    assert {a["id"]: a["role"] for a in tickets["agents"]} == team       # Ticketbook names the team as the shop does
```

- [ ] **Step 2: Run them, see them fail**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && python3 tests/test_web.py 2>&1 | tail -1; python3 tests/test_helpdesk.py 2>&1 | tail -1
```

Expected: `AssertionError`, twice.

- [ ] **Step 3: Implement.** In `secondlook/web.py`, `owner_tag`:

Replace:

```python
    who = team_mod.person(t, a["to"])
    name = who["name"] if who else a["to"]
    hand = a.get("handoff")
```

with:

```python
    who = team_mod.person(t, a["to"])
    name = (who["name"] + (f', {who["role"]}' if who.get("role") else "")) if who else a["to"]
    hand = a.get("handoff")
```

In `review_column`, the owner line:

Replace:

```python
            owner = f'<p class="owner-line">{e(holder_name)}\'s case.</p>' if plain_owner else ""
```

with:

```python
            role = f' ({holder["role"]})' if holder and holder.get("role") else ""
            owner = f'<p class="owner-line">{e(holder_name)}\'s case{e(role)}.</p>' if plain_owner else ""
```

In `helpdesk/make_tickets.py`, the agents carry the shop's titles:

Replace:

```python
     "agents": [{"id": "marta", "name": "Marta"}, {"id": "luca", "name": "Luca"},
                {"id": "sara", "name": "Sara"}, {"id": "giulia", "name": "Giulia"}],
```

with:

```python
     # the shop's customer care team, with each person's role as the shop names it (demo/shop.json)
     "agents": [{"id": pid, "name": p["name"], "role": p["role"]} for pid in ("marta", "luca", "sara", "giulia")
                for p in shop["shop"]["team"]["people"] if p["id"] == pid],
```

In `helpdesk/app.py`, `_page`:

Replace:

```python
        menu = "".join(f'<a href="?as={e(quote(a["id"]))}"{" class=on" if a["id"] == me["id"] else ""}>{e(a["name"])}</a>'
```

with:

```python
        role = f', {e(str(me["role"]))}' if me.get("role") else ""          # every name carries its role
        menu = "".join(f'<a href="?as={e(quote(a["id"]))}"{" class=on" if a["id"] == me["id"] else ""}>{e(a["name"])}'
                       + (f' <small>{e(str(a["role"]))}</small>' if a.get("role") else "") + '</a>'
```

Replace:

```python
<details class="who"><summary>Signed in as <b>{e(me["name"])}</b> ▾</summary><div class="menu">{menu}</div></details></div>
```

with:

```python
<details class="who"><summary>Signed in as <b>{e(me["name"])}</b>{role} ▾</summary><div class="menu">{menu}</div></details></div>
```

Regenerate the tickets:

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && python3 helpdesk/make_tickets.py && git diff --stat helpdesk/tickets.json | tail -1
```

Expected: `tickets.json: 16 tickets`, then `1 file changed, 8 insertions(+), 4 deletions(-)` (a role on each of the four agents; no ticket changes).

- [ ] **Step 4: Run the tests**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && python3 tests/test_web.py | tail -1 && python3 tests/test_helpdesk.py | tail -1 && python3 tests/test_intake.py | tail -1
```

Expected: `66 passed`, `36 passed`, `27 passed`.

- [ ] **Step 5: Commit**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && git add secondlook/web.py helpdesk/make_tickets.py helpdesk/tickets.json helpdesk/app.py tests/test_web.py tests/test_helpdesk.py && git diff --cached --name-only && git commit -q -m "Every list that says whose a case is names the role; Ticketbook signs in with it" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>" && test -z "$(git status --porcelain)" && echo CLEAN
```

Expected: the six file names, then `CLEAN`.

---

### Task 3: "Your call" itself is never approved

**Files:**
- Modify: `secondlook/web.py:2369-2380` (`approve`)
- Test: `tests/test_web.py`

- [ ] **Step 1: Write the failing test.** In `tests/test_web.py`, add above `if __name__ == "__main__":`

```python
def test_your_call_itself_is_never_approved_so_a_review_is_never_marked_sent_with_nothing_done():
    with approval_bench(action="ASK_SELLER", ai="REFUND", stops=["cap"]) as b:
        code, text = web.approve("X", "ASK_SELLER", None, by="giulia")
        assert code == 400 and "not an answer" in text and b.sent == [] and web._saved("X")[1] is None
```

- [ ] **Step 2: Run it, see it fail**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && python3 tests/test_web.py 2>&1 | tail -1
```

Expected: `AssertionError` (today it answers 200 and marks the review sent).

- [ ] **Step 3: Implement.** In `secondlook/web.py`, at the top of `approve`:

Replace:

```python
    from .__main__ import execute
    t = team_for(did)
    who = team_mod.person(t, by)
```

with:

```python
    from .__main__ import execute
    if chosen == "ASK_SELLER":
        # "your call" is what the review says when a person must choose; approving it would mark the review sent
        # with nothing done (found in review, 25/10)
        return 400, "\"Your call\" is not an answer: choose what to send (a reply, a refund, your evidence)."
    t = team_for(did)
    who = team_mod.person(t, by)
```

- [ ] **Step 4: Run all tests**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && for f in tests/test_*.py; do python3 $f | tail -1; done
```

Expected: cases `11`, demo_shop `12`, guard `33`, helpdesk `36`, inquiry `39`, intake `27`, ledger `11`, sort `15`, team `16`, web `67`.

- [ ] **Step 5: Commit**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && git add secondlook/web.py tests/test_web.py && git diff --cached --name-only && git commit -q -m "Approve: \"your call\" itself is refused (400), so a review is never marked sent with nothing done" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>" && test -z "$(git status --porcelain)" && echo CLEAN
```

Expected: the two file names, then `CLEAN`.

---

### Task 4: The demo shop's earlier cases (a new random stream)

**Files:**
- Modify: `demo/make_demo.py` (a section above `OUT.write_text(…)`, `:443`, and the key written), regenerate `demo/shop.json`
- Modify: `secondlook/demo.py:71` (`history`, above `requests`)
- Test: `tests/test_demo_shop.py`

- [ ] **Step 1: Write the failing test.** In `tests/test_demo_shop.py`, add above `if __name__ == "__main__":`

```python
def test_the_earlier_cases_are_closed_and_touch_nothing_this_morning_or_paypal_holds():
    h = pp.history()
    assert len(h) == 82 and sum(1 for c in h if c["opened"] >= "2026-10-01") == 29
    assert all(c["status"] == "closed" and c["closed_at"] < "2026-10-19" and c["dispute_id"] is None for c in h)
    assert all(c["id"].startswith("DEMO-H") for c in h)              # never a case id the case file could give out
    disputed = {d["disputed_transactions"][0]["seller_transaction_id"] for d in pp.disputes()}
    late = {o["email"] for o in pp.orders() if o["date"] >= "2026-10-10"} | {r["from"]["email"] for r in pp.requests()}
    assert not {c["order_no"] for c in h} & disputed and not {c["customer"]["email"] for c in h} & late
    assert len({c["customer"]["email"] for c in h}) == len(h)        # one case per customer
```

- [ ] **Step 2: Run it, see it fail**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && python3 tests/test_demo_shop.py 2>&1 | tail -1
```

Expected: `AttributeError: 'DemoPayPal' object has no attribute 'history'`

- [ ] **Step 3: Implement.** In `demo/make_demo.py`, insert immediately above `OUT.write_text(json.dumps({"_comment": …`:

```python
# ---------- the shop's earlier cases (26/10): what "I know" counts this month ----------
# Closed shop inquiries from 1 September to 16 October, by email or the web form, each answered and closed by the
# team: the shop's own record of the weeks before this morning. A third random stream (rng3) draws them, after
# everything above, so no earlier draw moves (the PayPal side and the paid reviews stay exactly as they were).
# Each case is about an order of a customer who has no other request, no PayPal dispute and no order after
# 9 October, so nothing this morning (a ticket, a request, a dispute) can land on one of them.
rng3 = random.Random(20261026)
disputed = {x["disputed_transactions"][0]["seller_transaction_id"] for x in disputes}
late_buyers = {o["email"] for o in orders if o["date"] >= "2026-10-10"} | {r["from"]["email"] for r in requests}
eligible = [o for o in grown if o["transaction_id"] not in disputed and o["email"] not in late_buyers]
WHERE = ["with a neighbour", "in your building's mailroom", "at the front door"]
# weight, kind, subject, what the customer wrote, [(outcome, weight, the team's answer)]; {item}: the order's item
HISTORY_KINDS = [
    (6, "not_received", "Where is my order?", "Hello, my {item} hasn't arrived yet. Could you check where it is?",
     [("solved", 6, "Your parcel was delivered on {day}: the courier left it {where}. Could you check there?"),
      ("refunded", 2, "We're sorry: the courier has lost your parcel. We've refunded you in full."),
      ("withdrawn", 2, None)]),
    (3, "not_as_described", "A problem with my order", "The {item} arrived with a small mark on it. What can you do?",
     [("replaced", 3, "We're sorry: a new one is on its way to you today."),
      ("refunded", 1, "We're sorry: we've refunded you in full. No need to send it back."),
      ("solved", 2, "Stonewashed linen has small marks by nature; a gentle wash takes most of them out. "
                    "Tell us if this one stays.")]),
    (1, "refund_missing", "Refund for my return?", "I sent the {item} back last week. When will the refund come?",
     [("refunded", 1, "Your return has arrived: we've refunded you in full.")]),
]
SIZE_KIND = (1, "wrong_size", "Wrong size", "The {item} is too small. Can I exchange it for the next size?",
             [("replaced", 1, "Of course: send it back and the next size goes out as soon as it arrives.")])
CLOSE_SAYS = {"solved": "solved before any dispute", "refunded": "refunded", "replaced": "replaced or exchanged",
              "withdrawn": "the customer withdrew"}


def at(day, h, m):
    return datetime(day.year, day.month, day.day, h, m).strftime("%Y-%m-%dT%H:%M")


history, used, k, day = [], set(), 0, date(2026, 9, 1)
while day <= date(2026, 10, 16):
    for _ in range(rng3.choice([0, 1, 1, 2, 2, 2, 3])):
        pool = [o for o in eligible if o["email"] not in used
                and (day - timedelta(days=14)).isoformat() <= o["date"] <= (day - timedelta(days=3)).isoformat()]
        if not pool:
            continue
        o = rng3.choice(pool)
        used.add(o["email"])
        item = o["items"][0]["item_name"]
        _, kind, subject, text, answers = (SIZE_KIND if item == "Linen shirt" and rng3.random() < 0.5
                                           else rng3.choice([h for h in HISTORY_KINDS for _ in range(h[0])]))
        outcome_, _, answer = rng3.choice([a for a in answers for _ in range(a[1])])
        channel = "email" if rng3.random() < 0.75 else "form"
        k += 1
        opened = at(day, rng3.randint(7, 21), rng3.randint(0, 59))
        t0 = datetime.strptime(opened, "%Y-%m-%dT%H:%M")
        amount = o["amount"]
        by = "Giulia" if outcome_ in ("refunded", "replaced") and amount > 30 else rng3.choice(["Marta", "Luca", "Sara"])
        said = text.format(item=item.lower())
        timeline_ = [{"at": opened, "channel": channel, "direction": "in", "text": said, "by": o["name"], "ai": False,
                      "subject": subject, "from": {"name": o["name"], "email": o["email"]}}]
        money = []
        if answer:
            replied = (t0 + timedelta(hours=rng3.randint(1, 20))).strftime("%Y-%m-%dT%H:%M")
            timeline_.append({"at": replied, "channel": channel, "direction": "out", "by": by, "ai": False,
                              "text": answer.format(day=o["date"], where=rng3.choice(WHERE))})
            if outcome_ == "refunded":
                money.append({"kind": "refund", "amount": amount, "at": replied, "by": by})
            if outcome_ == "replaced":
                money.append({"kind": "replace", "amount": amount, "at": replied, "by": by})
            last = datetime.strptime(replied, "%Y-%m-%dT%H:%M")
        else:
            last = t0 + timedelta(hours=rng3.randint(2, 30))
            timeline_.append({"at": last.strftime("%Y-%m-%dT%H:%M"), "channel": channel, "direction": "in",
                              "text": "It's arrived, sorry for the trouble!", "by": o["name"], "ai": False,
                              "from": {"name": o["name"], "email": o["email"]}})
        closed = (last + timedelta(hours=rng3.randint(0, 30))).strftime("%Y-%m-%dT%H:%M")
        timeline_.append({"at": closed, "channel": channel, "direction": "note", "by": by, "ai": False,
                          "text": f"Closed by {by}: {CLOSE_SAYS[outcome_]}."})
        history.append({"id": f"DEMO-H{k:03d}", "customer": {"name": o["name"], "email": o["email"]},
                        "order_no": o["transaction_id"], "problem": {"kind": kind, "summary": subject},
                        "stage": "inquiry", "status": "closed", "outcome": outcome_, "closed_at": closed,
                        "dispute_id": None, "sorted": {"by": "rules", "how": "An earlier case: the shop's own record."},
                        "opened": opened, "timeline": timeline_, "money": money})
    day += timedelta(days=1)
```

and write it into the file:

Replace:

```python
                           "other_orders": other_orders, "requests": requests},
```

with:

```python
                           "other_orders": other_orders, "requests": requests, "history": history},
```

In `secondlook/demo.py`, above `def requests(self)`:

Replace:

```python
    def requests(self) -> list:
```

with:

```python
    def history(self) -> list:
        """The shop's closed inquiries of the weeks before this morning (made up, like everything here): read only,
        for the morning screen's "I know"."""
        return self.raw.get("history", [])

    def requests(self) -> list:
```

- [ ] **Step 4: Regenerate and run the tests**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && python3 demo/make_demo.py && python3 -c "import json; h = json.load(open('demo/shop.json'))['history']; print(len(h), sum(c['opened'] >= '2026-10' for c in h))"
```

Expected: the same counts as before, then `82 29` (82 earlier cases, 29 of them in October).

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && for f in tests/test_*.py; do python3 $f | tail -1; done
```

Expected: cases `11`, demo_shop `13` (the fingerprint and the generator's determinism among them), guard `33`, helpdesk `36`, inquiry `39`, intake `27`, ledger `11`, sort `15`, team `16`, web `67`.

- [ ] **Step 5: Commit**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && git add demo/make_demo.py demo/shop.json secondlook/demo.py tests/test_demo_shop.py && git diff --cached --name-only && git commit -q -m "Demo shop: the shop's earlier cases, closed, from a new random stream (nothing PayPal holds moves)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>" && test -z "$(git status --porcelain)" && echo CLEAN
```

Expected: the four file names, then `CLEAN`.

---

### Task 5: I see: since yesterday, every channel, one row per problem (`today.came_in`)

**Files:**
- Create: `secondlook/today.py`
- Create: `tests/test_today.py`

- [ ] **Step 1: Write the failing tests.** Create `tests/test_today.py`:

```python
"""The morning screen: I see (since yesterday, every channel), I manage (who has what), I know (this month).
Run: python3 tests/test_today.py"""
import json
import sys
import tempfile
import threading
from contextlib import contextmanager
from datetime import date
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secondlook import demo as demo_mod, judge, sort as sort_mod, team as team_mod, today, web  # noqa: E402
from secondlook.demo import DemoPayPal  # noqa: E402

TODAY = date(2026, 10, 20)
TEAM = {"roles": {"Head of customer care": {"refund_up_to": None}, "Customer care assistant": {"refund_up_to": 30.0}},
        "people": [{"id": "giulia", "name": "Giulia", "role": "Head of customer care"},
                   {"id": "marta", "name": "Marta", "role": "Customer care assistant"}]}


def dispute(did, opened, status="WAITING_FOR_SELLER_RESPONSE", amount="40.00", tx=None, stage="INQUIRY", outcome=None,
            refunded=None):
    d = {"dispute_id": did, "create_time": opened, "status": status, "dispute_life_cycle_stage": stage,
         "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "dispute_amount": {"value": amount, "currency_code": "EUR"},
         "seller_response_due_date": opened[:8] + str(int(opened[8:10]) + 10).zfill(2) + opened[10:],
         "disputed_transactions": [{"seller_transaction_id": tx or f"TX-{did}", "buyer": {"name": f"Buyer {did}"}}],
         "messages": [{"posted_by": "BUYER", "content": f"Where is it? ({did})"}]}
    if outcome:
        d["dispute_outcome"] = {"outcome_code": outcome[0], "outcome_reason": outcome[1]}
        if refunded:
            d["dispute_outcome"]["amount_refunded"] = {"currency_code": "EUR", "value": refunded}
    return d


def case(cid, *entries, status="open", dispute_id=None, order_no=None, money=(), closed_at=None, opened=None):
    tl = [{"at": at, "channel": ch, "direction": way, "text": "…", "by": "Ann" if way == "in" else "Marta", "ai": False}
          for at, ch, way in entries]
    return {"id": cid, "customer": {"name": f"Customer {cid}", "email": f"{cid.lower()}@example.com"},
            "order_no": order_no, "problem": {"kind": "not_received", "summary": f"Summary {cid}"}, "stage": "inquiry",
            "status": status, "outcome": "solved" if status != "open" else None, "dispute_id": dispute_id,
            "sorted": {"by": "rules", "how": ""}, "opened": opened or tl[0]["at"], "timeline": tl, "money": list(money),
            **({"closed_at": closed_at} if closed_at else {})}


def test_since_yesterday_and_this_month_start_at_midnight_and_have_no_end():
    assert today.since(TODAY) == "2026-10-19T00:00" and today.month_start(TODAY) == "2026-10-01T00:00"
    assert today.since(date(2026, 11, 1)) == "2026-10-31T00:00" and today.month_start(date(2026, 11, 1)) == "2026-11-01T00:00"


def test_i_see_one_row_per_problem_every_channel_nearest_paypal_deadline_first():
    cases = [case("C1", ("2026-10-19T08:52", "email", "in")),                        # new email, no dispute
             case("C2", ("2026-10-18T09:00", "email", "in"), dispute_id="D1"),       # old email, its dispute is new
             case("C3", ("2026-10-12T09:00", "form", "in"), ("2026-10-13T09:00", "form", "out"))]  # nothing new
    disputes = [dispute("D1", "2026-10-19T10:30:00Z"), dispute("D2", "2026-10-20T17:50:00Z"),
                dispute("D3", "2026-10-17T10:00:00Z")]
    orders = [{"date": "2026-10-19"}, {"date": "2026-10-20"}, {"date": "2026-10-18"}]
    s = today.came_in(cases, disputes, orders, TODAY, review_of=lambda did: {"by": "ai", "text": f"rec {did}"})
    assert s["counts"] == {"call": 0, "email": 1, "form": 0, "paypal": 2} and s["orders"] == 2
    assert [(r["link"], r["channels"], r["days_left"]) for r in s["rows"]] == [
        ("/c/C2", ["paypal"], 9), ("/d/D2", ["paypal"], 10), ("/c/C1", ["email"], None)]
    assert s["rows"][0]["review"] == {"by": "ai", "text": "rec D1"}          # a case with a dispute: the dispute's review
    assert s["rows"][2]["review"]["text"] == "rec C1"


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
```

- [ ] **Step 2: Run them, see them fail**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && python3 tests/test_today.py 2>&1 | tail -1
```

Expected: `ImportError: cannot import name 'today' from 'secondlook' (…)`

- [ ] **Step 3: Implement.** Create `secondlook/today.py`:

```python
"""The morning screen, "I see, I manage, I know": grouping and arithmetic over what the shop already holds (its
cases, PayPal's disputes, its orders, who has which case). Nothing here calls PayPal or a model.

  I see     everything that came in since yesterday, from every channel, in one list, nearest deadline first,
            with the orders that came in over the same time beside it (problems read against sales);
  I manage  who has which open case, what nobody has yet, and what waits for a colleague after a handoff;
  I know    this month, every channel: requests, solved before any PayPal dispute, staff time (estimated),
            money given back, fees, what the open cases could still cost.

"Since yesterday" starts at 00:00 on the day before the shop's today and has no end: in the demo shop (today is
20 Oct 2026) it is everything from 19 Oct on, including anything a person does now, whatever the clock says.
"This month" starts at 00:00 on the 1st of the shop's today's month, with no end either. Times are compared
as Second Look saves them ("2026-10-19T08:52"): the demo shop's are UTC, like PayPal's.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import ledger
from .cases import CHANNEL_LABEL, KIND_LABEL, minute, staff_time
from .costs import DISPUTE_FEE, escalated

# The order chips and rows show channels in.
CHANNEL_ORDER = ("call", "email", "form", "paypal")
# Money that went back to a customer, as a case logs it (an inquiry's refund).
BACK = ("refund", "partial_refund")


def since(today: date) -> str:
    return (today - timedelta(days=1)).isoformat() + "T00:00"


def month_start(today: date) -> str:
    return today.replace(day=1).isoformat() + "T00:00"


def _at(iso) -> str:
    """A PayPal or Second Look time as Second Look saves it; "" when there is none (never "now")."""
    return minute(iso) if iso else ""


def _num(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return v if v == v else 0.0


def _tx(d: dict) -> str | None:
    return ((d.get("disputed_transactions") or [{}])[0]).get("seller_transaction_id")


def _buyer_name(d: dict) -> str | None:
    return (((d.get("disputed_transactions") or [{}])[0]).get("buyer") or {}).get("name")


def _first_message(d: dict) -> str:
    return next((m.get("content", "") for m in d.get("messages", []) if m.get("posted_by") == "BUYER"), "")


def _dispute_of_case(cases: list) -> dict:
    """Dispute id -> the case holding it: the open one first (a closed case is history)."""
    out = {}
    for c in sorted(cases, key=lambda c: c.get("status") == "open"):
        if c.get("dispute_id"):
            out[c["dispute_id"]] = c
    return out


def _amounts(orders: list) -> dict:
    """Order number -> its amount (the shop's own number, else PayPal's transaction id, as cases name orders)."""
    return {(o.get("order_no") or o.get("transaction_id")): _num(o.get("amount")) for o in orders}


def came_in(cases: list, disputes: list, orders: list, today: date, review_of=lambda did: None) -> dict:
    """I see: every problem something came in on since yesterday, one row each (a case and its PayPal dispute are
    one row), nearest PayPal deadline first, then the shop's own inquiries in the order they came in.
    `review_of(decision id)`: one line on what Second Look recommends there, or None."""
    start = since(today)
    by_id = {d["dispute_id"]: d for d in disputes}
    held = _dispute_of_case(cases)
    amount_of = _amounts(orders)
    rows, counts = [], {ch: 0 for ch in CHANNEL_ORDER}
    for c in cases:
        ins = [x for x in c.get("timeline", []) if x.get("direction") == "in" and (x.get("at") or "") >= start]
        d = by_id.get(c.get("dispute_id"))
        if d is not None and held.get(d["dispute_id"]) is not c:
            d = None                                   # the dispute's row is its open case's, not this old one's
        new_dispute = d is not None and _at(d.get("create_time")) >= start
        if not ins and not new_dispute:
            continue
        for x in ins:
            counts[x["channel"]] = counts.get(x["channel"], 0) + (x["channel"] != "paypal")
        chans = [ch for ch in CHANNEL_ORDER if any(x["channel"] == ch for x in ins)]
        if d is not None and "paypal" not in chans:
            chans.append("paypal")
        decision = c.get("dispute_id") if d is not None else c["id"]
        rows.append({"case_id": c["id"], "dispute_id": c.get("dispute_id"), "link": f"/c/{c['id']}",
                     "decision_id": decision, "channels": chans, "who": c["customer"].get("name") or c["customer"].get("email"),
                     "summary": c["problem"].get("summary") or KIND_LABEL.get(c["problem"].get("kind"), ""),
                     "order_no": c.get("order_no"),
                     "amount": _num(d["dispute_amount"]["value"]) if d else amount_of.get(c.get("order_no"), 0.0),
                     "status": c.get("status"), "first": min([x["at"] for x in ins] + ([_at(d.get("create_time"))] if new_dispute else [])),
                     "days_left": ledger.days_left(d, today) if d is not None and d.get("status") != "RESOLVED" else None,
                     "review": review_of(decision)})
    for d in disputes:
        opened = _at(d.get("create_time"))
        if opened < start:
            continue
        counts["paypal"] += 1
        if d["dispute_id"] in held:
            continue
        rows.append({"case_id": None, "dispute_id": d["dispute_id"], "link": f"/d/{d['dispute_id']}",
                     "decision_id": d["dispute_id"], "channels": ["paypal"], "who": _buyer_name(d),
                     "summary": _first_message(d), "order_no": _tx(d), "amount": _num(d["dispute_amount"]["value"]),
                     "status": "open" if d.get("status") != "RESOLVED" else "closed", "first": opened,
                     "days_left": ledger.days_left(d, today) if d.get("status") != "RESOLVED" else None,
                     "review": review_of(d["dispute_id"])})
    rows.sort(key=lambda r: (r["days_left"] is None, r["days_left"] if r["days_left"] is not None else 0, r["first"]))
    return {"since": start, "rows": rows, "counts": counts,
            "orders": sum(1 for o in orders if (o.get("date") or "") >= start[:10])}


def channel_words(counts: dict) -> list:
    """("📞", "calls", n)-style labels for the chips, in CHANNEL_ORDER: plural words for the counts."""
    nouns = {"call": ("call", "calls"), "email": ("email", "emails"), "form": ("web form", "web forms"),
             "paypal": ("PayPal dispute", "PayPal disputes")}
    return [(ch, nouns[ch][counts.get(ch, 0) != 1], counts.get(ch, 0)) for ch in CHANNEL_ORDER if ch in CHANNEL_LABEL]
```

- [ ] **Step 4: Run the tests**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && python3 tests/test_today.py | tail -1
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && git add secondlook/today.py tests/test_today.py && git diff --cached --name-only && git commit -q -m "Today: I see, everything since yesterday on every channel, one row per problem, nearest deadline first" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>" && test -z "$(git status --porcelain)" && echo CLEAN
```

Expected: the two file names, then `CLEAN`.

---

### Task 6: I manage and I know (`today.who_has`, `today.month`)

**Files:**
- Modify: `secondlook/today.py` (added at the end)
- Test: `tests/test_today.py`

- [ ] **Step 1: Write the failing tests.** In `tests/test_today.py`, add above `if __name__ == "__main__":`

```python
def test_i_manage_who_has_what_with_roles_and_what_waits_after_a_handoff():
    items = [{"id": "D1", "link": "/d/D1", "who": "Pablo", "summary": "s", "amount": 89.0},
             {"id": "C1", "link": "/c/C1", "who": "Sophie", "summary": "s", "amount": 64.0},
             {"id": "D2", "link": "/d/D2", "who": "Dario", "summary": "s", "amount": 58.0}]
    assigned = {"D1": {"to": "giulia", "handoff": {"from": "marta", "from_name": "Marta", "action": "REFUND"}},
                "D2": {"to": "marta", "handoff": None}}
    mg = today.who_has(items, assigned, team_mod.of(TEAM))
    giulia, marta = mg["people"]
    assert (giulia["name"], giulia["role"], len(giulia["items"]), len(giulia["waiting"])) == ("Giulia", "Head of customer care", 1, 1)
    assert (marta["role"], len(marta["items"]), marta["passed_on"]) == ("Customer care assistant", 1, 1)
    assert [i["id"] for i in mg["unassigned"]] == ["C1"]
    assert mg["handoffs"][0]["from_role"] == "Customer care assistant" and mg["handoffs"][0]["to_name"] == "Giulia"
    solo = today.who_has(items, {}, team_mod.of(None))
    assert solo["solo"] and solo["total"] == 3


def test_i_know_this_month_every_channel_in_money_and_hours():
    cases = [case("C1", ("2026-10-02T09:00", "email", "in"), ("2026-10-02T11:00", "email", "out"), status="closed",
                  order_no="O1", money=[{"kind": "refund", "amount": 30.0, "at": "2026-10-02T11:00"}],
                  closed_at="2026-10-03T09:00"),
             case("C2", ("2026-09-20T09:00", "form", "in"), ("2026-09-21T09:00", "form", "out"), status="closed",
                  closed_at="2026-09-22T09:00"),                                   # last month: not counted
             case("C3", ("2026-10-19T08:52", "email", "in"), order_no="O3"),       # open, nothing out yet
             case("C4", ("2026-10-05T08:00", "email", "in"), dispute_id="D1", order_no="TX-D1")]
    disputes = [dispute("D1", "2026-10-05T10:00:00Z"),
                dispute("D2", "2026-10-06T10:00:00Z", status="RESOLVED", stage="CHARGEBACK",
                        outcome=("RESOLVED_BUYER_FAVOUR", "ITEM_NOT_RECEIVED"), refunded="20.00")]
    orders = [{"date": "2026-10-01", "order_no": "O1", "amount": 30.0}, {"date": "2026-10-10", "order_no": "O3", "amount": 64.0},
              {"date": "2026-09-30", "transaction_id": "TX-D1", "amount": 40.0}]
    k = today.month(cases, disputes, orders, TODAY, {"staff_time": {"hourly_cost": 30, "reply_minutes": 10}},
                    answers=["2026-10-07T10:00", "2026-09-30T10:00"])
    # requests: C1, C3, C4 (its dispute D1 is one request with it) and D2, a PayPal dispute with no case
    assert (k["orders"], k["requests"], k["solved_before_dispute"]) == (2, 4, 1)
    assert k["requests_by_channel"] == {"call": 0, "email": 3, "form": 0, "paypal": 1}
    assert (k["answers"], k["minutes"], k["staff_cost"]) == (2, 20.0, 10.0)        # C1's answer + one PayPal answer
    assert (k["back_cases"], k["back_paypal"], k["back"]) == (30.0, 20.0, 50.0)
    assert k["fees"] == 14.0                                                          # a lost claim's standard fee
    assert k["open_inquiries_most"] == 64.0 and k["open_disputes_most"] == 54.0      # 40 + a 14 EUR fee
    assert k["could_still_cost"] == 118.0
```

- [ ] **Step 2: Run them, see them fail**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && python3 tests/test_today.py 2>&1 | tail -1
```

Expected: `AttributeError: module 'secondlook.today' has no attribute 'who_has'`

- [ ] **Step 3: Implement.** At the end of `secondlook/today.py`, add:

```python
def open_items(cases: list, disputes: list, orders: list) -> list:
    """Everything still open, once each: every open PayPal dispute (a case holding one is answered on it), and every
    open shop inquiry. Each with its decision id (whose assignment it is), who it is about and what is at stake."""
    held = _dispute_of_case(cases)
    amount_of = _amounts(orders)
    out = []
    for d in disputes:
        if d.get("status") == "RESOLVED":
            continue
        c = held.get(d["dispute_id"])
        out.append({"id": d["dispute_id"], "link": f"/c/{c['id']}" if c else f"/d/{d['dispute_id']}",
                    "who": (c or {}).get("customer", {}).get("name") or _buyer_name(d),
                    "summary": (c or {}).get("problem", {}).get("summary") or _first_message(d),
                    "amount": _num(d["dispute_amount"]["value"])})
    for c in cases:
        if c.get("status") == "open" and not c.get("dispute_id"):
            out.append({"id": c["id"], "link": f"/c/{c['id']}", "who": c["customer"].get("name") or c["customer"].get("email"),
                        "summary": c["problem"].get("summary") or "", "amount": amount_of.get(c.get("order_no"), 0.0)})
    return out


def who_has(items: list, assigned: dict, team: dict) -> dict:
    """I manage: for each person of the team (in the shop's own order), the open items they have and the handoffs
    waiting for them; what nobody has; every handoff. `assigned`: decision id -> {"to", "handoff"}."""
    if team.get("solo"):
        return {"solo": True, "total": len(items), "people": [], "unassigned": [], "handoffs": []}
    people = [p for p in team.get("people", []) if isinstance(p, dict) and p.get("id")]
    ids = {p["id"] for p in people}
    rows = {p["id"]: {"id": p["id"], "name": p.get("name") or p["id"], "role": p.get("role") or "", "items": [],
                      "waiting": [], "passed_on": 0} for p in people}
    unassigned, handoffs = [], []
    for it in items:
        a = assigned.get(it["id"]) or {}
        to, hand = a.get("to"), a.get("handoff") if isinstance(a.get("handoff"), dict) else None
        if to not in ids:
            unassigned.append(it)
            continue
        rows[to]["items"].append(it)
        if hand:
            rows[to]["waiting"].append(it)
            if hand.get("from") in rows:
                rows[hand["from"]]["passed_on"] += 1
            frm = rows.get(hand.get("from")) or {"name": hand.get("from_name") or "A colleague", "role": ""}
            handoffs.append({**it, "from_name": frm["name"], "from_role": frm["role"],
                             "to_name": rows[to]["name"], "to_role": rows[to]["role"]})
    return {"solo": False, "total": len(items), "people": [rows[p["id"]] for p in people],
            "unassigned": unassigned, "handoffs": handoffs}


def _closed_at(c: dict) -> str:
    """When a case closed: as recorded, else its last timeline entry (cases closed before closed_at was kept)."""
    return c.get("closed_at") or max((x.get("at") or "" for x in c.get("timeline", [])), default="")


def month(cases: list, disputes: list, orders: list, today: date, policy: dict | None, answers=(),
          currency: str = "EUR") -> dict:
    """I know: this month, every channel. `answers`: when each answer to a PayPal dispute was sent from Second Look
    (an inquiry's answers are on its case already). Staff time is an estimate (cases.staff_time); dispute fees are
    estimated from PayPal's fee table, as the Overview's."""
    m = month_start(today)
    held = {c.get("dispute_id") for c in cases if c.get("dispute_id")}
    ordered = sum(1 for o in orders if (o.get("date") or "") >= m[:10])
    new_cases = [c for c in cases if (c.get("opened") or "") >= m]
    new_disputes = [d for d in disputes if _at(d.get("create_time")) >= m and d["dispute_id"] not in held]
    solved = [c for c in cases if c.get("status") != "open" and not c.get("dispute_id") and _closed_at(c) >= m]
    st = staff_time(policy)
    entries = [x for c in cases for x in c.get("timeline", []) if (x.get("at") or "") >= m]
    written = sum(1 for x in entries if x.get("direction") == "out" and x.get("channel") != "call")
    written += sum(1 for a in answers if (a or "") >= m)
    call_min = sum(_num(x.get("minutes")) for x in entries if x.get("channel") == "call" and x.get("direction") in ("in", "out"))
    minutes = written * st["reply_minutes"] + call_min
    money = [x for c in cases for x in c.get("money", []) if (x.get("at") or "") >= m]
    back_cases = round(sum(_num(x.get("amount")) for x in money if x.get("kind") in BACK), 2)
    resolved = [d for d in disputes if d.get("status") == "RESOLVED" and _at(d.get("update_time") or d.get("create_time")) >= m]
    back_paypal = round(sum(ledger.refunded(d) for d in resolved), 2)
    hv = ledger.overview(disputes, orders, today, currency)["high_volume"]
    standard, hv_fee = DISPUTE_FEE.get(currency, (0.0, 0.0))
    fees = sum(hv_fee if hv["high_volume"] else standard if ledger.outcome(d) in ("lost_claim", "lost_no_reply") else 0
               for d in resolved if escalated(d))
    fees = round(fees + sum(_num(x.get("amount")) for x in money if x.get("kind") == "fee"), 2)
    ex = ledger.exposure(disputes, today, hv["high_volume"], currency)
    amount_of = _amounts(orders)
    open_inq = [c for c in cases if c.get("status") == "open" and not c.get("dispute_id") and c.get("order_no")]
    inq_stake = round(sum(max(0.0, amount_of.get(c["order_no"], 0.0)
                              - sum(_num(x.get("amount")) for x in c.get("money", []) if x.get("kind") in BACK + ("replace",)))
                          for c in open_inq), 2)
    return {"from": m, "orders": ordered, "requests": len(new_cases) + len(new_disputes),
            "requests_by_channel": _first_channels(new_cases, len(new_disputes)),
            "solved_before_dispute": len(solved), "answers": written, "minutes": minutes,
            "hourly_cost": st["hourly_cost"], "reply_minutes": st["reply_minutes"],
            "staff_cost": round(minutes / 60 * st["hourly_cost"], 2),
            "back_cases": back_cases, "back_paypal": back_paypal, "back": round(back_cases + back_paypal, 2),
            "fees": fees, "open_disputes_most": ex["all_lost"], "open_inquiries_most": inq_stake,
            "could_still_cost": round(ex["all_lost"] + inq_stake, 2), "high_volume": hv, "currency": currency}


def _first_channels(new_cases: list, new_disputes: int) -> dict:
    """How this month's requests first came in: each case by its first message's channel, a dispute with no
    case by PayPal."""
    out = {ch: 0 for ch in CHANNEL_ORDER}
    for c in new_cases:
        first = next((x["channel"] for x in sorted(c.get("timeline", []), key=lambda x: x.get("at") or "")
                      if x.get("direction") == "in"), "paypal" if c.get("dispute_id") else None)
        if first in out:
            out[first] += 1
    out["paypal"] += new_disputes
    return out
```

- [ ] **Step 4: Run the tests**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && python3 tests/test_today.py | tail -1
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && git add secondlook/today.py tests/test_today.py && git diff --cached --name-only && git commit -q -m "Today: I manage (who has what, handoffs, with roles) and I know (this month, every channel, in money and hours)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>" && test -z "$(git status --porcelain)" && echo CLEAN
```

Expected: the two file names, then `CLEAN`.

---

### Task 7: The shop's morning, read once (`web.today_view`); a case records when it closed

**Files:**
- Modify: `secondlook/web.py`: the imports (`:31`), a new section above `# ---------- the case page: one customer, …` (`:1649`), `_close` (`:770`)
- Modify: `secondlook/cases.py:303` (a case PayPal closes records when)
- Test: `tests/test_today.py`, `tests/test_cases.py`

- [ ] **Step 1: Write the failing tests.** In `tests/test_today.py`, add above `if __name__ == "__main__":`

```python
@contextmanager
def morning():
    """The demo shop's real data, its case file, assignments, reviews and logs in a temporary folder, no AI key,
    notifications dropped. The real Claude judge and the real AI sort fail the test if they are called."""
    tmp = Path(tempfile.mkdtemp())
    kept = (web.CASE_FILES, web.OUTBOX_LOGS, web.REVIEWS, web.SUGGESTED, web.assignments_for, web.has_ai_key, web.notify,
            sort_mod.read_with_ai, judge.INQUIRY_BACKENDS["claude"], judge.BACKENDS["claude"], demo_mod.ACTION_LOG)
    store = team_mod.Assignments(tmp / "assignments.json", seed=DemoPayPal().raw.get("assignments"))

    def no_paid_call(*a):
        raise AssertionError("no paid AI call may run in this test")
    try:
        web.CASE_FILES = {"demo": tmp / "cases-demo.json", "live": tmp / "cases-live.json"}
        web.OUTBOX_LOGS = {"demo": tmp / "actions-demo.jsonl", "live": tmp / "actions-live.jsonl"}
        web.REVIEWS, web.SUGGESTED = tmp / "reviews", tmp / "suggested.json"
        demo_mod.ACTION_LOG = tmp / "demo-paypal-actions.jsonl"
        web.assignments_for = lambda did: store
        web.has_ai_key = lambda: False
        web.notify = lambda event, payload: None
        sort_mod.read_with_ai = judge.INQUIRY_BACKENDS["claude"] = judge.BACKENDS["claude"] = no_paid_call
        yield store
    finally:
        (web.CASE_FILES, web.OUTBOX_LOGS, web.REVIEWS, web.SUGGESTED, web.assignments_for, web.has_ai_key, web.notify,
         sort_mod.read_with_ai, judge.INQUIRY_BACKENDS["claude"], judge.BACKENDS["claude"], demo_mod.ACTION_LOG) = kept


def test_the_demo_morning_reads_every_channel_against_its_orders():
    with morning():
        v = web.today_view("demo")
        s = v["see"]
        assert s["since"] == "2026-10-19T00:00" and s["counts"] == {"call": 0, "email": 2, "form": 1, "paypal": 3}
        assert s["orders"] == 141                                # 68 orders on 19 Oct, 73 on 20 Oct: made-up, ~2,000 a month
        assert [r["link"] for r in s["rows"]] == ["/c/DEMO-C003", "/d/DEMO-039", "/d/DEMO-036", "/c/DEMO-C001", "/c/DEMO-C002"]
        pablo = s["rows"][0]
        assert pablo["channels"] == ["email", "paypal"] and pablo["decision_id"] == "DEMO-034" and pablo["days_left"] == 19
        assert pablo["review"] == {"by": "ai", "text": "Your call (your limits held back: refund in full)"}
        assert s["rows"][3]["review"] == {"by": None, "text": "Not reviewed yet"}
        people = {p["name"]: (p["role"], len(p["items"])) for p in v["manage"]["people"]}
        assert people == {"Giulia": ("Head of customer care", 0), "Marta": ("Customer care assistant", 3),
                          "Luca": ("Customer care assistant", 2), "Sara": ("Customer care assistant", 0)}
        assert len(v["manage"]["unassigned"]) == 9 and v["manage"]["handoffs"] == []
        k = v["know"]
        assert (k["from"], k["orders"], k["requests"], k["solved_before_dispute"]) == ("2026-10-01T00:00", 1329, 64, 31)
        assert (k["answers"], k["staff_cost"], k["back_cases"], k["back_paypal"], k["fees"]) == (23, 57.5, 160.0, 154.7, 14.0)
        assert k["could_still_cost"] == 1073.0


def test_what_the_team_does_this_morning_shows_at_once():
    with morning() as store:
        web.run_review("DEMO-C001")                             # the rules baseline: no key here
        row = next(r for r in web.today_view("demo")["see"]["rows"] if r["case_id"] == "DEMO-C001")
        assert row["review"] == {"by": "rules", "text": "Reply only"}
        assert web.approve("DEMO-C001", "MESSAGE", "It was left with your neighbour.", by="marta")[0] == 200
        assert web.close_case("DEMO-C001", "solved", "marta")[0] == 200
        assert web.case_store("demo").get("DEMO-C001")["closed_at"]          # when it closed, for "this month"
        v = web.today_view("demo")
        row = next(r for r in v["see"]["rows"] if r["case_id"] == "DEMO-C001")
        assert row["review"]["text"] == "Answered: Reply sent by email" and row["status"] == "closed"
        assert (v["know"]["answers"], v["know"]["solved_before_dispute"]) == (24, 32)
        code, _ = web.approve("DEMO-034", "REFUND", "You're right: here is your refund.", by="marta")
        assert code == 202                                       # over Marta's 30 EUR: passed to Giulia, nothing sent
        hand = web.today_view("demo")["manage"]["handoffs"]
        assert [(h["id"], h["from_name"], h["from_role"], h["to_name"], h["to_role"]) for h in hand] == [
            ("DEMO-034", "Marta", "Customer care assistant", "Giulia", "Head of customer care")]
```

In `tests/test_cases.py`, a case PayPal closes says when:

Replace:

```python
        assert (y["status"], y["outcome"], y["closed_by"]) == ("closed", key, "PayPal"), code
```

with:

```python
        assert (y["status"], y["outcome"], y["closed_by"]) == ("closed", key, "PayPal"), code
        assert y["closed_at"] == "2026-10-19T10:30"          # PayPal's time (no update_time here: its opening)
```

- [ ] **Step 2: Run them, see them fail**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && python3 tests/test_today.py 2>&1 | tail -1; python3 tests/test_cases.py 2>&1 | tail -1
```

Expected: `AttributeError: module 'secondlook.web' has no attribute 'today_view'`, then `KeyError: 'closed_at'`.

- [ ] **Step 3: Implement.** In `secondlook/web.py`, the imports:

Replace:

```python
from . import cases as cases_mod, evidence as evidence_mod, judge as judge_mod, ledger, sort as sort_mod, team as team_mod
```

with:

```python
from . import cases as cases_mod, evidence as evidence_mod, judge as judge_mod, ledger, sort as sort_mod, team as team_mod, today as today_mod
```

Insert immediately above the line `# ---------- the case page: one customer, one order, one problem, every channel ----------`:

```python
# ---------- the morning screen: "I see, I manage, I know" (secondlook/today.py does the counting) ----------

def shop_cases(src: str) -> list:
    """Every case of a shop the morning screen counts: its case file (the demo's seeded on first read), and, for
    the demo shop, the closed cases of the weeks before this morning, from demo/shop.json ("history", read only)."""
    cases = case_store(src).all() if src in CASE_FILES else []
    return cases + (DemoPayPal().history() if src == "demo" else [])


def review_line(did: str) -> dict:
    """What Second Look recommends on a case, in one line, and who said it: "ai" (Second Look's AI: Claude, here or
    ahead of time), "rules" (the rules baseline, no AI key), or None (not reviewed yet, or already answered)."""
    saved = _saved(did)
    if not saved:
        return {"by": None, "text": "Not reviewed yet"}
    dec, sent = saved
    w = _words(did)
    if sent:
        return {"by": None, "text": "Answered: " + sent.split(". ")[0].rstrip(".")}
    text = w["action"].get(dec.action, dec.action)
    j = dec.judgment
    if dec.overridden and j.action != dec.action and j.action in w["action"]:
        text += f' (your limits held back: {w["action"][j.action].lower()})'
    return {"by": "rules" if judge_of(did) == "rules" else "ai", "text": text}


def sent_answers(src: str) -> list:
    """When each answer to one of this shop's PayPal disputes was sent from Second Look (its saved review's `at`).
    An inquiry's answers are on its case's timeline already, so they are not counted here twice."""
    out = []
    for f in sorted(REVIEWS.glob("*.json")) if REVIEWS.exists() else []:
        did = f.stem
        if cases_mod.is_case_id(did) or is_demo(did) != (src == "demo") or did.startswith("PP-D-"):
            continue
        raw = _raw(did) or {}
        if raw.get("sent") and raw.get("at"):
            out.append(cases_mod.minute(raw["at"]))
    return out


def today_view(src: str) -> dict:
    """The three blocks of the morning screen, as data (the page and GET /api/today show the same)."""
    demo = src == "demo"
    today = DemoPayPal().today if demo else datetime.utcnow().date()
    cases, disputes, orders = shop_cases(src), shop_disputes(src), shop_orders(src)
    t = team_for_src(src)
    assigned = {} if t.get("solo") else assignments_for("DEMO-" if demo else None).all()
    return {"today": today, "team": t,
            "see": today_mod.came_in(cases, disputes, orders, today, review_of=review_line),
            "manage": today_mod.who_has(today_mod.open_items(cases, disputes, orders), assigned, t),
            "know": today_mod.month(cases, disputes, orders, today, _policy(), sent_answers(src))}
```

In `_close`, a person's closing records when:

Replace:

```python
    def close(x):
        x["status"], x["outcome"] = "closed", outcome
```

with:

```python
    def close(x):
        x["status"], x["outcome"], x["closed_at"] = "closed", outcome, cases_mod.minute(None)
```

In `secondlook/cases.py`, `link_disputes`, a case PayPal closes records PayPal's time:

Replace:

```python
                    c.update(status="closed", outcome=key, closed_by="PayPal")
```

with:

```python
                    c.update(status="closed", outcome=key, closed_by="PayPal",
                             closed_at=minute(d.get("update_time") or d.get("create_time")))
```

- [ ] **Step 4: Run the tests**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && python3 tests/test_today.py | tail -1 && python3 tests/test_cases.py | tail -1 && python3 tests/test_inquiry.py | tail -1
```

Expected: `6 passed`, `11 passed`, `39 passed`.

- [ ] **Step 5: Commit**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && git add secondlook/web.py secondlook/cases.py tests/test_today.py tests/test_cases.py && git diff --cached --name-only && git commit -q -m "Today: the shop's morning read once, the earlier cases included; a case records when it closed" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>" && test -z "$(git status --porcelain)" && echo CLEAN
```

Expected: the four file names, then `CLEAN`.

---

### Task 8: The morning screen `/today`; the Overview shows the same month

**Files:**
- Modify: `secondlook/web.py`: the page section (after Task 7's), `PAGE` (styles before `.api{{…}}`, the logo's link `:1273`), `page` (`:1362-1376`, navigation), `overview_page` (`:1551-1561` and its body), `do_GET` (`:2641`)
- Test: `tests/test_today.py`

- [ ] **Step 1: Write the failing tests.** In `tests/test_today.py`, add above `if __name__ == "__main__":`

```python
def test_the_morning_screen_says_whose_names_and_roles_and_labels_every_estimate():
    with morning():
        html_ = web.today_page("demo", "giulia")
        for words in ("I see", "I manage", "I know", "🛒 141 new orders", "✉️ 2 emails", "📝 1 web form",
                      "PayPal 3 PayPal disputes", "📞 Phone: not connected yet", "<b>Pablo Martin</b>, <i>customer</i>",
                      "<b>Marta</b>, <i>Customer care assistant</i>", "<b>Giulia</b>, <i>Head of customer care</i>",
                      "Second Look's AI", "19 days left", "no PayPal deadline", "This month (October 2026)",
                      "estimated: 23 written answers", "estimated from PayPal&#x27;s fee table", "at most 1,073.00 EUR",
                      "PayPal's high-volume line", 'href="/?shop=demo">Disputes and requests'):
            assert words in html_, words
        assert "Export" not in html_                           # the accounting export comes with step 3, not a dead button
        nav = html_.split("<nav>")[1].split("</nav>")[0]
        assert '<a href="/today?shop=demo" aria-current="page">Today</a>' in nav
        overview = web.overview_page("demo", "giulia")
        assert "This month (October 2026)" in overview and 'href="/today?shop=demo">the morning screen' in overview
        assert overview.count("PayPal's high-volume line") == 1
        assert web.approve("DEMO-034", "REFUND", "You're right: here is your refund.", by="marta")[0] == 202
        assert "passed by Marta, <i>Customer care assistant</i>, to Giulia, <i>Head of customer care</i>" in \
            web.today_page("demo", "giulia")


def test_the_morning_screen_over_http_and_as_data():
    with morning():
        srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            con = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            con.request("GET", "/today?shop=demo&as=marta")
            r = con.getresponse()
            assert r.status == 200 and "Today at Linen &amp; Paper" in r.read().decode()
            con.request("GET", "/api/today?shop=demo")
            r = con.getresponse()
            data = json.loads(r.read())
            assert data["today"] == "2026-10-20" and data["see"]["counts"]["form"] == 1 and data["know"]["requests"] == 64
            con.request("GET", "/today?practice=1")
            r = con.getresponse()
            r.read()
            assert r.status == 303 and r.getheader("Location") == "/?practice=1"
        finally:
            srv.shutdown()
```

- [ ] **Step 2: Run them, see them fail**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && python3 tests/test_today.py 2>&1 | tail -1
```

Expected: `AttributeError: module 'secondlook.web' has no attribute 'today_page'`

- [ ] **Step 3: Implement.** In `secondlook/web.py`, insert immediately above the line `# ---------- the case page: one customer, one order, one problem, every channel ----------` (it follows Task 7's section):

```python
def _hours(minutes: float) -> str:
    h, mm = divmod(int(round(minutes)), 60)
    return f"{h} h {mm} min" if h else f"{mm} min"


def claim_line_box(hv: dict, today, cur: str = "EUR") -> str:
    """PayPal's high-volume line, as the Overview shows it: claims and card chargebacks against sales over PayPal's
    own window (the three previous full months), with the 1.5% line."""
    start, end = ledger.quarter_window(today)
    meter_w = min(100, 100 * hv["ratio"] / 0.02) if hv["sales"] else 0
    return (f'<section class="meter-box"><h2>PayPal\'s high-volume line</h2>'
            f'<p class="who">Claims and card chargebacks against sales, {start:%b}–'
            f'{(end - timedelta(days=1)):%b %Y} (PayPal counts the three previous full months). '
            f'At 1.5% with more than 100 sales, every claim costs {28:,.0f} {cur}, even the ones you win.</p>'
            f'<div class="meter" role="img" aria-label="{hv["ratio"]:.2%} of sales, line at 1.5%">'
            f'<span class="m-fill" style="width:{meter_w:.1f}%"></span><span class="m-line" style="left:75%"><i>1.5%</i></span></div>'
            f'<p><b>{hv["claims"]} claims in {hv["sales"]:,} sales: {hv["ratio"]:.2%}.</b> '
            + ("Above the line." if hv["high_volume"] else f'{hv["claims_to_threshold"]} more claims this quarter and you cross it.')
            + '</p></section>')


def month_block(k: dict, today) -> str:
    """I know: this month, every channel. The same block on the morning screen and on the Overview."""
    cur = k["currency"]
    m = lambda v: f"{v:,.2f} {cur}"  # noqa: E731
    by = ", ".join(f"{n} {word}" for ch, word, n in today_mod.channel_words(k["requests_by_channel"]) if n)
    rows = [("Requests", f'{k["requests"]}', f'in {k["orders"]:,} orders' + (f' · {by}' if by else "")),
            ("Solved before any PayPal dispute", f'{k["solved_before_dispute"]}', "shop inquiries closed this month"),
            ("Staff time", f'{_hours(k["minutes"])}, about {m(k["staff_cost"])}',
             f'estimated: {k["answers"]} written answer{"s" if k["answers"] != 1 else ""} × {k["reply_minutes"]:g} min '
             f'at {k["hourly_cost"]:g} {cur} an hour (your rules)'),
            ("Money given back", m(k["back"]), f'{m(k["back_cases"])} on your own cases (logged), '
                                               f'{m(k["back_paypal"])} through PayPal'),
            ("PayPal dispute fees", m(k["fees"]), "estimated from PayPal's fee table"),
            ("Open cases could still cost", f'at most {m(k["could_still_cost"])}',
             f'every open PayPal dispute lost at claim ({m(k["open_disputes_most"])}) and every open inquiry '
             f'refunded in full ({m(k["open_inquiries_most"])})')]
    trs = "".join(f'<div class="know-row"><dt>{e(a)}</dt><dd><b>{e(b)}</b><span class="t-sub">{e(x)}</span></dd></div>'
                  for a, b, x in rows)
    return (f'<h2>I know</h2><p class="t-sub">This month ({today:%B %Y}), every channel</p>'
            f'<dl class="know">{trs}</dl>')


def _rec(r: dict | None) -> str:
    if not r:
        return ""
    tag = ('<span class="ai-tag">Second Look\'s AI</span>' if r["by"] == "ai" else
           '<span class="ai-tag rules">Rules baseline</span>' if r["by"] == "rules" else "")
    return f'<span class="rec">{tag} {e(r["text"])}</span>'


def see_block(s: dict, q: str) -> str:
    chips = [f'<span class="chip ord">🛒 {s["orders"]:,} new order{"s" if s["orders"] != 1 else ""}</span>']
    for ch, word, n in today_mod.channel_words(s["counts"]):
        if ch == "call":
            chips.append('<span class="chip off">📞 Phone: not connected yet</span>')
            continue
        chips.append(f'<span class="chip">{e(cases_mod.CHANNEL_ICON[ch])} {n} {e(word)}</span>')
    rows = []
    for r in s["rows"]:
        icons = " ".join(cases_mod.CHANNEL_ICON[ch] for ch in r["channels"])
        left = r["days_left"]
        when = ("no PayPal deadline" if left is None else "overdue" if left < 0 else "today" if left == 0
                else f"{left} day{'s' if left != 1 else ''} left")
        due = f'<span class="due{" soft" if left is None else ""}">{e(when)}</span>'
        order = f' · order {e(r["order_no"])}' if r["order_no"] else " · no order"
        rows.append(f'<li><a href="{e(r["link"])}{q}"><span class="chan">{e(icons)}</span>'
                    f'<span class="what"><b>{e(r["who"] or "")}</b>, <i>customer</i> · “{e(r["summary"])}”'
                    f' · {r["amount"]:.2f} EUR{order}{" · closed" if r["status"] != "open" else ""}'
                    f'{_rec(r["review"])}</span>{due}</a></li>')
    listing = (f'<ol class="see">{"".join(rows)}</ol>' if rows else
               '<p class="empty">Nothing new since yesterday.</p>')
    return (f'<h2>I see</h2><p class="t-sub">Everything that came in since yesterday '
            f'({s["since"][8:10]} {datetime.strptime(s["since"][:10], "%Y-%m-%d"):%b}), from every channel, '
            f'nearest PayPal deadline first</p><p class="chips">{"".join(chips)}</p>{listing}')


def manage_block(mg: dict, q: str) -> str:
    if mg["solo"]:
        return (f'<h2>I manage</h2><p class="t-sub">Who has what</p><p>A team of one: all {mg["total"]} open '
                f'case{"s" if mg["total"] != 1 else ""} are yours.</p>')
    rows = []
    for p in mg["people"]:
        n = len(p["items"])
        extra = (f' · {p["passed_on"]} passed on' if p["passed_on"] else "") + \
                (f' · {len(p["waiting"])} waiting for them' if p["waiting"] else "")
        rows.append(f'<div class="know-row"><dt><b>{e(p["name"])}</b>, <i>{e(p["role"])}</i></dt>'
                    f'<dd><b>{n} open case{"s" if n != 1 else ""}</b><span class="t-sub">{e(extra.lstrip(" ·"))}</span></dd></div>')
    rows.append(f'<div class="know-row"><dt><b>Unassigned</b></dt><dd><b>{len(mg["unassigned"])}</b>'
                f'<span class="t-sub">nobody has these yet: open one and take it</span></dd></div>')
    hands = "".join(f'<li><a href="{e(h["link"])}{q}"><b>{e(h["who"] or "")}</b>, <i>customer</i> · {h["amount"]:.2f} EUR: '
                    f'passed by {e(h["from_name"])}' + (f', <i>{e(h["from_role"])}</i>' if h["from_role"] else "")
                    + f', to {e(h["to_name"])}, <i>{e(h["to_role"])}</i></a></li>' for h in mg["handoffs"])
    waits = (f'<h3 class="bl-h">Waiting after a handoff</h3><ul class="see">{hands}</ul>' if hands else
             '<p class="t-sub">No handoff is waiting.</p>')
    return (f'<h2>I manage</h2><p class="t-sub">Who has what, and what waits for whom</p><dl class="know">{"".join(rows)}</dl>'
            f'{waits}<p class="t-sub">Nothing goes out until a person approves it, each within their own limit.</p>')


def today_page(src: str, me: str | None = None) -> str:
    demo = src == "demo"
    v = today_view(src)
    q = "?shop=demo" if demo else ""
    name = DemoPayPal().shop["name"] if demo else _live_shop().get("name") or "Your shop"
    about = f'<p class="demo-note">{e(DemoPayPal().shop["about"])}</p>' if demo else ""
    body = (f'<h1 class="page">Today at {e(name)}</h1>{about}'
            f'<p class="who">I see, I manage, I know: every channel, one place. The lists stay where they were: '
            f'<a href="/{q}">Disputes and requests</a> · <a href="/overview{q}">Overview</a></p>'
            f'<div class="blocks"><section class="block">{see_block(v["see"], q)}</section>'
            f'<section class="block">{manage_block(v["manage"], q)}</section>'
            f'<section class="block">{month_block(v["know"], v["today"])}'
            f'{claim_line_box(v["know"]["high_volume"], v["today"])}</section></div>')
    return page(f"Today | Second Look", "PayPal sandbox", body, demo, me=me, here="today")
```

The styles (in `PAGE`, before `.api{{…}}`):

Replace:

```python
.api{{margin-top:40px}}
```

with:

```python
.blocks{{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr) minmax(0,1fr);gap:24px;align-items:start;margin-top:18px}}
.block{{background:#fff;border:1px solid var(--rule);padding:18px 20px}} .block.wide{{max-width:1100px;margin:0 0 30px}}
.block h2{{margin:0 0 2px}} .block > .t-sub{{display:block;margin:0 0 12px}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 12px}} .chip{{font-size:14px;padding:3px 10px;border-radius:14px;background:#EEF2F4}}
.chip.ord{{background:#E8F0EA}} .chip.off{{color:var(--soft);background:transparent;border:1px dashed var(--rule)}}
ol.see,ul.see{{list-style:none;padding:0;margin:0}} .see li a{{display:grid;grid-template-columns:auto 1fr auto;gap:10px;padding:9px 0;border-top:1px solid var(--rule);text-decoration:none;font-size:15px}}
.see .rec{{display:block;color:var(--soft)}} .due{{color:var(--incon);font-weight:700;white-space:nowrap}} .due.soft{{color:var(--soft);font-weight:400}}
.ai-tag.rules{{border-color:var(--unclear);color:var(--soft)}}
dl.know{{margin:0}} .know-row{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.3fr);gap:12px;padding:8px 0;border-top:1px solid var(--rule)}}
.know-row dt{{color:var(--ink)}} .know-row dd{{margin:0}} .know-row dd b{{display:block}}
@media (max-width:1100px){{.blocks{{grid-template-columns:1fr}}}}
.api{{margin-top:40px}}
```

The logo leads to the shop's first page, and the navigation starts there:

Replace:

```python
<a class="brand" href="/">
```

with:

```python
<a class="brand" href="/today">
```

Replace:

```python
    """`here`: the section the page belongs to ("disputes", "overview" or "rules"), said by the page itself.
```

with:

```python
    """`here`: the section the page belongs to ("today", "disputes", "overview" or "rules"), said by the page itself.
```

Replace:

```python
    nav = (f'<nav><a href="/{q}"{cur("disputes")}>Disputes</a><a href="/overview"{cur("overview")}>Overview</a>'
```

with:

```python
    nav = (f'<nav><a href="/today{q}"{cur("today")}>Today</a><a href="/{q}"{cur("disputes")}>Disputes</a>'
           f'<a href="/overview"{cur("overview")}>Overview</a>'
```

The Overview: the same claim-line box, and the month figures on top:

Replace:

```python
    meter_w = min(100, 100 * hv["ratio"] / 0.02) if hv["sales"] else 0
    meter = (f'<section class="meter-box"><h2>PayPal\'s high-volume line</h2>'
             f'<p class="who">Claims and card chargebacks against sales, {ov["quarter"][0]:%b}–'
             f'{(ov["quarter"][1] - timedelta(days=1)):%b %Y} (PayPal counts the three previous full months). '
             f'At 1.5% with more than 100 sales, every claim costs {m(28)}, even the ones you win.</p>'
             f'<div class="meter" role="img" aria-label="{hv["ratio"]:.2%} of sales, line at 1.5%">'
             f'<span class="m-fill" style="width:{meter_w:.1f}%"></span><span class="m-line" style="left:75%"><i>1.5%</i></span></div>'
             f'<p><b>{hv["claims"]} claims in {hv["sales"]:,} sales: {hv["ratio"]:.2%}.</b> '
             + ("Above the line." if hv["high_volume"] else f'{hv["claims_to_threshold"]} more claims this quarter and you cross it.')
             + '</p></section>')
```

with:

```python
    meter = claim_line_box(hv, today, cur)      # the same box as the morning screen's
    # every channel this month, as the morning screen counts it: one function, one set of numbers, two places
    month = month_block(today_mod.month(shop_cases(src), disputes, shop_orders(src), today, _policy(),
                                        sent_answers(src), cur), today)
```

Replace:

```python
            + overview_whatnow(ov)
            + f'<div class="kpis">{kpis}</div>'
```

with:

```python
            + overview_whatnow(ov)
            + f'<section class="block wide">{month}<p class="cost-note">The figures above are every channel, this month; '
              f'<a href="/today{q}">the morning screen</a> shows them with what came in since yesterday. Below: PayPal '
              f'disputes only, over the last {ov["window_days"]} days.</p></section>'
            + f'<div class="kpis">{kpis}</div>'
```

The routes, in `do_GET`:

Replace:

```python
            if u.path == "/overview":
                return self._send(overview_page(src, me=me))
```

with:

```python
            if u.path == "/today":
                if src == "practice":
                    return self._redirect("/?practice=1")    # practice cases are a test bench, not a shop's morning
                return self._send(today_page(src, me=me))
            if u.path == "/api/today":
                v = today_view("live" if src == "live" else "demo")
                return self._json({"today": v["today"], "see": v["see"], "manage": v["manage"], "know": v["know"]})
            if u.path == "/overview":
                return self._send(overview_page(src, me=me))
```

- [ ] **Step 4: Run the tests**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && python3 tests/test_today.py | tail -1
```

Expected: `8 passed`

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && for f in tests/test_*.py; do python3 $f | tail -1; done
```

Expected: cases `11`, demo_shop `13`, guard `33`, helpdesk `36`, inquiry `39`, intake `27`, ledger `11`, sort `15`, team `16`, today `8`, web `67` (276).

- [ ] **Step 5: Commit**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && git add secondlook/web.py tests/test_today.py && git diff --cached --name-only && git commit -q -m "Today: the morning screen, I see, I manage, I know; the Overview shows the same month" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>" && test -z "$(git status --porcelain)" && echo CLEAN
```

Expected: the two file names, then `CLEAN`.

---

### Task 9: README: the morning screen, the titles

**Files:**
- Modify: `README.md` (the screen list `:108`, the demo shop `:119`, the API table `:141`, Teams `:238`, Try it `:299-305`)

- [ ] **Step 1: The screen list.** In `README.md`:

Replace:

```markdown
- **Overview** (`/overview`): the last 90 days at a glance, from PayPal's own outcome codes: won,
```

with:

```markdown
- **Today** (`/today`), the shop's first page, in three blocks. *I see*: everything that came in since
  yesterday, every channel in one list (email, web form, PayPal disputes; calls arrive in a later step),
  each matched to its order with Second Look's recommendation in one line, nearest PayPal deadline first,
  and the new orders beside it. *I manage*: who has which open case, with their role, what nobody has
  yet, and what waits after a handoff. *I know*: this month, every channel: requests, solved before any
  PayPal dispute, staff time (estimated), money given back, fees, what the open cases could still cost,
  and PayPal's claim line. The same month figures head the Overview.
- **Overview** (`/overview`): the last 90 days at a glance, from PayPal's own outcome codes: won,
```

- [ ] **Step 2: The titles.**

Replace:

```markdown
  customer care team of four (Giulia, manager; Marta, Luca and Sara, agents who send refunds up to
```

with:

```markdown
  customer care team of four (Giulia, head of customer care; Marta, Luca and Sara, customer care assistants, who send refunds up to
```

Replace:

```markdown
- **Over your limit, the case passes on.** An agent who approves a refund above their limit sends
```

with:

```markdown
- **Over your limit, the case passes on.** A customer care assistant who approves a refund above their limit sends
```

Replace:

```markdown
- **Pick who you are**, at the top of the page: *Giulia*, the manager, may send any amount the
  limits hand to a person; *Marta*, an agent, sends refunds up to 30 EUR.
```

with:

```markdown
- **Pick who you are**, at the top of the page: *Giulia*, head of customer care, may send any amount the
  limits hand to a person; *Marta*, a customer care assistant, sends refunds up to 30 EUR.
```

- [ ] **Step 3: Try it starts on the morning screen.**

Replace:

```markdown
Open http://127.0.0.1:8765/?shop=demo. This is "Linen & Paper", a made-up shop with a customer care
```

with:

```markdown
Open http://127.0.0.1:8765/today?shop=demo: the morning screen, with what came in since yesterday
(made-up data: the demo shop's today is 20 Oct 2026), who has what, and the month so far. The
Disputes list is one click away (http://127.0.0.1:8765/?shop=demo). This is "Linen & Paper", a made-up shop with a customer care
```

- [ ] **Step 4: The API.** Above the `POST /api/requests` row:

Replace:

```markdown
| `POST /api/requests` | `{"channel"
```

with:

```markdown
| `GET /api/today` | the morning screen as data: `see` (what came in since yesterday, one row per problem, with `counts` by channel and the new `orders`), `manage` (who has which open case, with roles; unassigned; handoffs) and `know` (this month: requests, solved before any dispute, staff time and its estimate's inputs, money given back, fees, what open cases could still cost, PayPal's claim line) |
| `POST /api/requests` | `{"channel"
```

- [ ] **Step 5: Commit**

```bash
cd /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look && git add README.md && git diff --cached --name-only && git commit -q -m "README: the morning screen; the team's new titles; /api/today" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>" && test -z "$(git status --porcelain)" && echo CLEAN
```

Expected: `README.md`, then `CLEAN`.

---

### Task 10: Proof that nothing PayPal-side moved, and a judge's fresh clone

**Files:** none changed.

- [ ] **Step 1: The 12 open disputes read exactly as before** (the same snapshot as in "Before you start", now on the branch):

```bash
S=/private/tmp/claude-501/-Users-claudiamauri-Desktop-hackathons-paypal-ai/7fe40038-1fc8-4bbd-a54c-d74e1e02ecd1/scratchpad
python3 "$S/disputes_snapshot.py" /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look > "$S/snap-after-morning.json" 2> "$S/snap-after-morning.err"
cmp "$S/snap-before-morning.json" "$S/snap-after-morning.json" && echo SNAPSHOT-IDENTICAL
```

Expected: `SNAPSHOT-IDENTICAL`: every open dispute's records, the guard's decision on its saved review, and the API's answer for every person are byte-for-byte the same.

- [ ] **Step 2: The ports are free** (if either prints a number, pick two other free ports and use them below):

```bash
lsof -tiTCP:8793 -sTCP:LISTEN; lsof -tiTCP:8794 -sTCP:LISTEN; echo checked
```

Expected: only `checked`.

- [ ] **Step 3: Clone the branch and start both apps, with no AI key**

```bash
S=/private/tmp/claude-501/-Users-claudiamauri-Desktop-hackathons-paypal-ai/7fe40038-1fc8-4bbd-a54c-d74e1e02ecd1/scratchpad
rm -rf "$S/fresh-clone-morning" && git clone -q --branch morning-screen /Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look "$S/fresh-clone-morning"
cd "$S/fresh-clone-morning"
(env -u ANTHROPIC_API_KEY python3 -c "from secondlook.web import serve; serve(8793)" > "$S/sl-m.log" 2>&1 & echo $! > "$S/sl-m.pid")
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do curl -s -o /dev/null http://127.0.0.1:8793/favicon.ico && break; python3 -c "import time; time.sleep(0.5)"; done; echo up
```

Expected: `up`. (Ticketbook isn't started yet, so Second Look holds only the demo's own requests: 2 emails, 1 web form.)

- [ ] **Step 4: The morning screen, its data and the Overview**

```bash
curl -s "http://127.0.0.1:8793/api/today?shop=demo" | python3 -c "import json,sys; v=json.load(sys.stdin); s,k=v['see'],v['know']; print(s['since'], s['orders'], s['counts']); print([r['link'] for r in s['rows']]); print(k['requests'], k['solved_before_dispute'], k['answers'], k['back'], k['could_still_cost']); print([(p['name'], p['role'], len(p['items'])) for p in v['manage']['people']])"
```

Expected:

```
2026-10-19T00:00 141 {'call': 0, 'email': 2, 'form': 1, 'paypal': 3}
['/c/DEMO-C003', '/d/DEMO-039', '/d/DEMO-036', '/c/DEMO-C001', '/c/DEMO-C002']
64 31 23 314.7 1073.0
[('Giulia', 'Head of customer care', 0), ('Marta', 'Customer care assistant', 3), ('Luca', 'Customer care assistant', 2), ('Sara', 'Customer care assistant', 0)]
```

```bash
curl -s "http://127.0.0.1:8793/today?shop=demo&as=giulia" | grep -o "Phone: not connected yet\|I manage\|This month (October 2026)\|Head of customer care\|Second Look&#x27;s AI\|Second Look's AI" | sort -u; curl -s "http://127.0.0.1:8793/overview?shop=demo" | grep -o "the morning screen" | head -1; curl -s -o /dev/null -w '%{http_code} /\n' "http://127.0.0.1:8793/?shop=demo"
```

Expected: the five page phrases, `the morning screen` (the Overview's link), then `200 /` (the Disputes list is where it was).

- [ ] **Step 5: "Your call" is refused through the API** (DEMO-034's shipped review is "your call"; nothing is sent):

```bash
curl -s -X POST -H 'Content-Type: application/json' -d '{"action": "ASK_SELLER", "by": "giulia"}' "http://127.0.0.1:8793/api/cases/DEMO-C003/approve"; echo
```

Expected: a JSON answer whose `result` is `"Your call" is not an answer: choose what to send (a reply, a refund, your evidence).`, answered with 400.

- [ ] **Step 6: Ticketbook joins: its dispute emails arrive, and it signs in with the role**

```bash
S=/private/tmp/claude-501/-Users-claudiamauri-Desktop-hackathons-paypal-ai/7fe40038-1fc8-4bbd-a54c-d74e1e02ecd1/scratchpad
cd "$S/fresh-clone-morning"
(env -u ANTHROPIC_API_KEY python3 -m helpdesk serve --port 8794 --secondlook http://127.0.0.1:8793 > "$S/tb-m.log" 2>&1 & echo $! > "$S/tb-m.pid")
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do curl -s -o /dev/null http://127.0.0.1:8794/ && break; python3 -c "import time; time.sleep(0.5)"; done
python3 -c "import time; time.sleep(3)"; echo up
```

```bash
curl -s "http://127.0.0.1:8794/?as=marta" | grep -o "Signed in as <b>Marta</b>, Customer care assistant" | head -1; curl -s "http://127.0.0.1:8793/api/today?shop=demo" | python3 -c "import json,sys; print(json.load(sys.stdin)['see']['counts'])"
```

Expected: `Signed in as <b>Marta</b>, Customer care assistant`, then `{'call': 0, 'email': 4, 'form': 1, 'paypal': 3}`. Ticketbook handed over its open tickets; two of them are emails since yesterday about DEMO-039 and DEMO-036, and they join those disputes' rows.

- [ ] **Step 7: Stop both servers by their process ids; the ports are free again**

```bash
S=/private/tmp/claude-501/-Users-claudiamauri-Desktop-hackathons-paypal-ai/7fe40038-1fc8-4bbd-a54c-d74e1e02ecd1/scratchpad
kill "$(cat "$S/sl-m.pid")" "$(cat "$S/tb-m.pid")"; python3 -c "import time; time.sleep(1)"
lsof -tiTCP:8793 -sTCP:LISTEN; lsof -tiTCP:8794 -sTCP:LISTEN; echo stopped
```

Expected: only `stopped`.

---

## After this plan

- Ask Claudia before merging `morning-screen` into main and before pushing.
- Update `HANDOVER.md` and append to `LOG.md`:
  - the definitions of "since yesterday" and "this month";
  - the spec's "8 new orders" against the demo's 141;
  - "Not reviewed yet" on a fresh clone's inquiry rows until the paid demo-inquiry reviews ship (Claudia's OK);
  - `ASK_SELLER` refused.
- Step 3 next: calls (the phone chip gets its count), orders/courier stand-ins, accounting (the export goes in I know), PayPal's refund API.

## Self-review (against the spec and the brief)

- **Spec §2, I see:**
  - since yesterday, every channel in one list (`came_in`, Tasks 5, 7);
  - each row matched to its order, with Second Look's AI's or the rules baseline's recommendation in one line, labelled (`review_line`, Task 7);
  - nearest PayPal deadline first, new orders counted beside it (Tasks 5, 8);
  - the call chip is honest: "Phone: not connected yet" (decision 8).
- **I manage:** who has which open case (disputes and inquiries, once each), with roles; unassigned; what waits after a handoff, with both names and roles (`who_has`, Tasks 6, 7, 8).
- **I know:** this month, every channel (`month`, Task 6):
  - requests;
  - solved before any dispute;
  - staff time, estimated and labelled;
  - money given back, logged refunds plus PayPal refunds;
  - fees;
  - what the open cases could still cost;
  - PayPal's claim line, the Overview's own meter (Task 8);
  - no export button.
- **Overview's all-channel figures:** the same `month_block` on top of the Overview, linked to `/today` (decision 4, Task 8). The Disputes list and the Overview stay, linked from `/today`.
- **Decision 7, roles:** renamed in the data, the fixtures, Ticketbook and the README (Tasks 1, 2, 9). Names carry their role in owner tags, owner lines, Ticketbook's sign-in, I manage and I see's customers (Tasks 2, 8). The film is not touched; the capture script's assertions hold (decision 5).
- **Spec §4, past months:** the earlier cases, from a new stream (Task 4). The PayPal side is unchanged: the fingerprint and determinism tests (Task 4), and the 12-dispute snapshot (Task 10).
- **Brief, item 3:** `ASK_SELLER` refused with 400 (Task 3, and through the API in Task 10).
- **No placeholders:** every code step shows its code; every command shows its expected output. The plan was replayed task by task from main (c3fc6fc) in a scratch clone, and every expected output above is what that replay printed.
- **Names:**
  - `today.since/month_start/came_in/open_items/who_has/month/channel_words`;
  - `web.shop_cases/review_line/sent_answers/today_view/claim_line_box/month_block/see_block/manage_block/today_page`;
  - `DemoPayPal.history`; case field `closed_at`.

  Each is used as defined across tasks.
