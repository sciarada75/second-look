# The morning screen, Numbers, and answered requests that close themselves: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/today` answers "what needs me?" per person; every figure moves to a new `/numbers` page that compares
this week or month so far with the same days before; an answered shop request closes itself after 3 quiet days;
the demo's first-load answer is stamped on the demo morning's clock.

**Spec:** `docs/specs/2026-10-27-morning-and-numbers-design.md` (read it first).

**Architecture:** Counting stays in `secondlook/today.py` (pure functions over cases, disputes, orders): `month()`
becomes a thin wrapper over a new `period(start, end)`, plus `windows()`, `weeks()` and `needs_you()`. The time
"now" gets one seam in `secondlook/cases.py` (`CLOCK`, `clock()`, `now()`). Pages and routes stay in
`secondlook/web.py`, which is one big file by design: follow its idiom (f-string HTML, `e()` escaping, the `PAGE`
template whose CSS braces are doubled `{{ }}`).

**Tech stack:** Python 3.9, standard library only. Tests are plain scripts (`python3 tests/test_x.py` runs every
`test_` function in the file). No pytest. No paid call, no network: the test benches patch the AI out.

**House rules for every task:**
- Work in the worktree you were given; never touch `/Users/claudiamauri/Desktop/hackathons/paypal-ai/second-look`
  itself, `.env`, or ports 8765/8766/8767.
- Stage files **by name** (`git add path1 path2`), never `git add -A` or `git add .`. Check `git diff --cached --stat`
  before committing.
- Every commit message ends with a blank line and
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Match the comment style: short docstrings in plain English saying *why*, no type-hint noise beyond what the file
  already uses.
- Run one test function: `python3 -c "import sys; sys.path[:0]=['tests','.']; import test_today as t; t.test_name()"`.
- Run the whole suite: `for f in tests/test_*.py; do python3 "$f" >/dev/null || echo "FAIL $f"; done` (prints nothing
  when all pass). Before this plan: 394 tests, all passing.

---

## File map

| File | Change |
|---|---|
| `secondlook/cases.py` | `CLOCK`, `clock()`, `now()`; `minute(None)` uses `now()`; new `closes_on()` |
| `secondlook/today.py` | new `period()`, `windows()`, `weeks()`, `needs_you()`, `NEAR_LINE`; `month()` wraps `period()`; `open_items()` gains `today` |
| `secondlook/autopilot.py` | `Record.looks_right()` |
| `secondlook/web.py` | demo clock at first load; `shop_today`, `quiet_days`, `close_quiet`, `_closes_words`; `records_from`, `numbers_view`, `numbers_page`; `autopilot_looks_right`, `ai_check_form`, `_back_to`; `today_view(src, me)`, `needs_block`, `see_block`, `team_block`, `today_page`; routes `/numbers`, `/api/numbers`, `/overview` redirect, `POST /autopilot/looks-right`; removes `overview_page`, `overview_whatnow`, `month_block`, `manage_block`, `handled_block` |
| `policy.json` | `"close_answered_after_days": 3` |
| `demo/make_demo.py`, `demo/shop.json` | the shop block gains `"records_from": "2026-09-01"` |
| `tests/test_closing.py` | new |
| `tests/test_numbers.py` | new |
| `tests/test_today.py`, `tests/test_autopilot.py`, `tests/test_web.py` | updated as each task says |

---

### Task 0: Baseline

- [ ] **Step 1: Record the 12-dispute snapshot before any change**

```bash
SP=/private/tmp/claude-501/-Users-claudiamauri-Desktop-hackathons-paypal-ai/7fe40038-1fc8-4bbd-a54c-d74e1e02ecd1/scratchpad
python3 $SP/disputes_snapshot.py "$PWD" > $SP/mn-snap-base.json
for f in tests/test_*.py; do python3 "$f" >/dev/null || echo "FAIL $f"; done
```
Expected: the snapshot file is written; the suite prints nothing.

---

### Task 1: The demo morning's clock

The demo's first load answers Margot (DEMO-C004) and steps back from Sophie (DEMO-C001) at the computer's time
(27 Oct), while the demo's today is 20 Oct. Every Second Look timestamp comes from `cases.minute(None)` except the
approval's local `now` in `web.approve` and the autopilot's daily count. One seam fixes all three.

**Files:** Modify `secondlook/cases.py:22,60-67`, `secondlook/web.py` (`case_store`, `autopilot_soon`, `_approve`'s
`now = datetime.now()`, `_autopilot_case`'s `day = datetime.utcnow()...`). Test: `tests/test_autopilot.py`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_autopilot.py`, before the `if __name__` block)

```python
def test_the_demo_s_first_load_answers_on_the_demo_morning_s_clock():
    from secondlook import cases as cases_mod
    with morning() as b:
        margot = web.case_store("demo").get("DEMO-C004")
        assert margot["timeline"][-1]["at"] == "2026-10-20T07:41"            # a minute after her email, on 20 Oct
        assert web.autopilot_store("demo").view()["cases"]["DEMO-C004"]["at"] == "2026-10-20T07:41"
        assert web.case_store("demo").get("DEMO-C001")["timeline"][-1]["at"] == "2026-10-20T07:41"  # Sophie's step back
        log = [json.loads(x) for x in (b.tmp / "actions-demo.jsonl").read_text().splitlines()]
        assert [x["ts"] for x in log] == ["2026-10-20T07:41"]
        assert web._utc_minute(web._raw("DEMO-C004")["at"]) == "2026-10-20T07:41"
    assert cases_mod.CLOCK.at is None                                          # the clock goes back after the first load


def test_a_look_in_its_own_thread_keeps_the_clock_of_whoever_asked():
    from secondlook import cases as cases_mod
    seen = []
    kept_run, kept_look = web.AUTOPILOT_RUN, web._look
    with morning():
        web.case_store("demo")                                                 # the first load, done
        web.AUTOPILOT_RUN = web._in_a_thread
        web._look = lambda src, did: seen.append(cases_mod.minute(None))
        try:
            with cases_mod.clock("2026-10-20T07:41"):
                th = web.autopilot_soon("demo", "inquiry", "not_received", "DEMO-C004")
            th.join(5)
        finally:
            web.AUTOPILOT_RUN, web._look = kept_run, kept_look
    assert seen == ["2026-10-20T07:41"]
    assert cases_mod.minute(None) != "2026-10-20T07:41"                        # this thread's clock: the computer's
```

- [ ] **Step 2: Run them, expect FAIL**

Run: `python3 -c "import sys; sys.path[:0]=['tests','.']; import test_autopilot as t; t.test_the_demo_s_first_load_answers_on_the_demo_morning_s_clock()"`
Expected: AssertionError on the first `at` (it reads today's real date).

- [ ] **Step 3: The seam in `secondlook/cases.py`**

Change the imports (line 21-22) to:

```python
import re
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta
```

Replace `minute()` (lines 60-67) with:

```python
class _Clock(threading.local):
    """A fixed "now" for this thread ("2026-10-20T07:41"), or None: the computer's. The demo's first load sets the demo
    morning's (web.case_store), so what Second Look's AI does that morning reads as that morning."""
    at = None


CLOCK = _Clock()


@contextmanager
def clock(at: str | None):
    was, CLOCK.at = CLOCK.at, at
    try:
        yield
    finally:
        CLOCK.at = was


def now() -> datetime:
    """Now in UTC, as Second Look stamps it: this thread's clock when one is set, else the computer's."""
    return datetime.strptime(CLOCK.at, "%Y-%m-%dT%H:%M") if CLOCK.at else datetime.utcnow()


def minute(iso=None) -> str:
    """'2026-10-19T08:52:00Z' -> '2026-10-19T08:52', the way Second Look saves times. Unreadable or none: now (UTC)."""
    for fmt, n in (("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%dT%H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(str(iso)[:n], fmt).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            continue
    return now().strftime("%Y-%m-%dT%H:%M")
```

(`date` and `timedelta` are for Task 2's `closes_on`; adding them now keeps one import edit.)

- [ ] **Step 4: The approval's local time and the daily count in `secondlook/web.py`**

Add, just above `def _a_person_s(` (near the other autopilot helpers):

```python
def _local_now() -> datetime:
    """Now in local time, as an approval shows it ("Sent by Giulia, 11:47"): the demo morning's when its clock is set."""
    if cases_mod.CLOCK.at:
        return cases_mod.now().replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    return datetime.now()
```

In the approval (the line `    now = datetime.now()` right after `need = required(chosen, dec, case["dispute"])`),
replace it with `    now = _local_now()`.

In `_autopilot_case`, replace `    day = datetime.utcnow().strftime("%Y-%m-%d")` with
`    day = cases_mod.now().strftime("%Y-%m-%d")`.

- [ ] **Step 5: A look keeps its asker's clock** — in `autopilot_soon`, replace the last line
`    return AUTOPILOT_RUN(lambda: _look(src, did))` with:

```python
    at = cases_mod.CLOCK.at                       # a look in its own thread keeps the clock of whoever asked for it

    def look():
        with cases_mod.clock(at):
            return _look(src, did)
    return AUTOPILOT_RUN(look)
```

- [ ] **Step 6: The first load runs on the demo morning's clock** — in `case_store`, replace:

```python
        try:
            for th in [autopilot_after("demo", store.get(cid)) for cid in dict.fromkeys(filed)]:
                if th is not None:
                    th.join(10)
        finally:
            mine.set()
```
with:
```python
        # ... on the demo morning's own clock: a minute after the last request came in (Margot's, 07:40 on 20 Oct)
        heard = [x["at"] for c in store.all() for x in c["timeline"] if x.get("direction") == "in" and x.get("at")]
        morning = ((datetime.strptime(max(heard), "%Y-%m-%dT%H:%M") + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M")
                   if heard else None)
        try:
            with cases_mod.clock(morning):
                for th in [autopilot_after("demo", store.get(cid)) for cid in dict.fromkeys(filed)]:
                    if th is not None:
                        th.join(10)
        finally:
            mine.set()
```
Also extend the comment above that `try` (the one beginning "Second Look's AI looks at the morning once it is all
filed") by nothing else: the new comment line above covers it.

- [ ] **Step 7: Run the two tests, then the files they touch**

Run: the two functions as in Step 2, then `python3 tests/test_autopilot.py && python3 tests/test_today.py && python3 tests/test_inquiry.py`
Expected: all pass. (`test_today`'s `"Handled by Second Look's AI · reply sent by email"` is unchanged.)

- [ ] **Step 8: Commit**

```bash
git add secondlook/cases.py secondlook/web.py tests/test_autopilot.py
git commit -m "The demo's first load answers on the demo morning's clock: one seam for now (cases.CLOCK), carried into a look's own thread

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: An answered request closes itself

**Files:** Modify `secondlook/cases.py` (add `closes_on`), `secondlook/web.py` (`shop_today`, `quiet_days`,
`close_quiet`, `_closes_words`; `today_view` and `inbox_page` and `case_file_page` call `close_quiet`; the case page
shows the closing line; the Rules page states the rule), `policy.json`. Create `tests/test_closing.py`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_closing.py`:

```python
"""An answered shop request closes itself, as solved before any dispute, once the customer stays quiet for the shop's
days (policy.json "close_answered_after_days", 3). Code, not AI. Run: python3 tests/test_closing.py"""
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from secondlook import cases as cases_mod, web  # noqa: E402
from test_inquiry import morning  # noqa: E402  the demo's real data, its state in a temporary folder, no paid call


@contextmanager
def on_day(d):
    """The shop's today, moved: the demo's is 20 Oct."""
    kept = web.shop_today
    web.shop_today = lambda src: d
    try:
        yield
    finally:
        web.shop_today = kept


def case(*entries, **extra):
    return {"id": "C1", "status": "open", "dispute_id": None, "money": [], "customer": {"name": "Ann Lee"},
            "timeline": [{"at": at, "direction": way, "channel": "email", "text": "…"} for at, way in entries], **extra}


def test_the_day_it_closes_is_days_after_the_shop_s_reply_when_that_reply_is_the_last_word():
    c = case(("2026-10-20T07:40", "in"), ("2026-10-20T07:41", "out"))
    assert cases_mod.closes_on(c, 3) == date(2026, 10, 23)
    assert cases_mod.closes_on(case(("2026-10-20T07:40", "in"), ("2026-10-20T07:41", "out"), ("2026-10-21T09:00", "note")), 3) \
        == date(2026, 10, 23)                                                  # a note is nobody's word
    assert cases_mod.closes_on(case(("2026-10-20T07:40", "in")), 3) is None                      # not answered yet
    assert cases_mod.closes_on(case(("2026-10-20T07:40", "in"), ("2026-10-20T07:41", "out"),
                                    ("2026-10-21T09:00", "in")), 3) is None                      # the customer wrote again
    assert cases_mod.closes_on(case(("2026-10-20T07:40", "in"), ("2026-10-20T07:41", "out"), dispute_id="D1"), 3) is None
    assert cases_mod.closes_on(case(("2026-10-20T07:40", "in"), ("2026-10-20T07:41", "out"),
                                    money=[{"kind": "refund", "amount": 5.0}]), 3) is None       # a person closes those
    assert cases_mod.closes_on(case(("2026-10-20T07:40", "in"), ("2026-10-20T07:41", "out"), status="closed"), 3) is None


def test_margot_s_answered_request_closes_itself_on_the_third_quiet_day_signed():
    with morning():
        assert web.close_quiet("demo") == []                                   # the demo's today: 20 Oct
        with on_day(date(2026, 10, 22)):
            assert web.close_quiet("demo") == []                               # two quiet days: still open
        with on_day(date(2026, 10, 23)):
            assert web.close_quiet("demo") == ["DEMO-C004"]
            assert web.close_quiet("demo") == []                               # once
        c = web.case_store("demo").get("DEMO-C004")
        assert (c["status"], c["outcome"], c["closed_by"]) == ("closed", "solved", "Second Look")
        assert c["closed_at"]
        note = c["timeline"][-1]
        assert (note["direction"], note["by"], note["text"]) == ("note", "Second Look",
                                                                 "Closed by Second Look: no reply in 3 days.")
        assert "Solved before any dispute" in web.case_file_page("DEMO-C004", me="giulia")


def test_the_shop_s_setting_sets_the_days():
    kept = web._policy
    try:
        web._policy = lambda: {**kept(), "close_answered_after_days": 5}
        assert web.quiet_days() == 5
        for bad in (0, -2, "3", 2.5, True, None):
            web._policy = lambda: {**kept(), "close_answered_after_days": bad}
            assert web.quiet_days() == 3, bad
    finally:
        web._policy = kept
    assert "after 3 days with no word from the customer" in web.rules_page(demo=True, me="giulia")


def test_a_look_at_the_shop_closes_what_is_due_and_the_customer_s_next_message_opens_a_new_case():
    with morning():
        assert "Answered · closes on 23 Oct if Margot doesn&#x27;t write" in web.case_file_page("DEMO-C004", me="giulia")
        with on_day(date(2026, 10, 23)):
            web.today_view("demo")                                             # the morning screen's look closes it
        assert web.case_store("demo").get("DEMO-C004")["status"] == "closed"
        code, out = web.receive("demo", {"channel": "email", "from": {"name": "Margot Lefèvre",
                                                                     "email": "margot.lefevre@example.com"},
                                         "text": "The napkins never came. Order LP-90003.", "source_id": "test:margot2"})
        assert code == 201 and out["case_id"] != "DEMO-C004"
        assert web.case_store("demo").get(out["case_id"])["earlier_case"] == "DEMO-C004"


def test_the_customer_writing_before_the_day_keeps_it_open():
    with morning():
        web.case_store("demo").add("DEMO-C004", cases_mod.entry("2026-10-21T08:00", "email", "in", "Still nothing?",
                                                               "Margot Lefèvre"))
        with on_day(date(2026, 10, 30)):
            assert web.close_quiet("demo") == []
        assert web.case_store("demo").get("DEMO-C004")["status"] == "open"


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
```

Before running: check `CaseStore.add(cid, entry)` exists with that signature (`grep -n "def add" secondlook/cases.py`);
`web.autopilot_differently` already uses `case_store(src).add(c["id"], cases_mod.entry(...))`, so it does.

- [ ] **Step 2: Run, expect FAIL** — `python3 tests/test_closing.py` → `AttributeError: ... 'closes_on'`.

- [ ] **Step 3: `closes_on` in `secondlook/cases.py`** (add after `entry()`):

```python
def closes_on(c: dict, days: int) -> date | None:
    """The day an answered request closes itself if the customer stays quiet: `days` after the shop's last reply, when
    that reply is the case's last word (notes are nobody's word). None when it never closes on its own: a PayPal
    dispute (PayPal closes those), a closed case, no reply yet, the customer wrote after it, or money or goods logged
    on it (a person closes those with what happened: refunded, replaced)."""
    if c.get("status") != "open" or c.get("dispute_id") or c.get("money"):
        return None
    words = sorted((x for x in c.get("timeline", []) if x.get("direction") in ("in", "out") and x.get("at")),
                   key=lambda x: x["at"])                    # stable: an answer in the same minute stays after the question
    if not words or words[-1]["direction"] != "out":
        return None
    return date.fromisoformat(words[-1]["at"][:10]) + timedelta(days=days)
```

- [ ] **Step 4: The rule in `secondlook/web.py`**

Add right after `_close()` (the function `close_case` calls):

```python
def shop_today(src: str):
    """The shop's today: the demo's is fixed (20 Oct 2026); a live shop's is the computer's, in UTC."""
    return DemoPayPal().today if src == "demo" else datetime.utcnow().date()


def quiet_days() -> int:
    """policy.json "close_answered_after_days": an answered request closes itself after this many days with no word
    from the customer. 3 when it isn't a whole number of 1 or more."""
    v = _policy().get("close_answered_after_days")
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else 3


def close_quiet(src: str) -> list:
    """Every answered request whose customer stayed quiet for the shop's days closes itself, as solved before any
    dispute, signed (cases.closes_on). Code, not AI. Run at each look at the shop's cases, against the shop's today:
    no timer. Each case is checked again under its lock: a customer who just wrote keeps it open."""
    if src not in CASE_FILES:
        return []
    days, today, store, done = quiet_days(), shop_today(src), case_store(src), []
    for c in store.all():
        on = cases_mod.closes_on(c, days)
        if on is None or on > today:
            continue
        with _case_lock(c["id"]):
            x = store.get(c["id"])
            on = cases_mod.closes_on(x, days) if x else None
            if on is None or on > today:
                continue

            def close(y):
                y["status"], y["outcome"], y["closed_at"], y["closed_by"] = "closed", "solved", cases_mod.minute(None), "Second Look"
                y["timeline"].append(cases_mod.entry(None, reply_channel(y), "note",
                                                     f"Closed by Second Look: no reply in {days} days.", "Second Look"))
            store.update(c["id"], close)
            done.append(c["id"])
    return done


def _closes_words(c: dict | None) -> str:
    """"Answered · closes on 23 Oct if Margot doesn't write", or "" when the case doesn't close itself."""
    on = cases_mod.closes_on(c, quiet_days()) if c else None
    if on is None:
        return ""
    first = ((c.get("customer") or {}).get("name") or "").split(" ")[0] or "the customer"
    return f"Answered · closes on {on.day} {on:%b} if {first} doesn't write"
```

Check `cases.outcome_says(c, CLOSE_OUTCOMES)` reads `outcome` "solved" as "Solved before any dispute" (it does for a
person's close; `closed_by` "Second Look" is not "PayPal", so the case page's pill says "Closed: Solved before any
dispute").

- [ ] **Step 5: Where it runs and shows**

1. `today_view`: add `    close_quiet(src)` as its first statement (before `demo = src == "demo"`), and replace `    today = DemoPayPal().today if demo else datetime.utcnow().date()` with
   `    today = shop_today(src)`.
2. `inbox_page`: add `    close_quiet(src)` as its first statement (practice has no case file: `close_quiet`
   returns `[]`).
3. `case_file_page`: add `    close_quiet(shop_of_case(cid)) if cases_mod.is_case_id(cid) else None` as its first
   statement (before `v = case_view(cid)`), and right after the `owner = (...)` assignment add:
   ```python
   closes = _closes_words(c)
   owner += f'<p class="owner-line">{e(closes)}</p>' if closes else ""
   ```
4. `rules_page`: after the `limits.append(f'A case\'s staff time ...')` statement, add:
   ```python
   limits.append(f'An answered request closes itself, as solved before any dispute, after {quiet_days()} days with no '
                 'word from the customer. Not one with money or goods logged on it: a person closes those.')
   ```
5. `policy.json`: add after the `"staff_time"` block:
   ```json
     "close_answered_after_days": 3,
   ```
   (keep the file valid JSON: the comma goes where the next key follows). This key is not in
   `autopilot.LIMITS`, so Second Look's AI's record keeps its fingerprint: `test_the_demo_s_record_is_earned_under_today_s_setup...` still passes.

- [ ] **Step 6: Run** `python3 tests/test_closing.py && python3 tests/test_autopilot.py && python3 tests/test_today.py && python3 tests/test_web.py`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add secondlook/cases.py secondlook/web.py policy.json tests/test_closing.py
git commit -m "An answered request closes itself after 3 quiet days, signed by Second Look: code, at each look, never with money logged

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: One counting function for any period

**Files:** Modify `secondlook/today.py` (`period`, `windows`, `weeks`; `month` wraps `period`). Test: `tests/test_today.py`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_today.py` before `if __name__`):

```python
def test_like_for_like_windows_and_the_last_eight_weeks():
    assert today.windows(date(2026, 10, 20)) == ((date(2026, 10, 1), date(2026, 10, 20)), (date(2026, 9, 1), date(2026, 9, 20)))
    assert today.windows(date(2026, 10, 31))[1] == (date(2026, 9, 1), date(2026, 9, 30))       # cut at 30 Sep
    assert today.windows(date(2026, 3, 1))[1] == (date(2026, 2, 1), date(2026, 2, 1))
    assert today.windows(date(2026, 10, 20), "week") == ((date(2026, 10, 19), date(2026, 10, 20)),
                                                         (date(2026, 10, 12), date(2026, 10, 13)))
    assert today.windows(date(2026, 10, 19), "week") == ((date(2026, 10, 19), date(2026, 10, 19)),
                                                         (date(2026, 10, 12), date(2026, 10, 12)))
    w = today.weeks(date(2026, 10, 20))
    assert len(w) == 8 and w[0] == (date(2026, 8, 31), date(2026, 9, 6)) and w[-1] == (date(2026, 10, 19), date(2026, 10, 20))


def test_a_period_counts_only_its_own_days_and_this_month_is_the_morning_screen_s_month():
    cases = [case("C1", ("2026-09-05T09:00", "email", "in"), ("2026-09-05T10:00", "email", "out"), status="closed",
                  closed_at="2026-09-06T09:00"),
             case("C2", ("2026-10-02T09:00", "email", "in"), ("2026-10-02T10:00", "email", "out"))]
    cases[1]["timeline"].append({"at": "2026-10-02T11:00", "channel": "email", "direction": "out", "text": "…",
                                 "by": "Second Look's AI", "ai": True, "autopilot": True})
    orders = [{"date": "2026-09-05"}, {"date": "2026-09-25"}, {"date": "2026-10-02"}, {"date": "2026-10-03"}]
    sep = today.period(cases, [], orders, "2026-09-01T00:00", "2026-09-21T00:00", None)
    octo = today.period(cases, [], orders, "2026-10-01T00:00", None, None)
    assert (sep["requests"], sep["solved_before_dispute"], sep["answers"], sep["orders"], sep["ai_answered"]) == (1, 1, 1, 1, 0)
    assert (octo["requests"], octo["solved_before_dispute"], octo["answers"], octo["orders"], octo["ai_answered"]) == (1, 0, 1, 2, 1)
    assert (sep["from"], sep["to"], octo["to"]) == ("2026-09-01T00:00", "2026-09-21T00:00", None)
    m = today.month(cases, [], orders, TODAY, None)
    assert {k: m[k] for k in octo} == octo                     # the morning screen's month is this period, unchanged
```

- [ ] **Step 2: Run, expect FAIL** (`AttributeError: ... 'windows'`).

- [ ] **Step 3: Implement in `secondlook/today.py`**

Update the module docstring's last paragraph to add: `"A period" (Numbers) runs from 00:00 on its first day to 00:00
after its last; the current one, like this month, has no end.`

Add after `month_start()`:

```python
def windows(today: date, by: str = "month") -> tuple:
    """Like for like: ((first, last) of this period so far, (first, last) of the same days of the one before), days
    inclusive. By month: the 1st to today, and the 1st of the month before to the same day, cut at that month's last
    day (31 Oct is compared with 1-30 Sep). By week, Monday first: Monday to today, and the same days a week before."""
    if by == "week":
        first = today - timedelta(days=today.weekday())
        return (first, today), (first - timedelta(days=7), today - timedelta(days=7))
    first = today.replace(day=1)
    end_before = first - timedelta(days=1)
    first_before = end_before.replace(day=1)
    return (first, today), (first_before, min(first_before + timedelta(days=today.day - 1), end_before))


def weeks(today: date, n: int = 8) -> list:
    """The last `n` weeks, Monday to Sunday, oldest first; this one ends today."""
    monday = today - timedelta(days=today.weekday())
    return [(monday - timedelta(days=7 * i), min(monday - timedelta(days=7 * i - 6), today)) for i in range(n - 1, -1, -1)]


def _within(at: str, start: str, end: str | None) -> bool:
    return at >= start and (end is None or at < end)
```

Replace the whole `month()` function with `period()` and the new `month()`:

```python
def period(cases: list, disputes: list, orders: list, start: str, end: str | None, policy: dict | None, answers=(),
           high_volume: bool = False, currency: str = "EUR") -> dict:
    """What happened from `start` up to `end` (None: no end, as this month has none): the flows a period is compared on
    (Numbers), every channel. `answers`: when each answer to a PayPal dispute was sent from Second Look (an inquiry's
    answers are on its case already). Staff time is an estimate (cases.staff_time); dispute fees are estimated from
    PayPal's fee table, at the fee `high_volume` says (PayPal's line as it stood at the period's end)."""
    held = set(links(cases, disputes, orders))
    inside = lambda at: _within(at or "", start, end)  # noqa: E731
    ordered = sum(1 for o in orders if _within(o.get("date") or "", start[:10], end and end[:10]))
    new_cases = [c for c in cases if inside(c.get("opened"))]
    new_disputes = [d for d in disputes if inside(_at(d.get("create_time"))) and d["dispute_id"] not in held]
    solved = [c for c in cases if c.get("status") != "open" and not c.get("dispute_id") and inside(_closed_at(c))]
    st = staff_time(policy)
    entries = [x for c in cases for x in c.get("timeline", []) if inside(x.get("at"))]
    # a reply Second Look's AI sent on its own took nobody's minutes: it is not staff time
    written = sum(1 for x in entries if x.get("direction") == "out" and x.get("channel") != "call" and not x.get("autopilot"))
    written += sum(1 for a in answers if inside(a))
    call_min = sum(_num(x.get("minutes")) for x in entries if x.get("channel") == "call" and x.get("direction") in ("in", "out"))
    minutes = written * st["reply_minutes"] + call_min
    # a refund a person cancelled moved no money
    money = [x for c in cases for x in c.get("money", []) if inside(x.get("at")) and x.get("status") != "cancelled"]
    back_cases = round(sum(_num(x.get("amount")) for x in money if x.get("kind") in BACK), 2)
    resolved = [d for d in disputes if d.get("status") == "RESOLVED" and inside(_at(d.get("update_time") or d.get("create_time")))]
    back_paypal = round(sum(ledger.refunded(d) for d in resolved), 2)
    # the same order given back on both sides (a refund logged on a case, and PayPal's): flagged, not hidden in a sum
    on_cases = {c.get("order_no") for c in cases for x in c.get("money", [])
                if c.get("order_no") and x.get("kind") in BACK and inside(x.get("at")) and x.get("status") != "cancelled"}
    both_sides = sorted(on_cases & {_tx(d) for d in resolved if ledger.refunded(d) > 0})
    standard, hv_fee = DISPUTE_FEE.get(currency, (0.0, 0.0))
    fees = sum(hv_fee if high_volume else standard if ledger.outcome(d) in ("lost_claim", "lost_no_reply") else 0
               for d in resolved if escalated(d))
    fees = round(fees + sum(_num(x.get("amount")) for x in money if x.get("kind") == "fee"), 2)
    return {"from": start, "to": end, "orders": ordered, "requests": len(new_cases) + len(new_disputes),
            "requests_by_channel": _first_channels(new_cases, len(new_disputes)),
            "solved_before_dispute": len(solved),
            "ai_answered": sum(1 for x in entries if x.get("direction") == "out" and x.get("autopilot")),
            "answers": written, "minutes": minutes,
            "calls": sum(1 for x in entries if x.get("channel") == "call" and x.get("direction") == "in"),
            "call_minutes": round(call_min, 2),
            "hourly_cost": st["hourly_cost"], "reply_minutes": st["reply_minutes"],
            "staff_cost": round(minutes / 60 * st["hourly_cost"], 2),
            "back_cases": back_cases, "back_paypal": back_paypal, "back": round(back_cases + back_paypal, 2),
            "both_sides": both_sides, "fees": fees, "currency": currency}


def month(cases: list, disputes: list, orders: list, today: date, policy: dict | None, answers=(),
          currency: str = "EUR") -> dict:
    """This month so far, every channel (period from the 1st, no end), and what holds right now: what the open cases
    could still cost, and PayPal's high-volume line."""
    hv = ledger.overview(disputes, orders, today, currency)["high_volume"]
    out = period(cases, disputes, orders, month_start(today), None, policy, answers, hv["high_volume"], currency)
    linked = {id(c) for c in links(cases, disputes, orders).values()}
    ex = ledger.exposure(disputes, today, hv["high_volume"], currency)
    amount_of = _amounts(orders)
    open_inq = [c for c in cases if c.get("status") == "open" and not c.get("dispute_id") and c.get("order_no")
                and id(c) not in linked]
    # what already went back on each order, from every case on it (closed ones too): refunds and goods
    given = {}
    for c in cases:
        for x in c.get("money", []):
            if c.get("order_no") and x.get("kind") in BACK + ("replace",) and x.get("status") != "cancelled":
                given[c["order_no"]] = given.get(c["order_no"], 0.0) + _num(x.get("amount"))
    inq_stake = round(sum(max(0.0, amount_of.get(c["order_no"], 0.0) - given.get(c["order_no"], 0.0))
                          for c in open_inq), 2)
    return {**out, "open_disputes_most": ex["all_lost"], "open_inquiries_most": inq_stake,
            "could_still_cost": round(ex["all_lost"] + inq_stake, 2), "high_volume": hv}
```

- [ ] **Step 4: Run** `python3 tests/test_today.py && python3 tests/test_books.py && python3 tests/test_autopilot.py`
Expected: all pass — every existing figure (65 requests, 31 solved, 23 answers, 57.74 EUR, 1,109.00 EUR) unchanged.

- [ ] **Step 5: Commit**

```bash
git add secondlook/today.py tests/test_today.py
git commit -m "One counting function for any period (today.period); this month is a period with no end, unchanged; like-for-like windows

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Numbers as data, and where the demo's records begin

**Files:** Modify `demo/make_demo.py`, regenerate `demo/shop.json`; `secondlook/web.py` (`records_from`,
`numbers_view`, route `/api/numbers`). Create `tests/test_numbers.py`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_numbers.py`:

```python
"""Numbers: this week or month so far beside the same days of the one before (like for like), the weeks on record, and
what holds right now. One counting function (today.period) for all of it. Run: python3 tests/test_numbers.py"""
import json
import sys
import threading
from datetime import date
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from secondlook import web  # noqa: E402
from test_inquiry import morning  # noqa: E402

FLOWS = ("orders", "requests", "solved_before_dispute", "ai_answered", "answers", "minutes", "back", "fees")


def test_the_demo_s_own_records_begin_on_1_september():
    assert web.records_from("demo") == date(2026, 9, 1)


def test_october_so_far_beside_the_same_days_of_september():
    with morning():
        v = web.numbers_view("demo")
        a, b, m = v["this"], v["before"], v["month"]
        assert (v["by"], a["first"], a["last"], b["first"], b["last"]) == (
            "month", date(2026, 10, 1), date(2026, 10, 20), date(2026, 9, 1), date(2026, 9, 20))
        assert {k: a[k] for k in FLOWS} == {k: m[k] for k in FLOWS}          # this month: the same figures as before
        assert (m["requests"], m["solved_before_dispute"], m["ai_answered"]) == (65, 31, 1)
        assert (a["to"], b["to"]) == (None, "2026-09-21T00:00") and b["requests"] > 0
        assert [w["first"] for w in v["weeks"]][0] == date(2026, 9, 7) and len(v["weeks"]) == 7   # 31 Aug: before 1 Sep
        assert v["weeks"][-1]["so_far"] and not v["weeks"][-2]["so_far"]
        w = web.numbers_view("demo", "week")
        assert (w["by"], w["this"]["first"], w["before"]["first"], w["before"]["last"]) == (
            "week", date(2026, 10, 19), date(2026, 10, 12), date(2026, 10, 13))
        assert web.numbers_view("demo", "year")["by"] == "month"


def test_before_the_first_record_there_is_no_record_never_a_zero():
    with morning():
        kept = web.records_from
        web.records_from = lambda src: date(2026, 10, 1)
        try:
            v = web.numbers_view("demo")
        finally:
            web.records_from = kept
        assert v["before"] is None and all(w["first"] >= date(2026, 10, 1) for w in v["weeks"])
        assert web.records_from("live") is None                              # no case in the live shop here


def test_numbers_as_data_over_http():
    with morning():
        srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            con = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            con.request("GET", "/api/numbers?shop=demo&by=week")
            data = json.loads(con.getresponse().read())
            assert data["by"] == "week" and data["this"]["first"] == "2026-10-19" and data["month"]["requests"] == 65
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
```

Note: `web.records_from("live")` reads `case_store("live")`, which the bench points at an empty temporary file.

- [ ] **Step 2: Run, expect FAIL** — `python3 tests/test_numbers.py` → `KeyError: 'records_from'` or `AttributeError`.

- [ ] **Step 3: The demo's records begin on 1 Sep** — in `demo/make_demo.py`:

1. After `TODAY = date(2026, 10, 20)` add:
   `HISTORY_FROM = date(2026, 9, 1)  # the shop's own cases begin here: Numbers never compares a period before it`
2. In the `SHOP` dict, after the `"about": ...` entry, add `    "records_from": HISTORY_FROM.isoformat(),`
3. In the history loop line `history, used, k, day = [], set(), 0, date(2026, 9, 1)` replace `date(2026, 9, 1)` with
   `HISTORY_FROM`.

Regenerate and check that only that line changed:

```bash
env -u SECONDLOOK_MODEL python3 demo/make_demo.py
git diff --stat demo/shop.json          # expect: 1 file changed, 1 insertion(+)
git diff demo/shop.json                 # expect: only  "records_from": "2026-09-01",
python3 tests/test_demo_shop.py         # the generator is deterministic and the shipped file is its output
```
If the diff shows anything else, stop and report: the demo must not move.

- [ ] **Step 4: `records_from` and `numbers_view` in `secondlook/web.py`** (add above the `claim_line_box` function,
i.e. in the morning-screen section):

```python
def records_from(src: str):
    """The first day this shop's own records cover: a period before it has no record, never a zero. The demo's history
    begins on 1 Sep 2026 (demo/shop.json "records_from"); a live shop's on its first case's day; None: no case yet."""
    if src == "demo":
        return datetime.strptime(DemoPayPal().shop["records_from"], "%Y-%m-%d").date()
    days = [c["opened"][:10] for c in case_store(src).all() if c.get("opened")] if src in CASE_FILES else []
    return datetime.strptime(min(days), "%Y-%m-%d").date() if days else None


def numbers_view(src: str, by: str = "month") -> dict:
    """Numbers, as data: this week or month so far beside the same days of the one before (like for like; None before
    the shop's records begin), the weeks on record, this month with what holds right now (today.month), and PayPal's
    own last 90 days. One counting function for every period (today.period)."""
    by = by if by in ("week", "month") else "month"
    close_quiet(src)
    today = shop_today(src)
    cases, disputes, orders = shop_cases(src), shop_disputes(src), shop_orders(src)
    pol, answers, cur = _policy(), sent_answers(src), "EUR"
    since = records_from(src)

    def flows(first, last, current, fees=True):
        # PayPal's line as it stood at the period's end sets its fee; the week bars count requests only
        hv = fees and ledger.overview(disputes, orders, last, cur)["high_volume"]["high_volume"]
        return today_mod.period(cases, disputes, orders, f"{first.isoformat()}T00:00",
                                None if current else f"{(last + timedelta(days=1)).isoformat()}T00:00",
                                pol, answers, bool(hv), cur)
    (a0, a1), (b0, b1) = today_mod.windows(today, by)
    weeks = []
    for first, last in today_mod.weeks(today):
        if since is None or first < since:
            continue
        f = flows(first, last, last == today, fees=False)
        weeks.append({"first": first, "last": last, "so_far": (last - first).days < 6,
                      "requests": f["requests"], "orders": f["orders"]})
    ov = ledger.overview(disputes, orders, today, cur)
    return {"by": by, "today": today, "records_from": since,
            "this": {"first": a0, "last": a1, **flows(a0, a1, True)},
            "before": {"first": b0, "last": b1, **flows(b0, b1, False)} if since and b0 >= since else None,
            "weeks": weeks, "month": today_mod.month(cases, disputes, orders, today, pol, answers, cur),
            "paypal": ov, "exposure": ledger.exposure(disputes, today, ov["high_volume"]["high_volume"], cur)}
```

- [ ] **Step 5: The route** — in `do_GET`, right after the `/api/today` block, add:

```python
            if u.path == "/api/numbers":
                return self._json(numbers_view("live" if src == "live" else "demo", (qs.get("by") or ["month"])[0]))
```

- [ ] **Step 6: Run** `python3 tests/test_numbers.py && python3 tests/test_demo_shop.py && python3 tests/test_today.py` → pass.

- [ ] **Step 7: Commit**

```bash
git add demo/make_demo.py demo/shop.json secondlook/web.py tests/test_numbers.py
git commit -m "Numbers as data: this period so far beside the same days before, the weeks on record (the demo's from 1 Sep), GET /api/numbers

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: "Looks right", and checking from the case page

**Files:** Modify `secondlook/autopilot.py` (`Record.looks_right`), `secondlook/web.py` (`autopilot_looks_right`,
`ai_check_form`, `_back_to`, the POST route, the case page). Test: `tests/test_autopilot.py`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_autopilot.py`):

```python
def test_looks_right_marks_it_checked_and_moves_nothing_in_its_record():
    with morning():
        kind_before = web.autopilot_store("demo").view()["kinds"][KIND]
        page = web.case_file_page("DEMO-C004", me="marta")
        assert "Looks right" in page and "I&#x27;d have done it differently" in page   # anyone checks from the case
        with served() as post:
            assert post("/autopilot/looks-right", {"case": "DEMO-C004", "by": "nobody", "shop": "demo"})[0] == 400
            assert post("/autopilot/looks-right", {"case": "DEMO-C001", "by": "giulia", "shop": "demo"}) == (
                404, "Second Look's AI didn't answer this case on its own.")
            assert post("/autopilot/looks-right", {"case": "DEMO-C004", "by": "giulia", "shop": "demo",
                                                   "to": "/c/DEMO-C004"})[0] == 303
            assert post("/autopilot/looks-right", {"case": "DEMO-C004", "by": "marta", "shop": "demo"}) == (
                409, "Already checked by Giulia.")
            assert post("/autopilot/differently", {"case": "DEMO-C004", "by": "marta", "shop": "demo"}) == (
                409, "Already noted by Giulia.")
        x = web.autopilot_store("demo").view()
        assert x["cases"]["DEMO-C004"]["checked"]["by"] == "Giulia" and not x["cases"]["DEMO-C004"]["checked"]["differently"]
        assert x["kinds"][KIND] == kind_before                                # its record and its switch: unchanged
        assert web.case_store("demo").get("DEMO-C004")["timeline"][-1]["text"] == \
            "Giulia checked what Second Look's AI sent on its own: it looks right."
        assert "Giulia checked it: looks right" in web.case_file_page("DEMO-C004", me="marta")


def test_a_check_sends_you_back_only_to_a_page_of_this_app():
    assert web._back_to("/c/DEMO-C004", "demo") == "/c/DEMO-C004"
    for bad in ("", "https://elsewhere.example/c/X", "//elsewhere.example", "/c/X?y=<b>", "/rules"):
        assert web._back_to(bad, "demo") == "/today?shop=demo", bad
```

`I&#x27;d` is how `e()` escapes the apostrophe in the button text. If `served()` is defined below where you append,
that is fine: the functions run after the module loads.

- [ ] **Step 2: Run, expect FAIL** (`"Looks right" in page` is False).

- [ ] **Step 3: `Record.looks_right` in `secondlook/autopilot.py`** (after `differently`):

```python
    def looks_right(self, did: str, by: str, at: str) -> tuple:
        """A person checked what it sent on its own, and it looks right: the check is kept, so the answers left to check
        go down. It never counts toward the record: only people's decisions on its advice, before anything is sent, do."""
        def do(data):
            c = data["cases"].get(did)
            if not c or not c.get("handled"):
                return 404, "Second Look's AI didn't answer this case on its own."
            if c.get("checked"):
                return 409, f"Already checked by {c['checked']['by']}."
            c["checked"] = {"by": by, "at": at, "differently": False}
            return 200, c["kind"]
        return self.change(do)
```

- [ ] **Step 4: In `secondlook/web.py`**, after `autopilot_differently` add:

```python
def autopilot_looks_right(src: str, did: str, by: str | None) -> tuple:
    """A person checked what Second Look's AI sent on its own, and it looks right: noted on its record and on the case."""
    who = team_mod.person(team_for_src(src), by)
    if not who:
        return 400, "Say who you are: a person in this shop's team."
    code, out = autopilot_store(src).looks_right(did, who["name"], cases_mod.minute(None))
    if code != 200:
        return code, out
    text = f"{who['name']} checked what Second Look's AI sent on its own: it looks right."
    c = case_store(src).get(did) if cases_mod.is_case_id(did) else find_case_of_dispute(did)
    if c:
        case_store(src).add(c["id"], cases_mod.entry(None, reply_channel(c), "note", text, who["name"]))
    return 200, text


def _back_to(to: str, src: str) -> str:
    """Where a check sends the person back: the case page they were on, or the morning screen. Never elsewhere."""
    return to if re.fullmatch(r"/c/[A-Za-z0-9-]+", to or "") else f"/today?shop={src}"


def ai_check_form(src: str, did: str, me: str | None, back: str) -> str:
    """Looks right / I'd have done it differently, on what Second Look's AI sent on its own (anyone in the team). The
    reason opens only after the second button. Once checked: who checked it, and how. Nothing when it didn't answer."""
    x = autopilot_store(src).view()["cases"].get(did) or {}
    if not x.get("handled"):
        return ""
    ch = x.get("checked")
    if ch:
        return (f'<p class="t-sub">{e(ch["by"])} would have done it differently</p>' if ch.get("differently") else
                f'<p class="t-sub">{e(ch["by"])} checked it: looks right</p>')
    hidden = (f'<input type="hidden" name="case" value="{e(did)}"><input type="hidden" name="shop" value="{e(src)}">'
              f'<input type="hidden" name="to" value="{e(back)}">'
              + (f'<input type="hidden" name="by" value="{e(me)}">' if me else ""))
    return (f'<div class="ai-check-actions"><form method="post" action="/autopilot/looks-right">{hidden}'
            '<button class="quiet">Looks right</button></form>'
            '<details><summary class="quiet">I&#x27;d have done it differently</summary>'
            f'<form method="post" action="/autopilot/differently" class="addrule">{hidden}'
            '<input name="why" maxlength="300" aria-label="What you would have done" '
            'placeholder="What you would have done (optional)"><button>Switch it off and note it</button></form>'
            '</details></div>')
```

- [ ] **Step 5: The route** — in `do_POST`, replace the block starting
`if parts in (["autopilot", "switch"], ["autopilot", "differently"]):` through its `return` with:

```python
            if parts in (["autopilot", "switch"], ["autopilot", "differently"], ["autopilot", "looks-right"]):
                src = "live" if form.get("shop", [""])[0] == "live" else "demo"
                by = form.get("by", [""])[0]
                if parts[1] == "switch":
                    code, text = autopilot_switch(src, form.get("kind", [""])[0], form.get("on", [""])[0] == "on", by)
                    to = f"/rules?shop={src}"
                elif parts[1] == "differently":
                    code, text = autopilot_differently(src, form.get("case", [""])[0], by, form.get("why", [""])[0])
                    to = _back_to(form.get("to", [""])[0], src)
                else:
                    code, text = autopilot_looks_right(src, form.get("case", [""])[0], by)
                    to = _back_to(form.get("to", [""])[0], src)
                return self._redirect(to) if code == 200 else self._send(e(text), code)
```

- [ ] **Step 6: The case page** — in `case_file_page`, in the `else:` branch where `right = (review_column(cid, case,
me, plain_owner=False) + (_close_form(...) ...))` is built, change it to put the check first:

```python
        right = (ai_check_form(v["src"], cid, me, f"/c/{cid}")
                 + review_column(cid, case, me, plain_owner=False)
                 + (_close_form(cid, me) if c["status"] == "open" else ""))
```

- [ ] **Step 7: Run** `python3 tests/test_autopilot.py && python3 tests/test_web.py && python3 tests/test_closing.py` → pass.

- [ ] **Step 8: Commit**

```bash
git add secondlook/autopilot.py secondlook/web.py tests/test_autopilot.py
git commit -m "Looks right: a person checks what Second Look's AI sent on its own, from the case page too; its record never moves

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: What needs this person, as data

**Files:** Modify `secondlook/today.py` (`NEAR_LINE`, `needs_you`; `open_items` gains `today`), `secondlook/web.py`
(`today_view(src, me=None)`: `needs`, `head`, each new row's `has`, no `know`; `/api/today`). Tests:
`tests/test_today.py`, `tests/test_autopilot.py`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_today.py`):

```python
def test_needs_you_is_what_is_yours_nearest_deadline_first_then_calls_then_the_head_s_checks():
    def it(i, left):
        return {"id": i, "link": f"/d/{i}", "who": f"W {i}", "summary": "s", "amount": 10.0, "currency": "EUR",
                "days_left": left}
    items = [it("D1", 9), it("C1", None), it("D2", 2), it("D3", 1)]
    assigned = {"D1": {"to": "marta"}, "C1": {"to": "marta"}, "D2": {"to": "marta", "handoff": {"from": "giulia"}},
                "D3": {"to": "giulia"}}
    ai = [{"id": "DEMO-C9", "kind": "inquiry · not_received · MESSAGE"}]
    n = today.needs_you("marta", False, items, assigned, TEAM, handled=ai, failed=["a.wav"])
    assert [(x["kind"], x.get("id")) for x in n] == [("case", "D2"), ("case", "D1"), ("case", "C1"), ("calls", None)]
    assert (n[0]["from_name"], n[0]["from_role"]) == ("Giulia", "Head of customer care") and n[1]["from_name"] is None
    near = {"counts": True, "high_volume": False, "claims_to_threshold": 2, "claims": 30, "sales": 2100, "ratio": 0.014}
    g = today.needs_you("giulia", True, items, assigned, TEAM, handled=ai, hv=near)
    assert [x["kind"] for x in g] == ["case", "ai", "line"] and g[1]["ai_kind"] == "inquiry · not_received · MESSAGE"
    far = {**near, "claims_to_threshold": 9}
    assert [x["kind"] for x in today.needs_you("giulia", True, items, assigned, TEAM, hv=far)] == ["case"]
    assert [x["id"] for x in today.needs_you(None, True, items, {}, {"solo": True})] == ["D3", "D2", "D1", "C1"]
    assert today.needs_you("sara", False, items, assigned, TEAM) == []


def test_the_demo_morning_needs_giulia_for_one_check_and_marta_for_her_four_cases():
    with morning():
        g = web.today_view("demo", "giulia")
        assert [(x["kind"], x.get("id")) for x in g["needs"]] == [("ai", "DEMO-C004")] and g["head"]
        assert g["needs"][0]["closes"] == "Answered · closes on 23 Oct if Margot doesn't write"
        m = web.today_view("demo", "marta")
        assert [x["kind"] for x in m["needs"]] == ["case"] * 4 and not m["head"]
        lefts = [x["days_left"] for x in m["needs"]]
        assert lefts == sorted(lefts, key=lambda d: (d is None, d or 0))
        assert next(r for r in g["see"]["rows"] if r["case_id"] == "DEMO-C001")["has"] == "Marta"
        assert next(r for r in g["see"]["rows"] if r["case_id"] == "DEMO-C004")["has"] is None
        assert "know" not in g
```

Then update existing tests that read the old `know`:
- `tests/test_today.py`, in `test_the_demo_morning_reads_every_channel_against_its_orders`: replace
  `        k = v["know"]` with `        k = web.numbers_view("demo")["month"]`.
- `tests/test_today.py`, in `test_what_the_team_does_this_morning_shows_at_once`: replace
  `        assert (v["know"]["answers"], v["know"]["solved_before_dispute"]) == (24, 32)` with
  `        k = web.numbers_view("demo")["month"]` and, on the next line, `        assert (k["answers"], k["solved_before_dispute"]) == (24, 32)`.
- `tests/test_today.py`, in `test_the_morning_screen_over_http_and_as_data`: replace `and data["know"]["requests"] == 65`
  with nothing (end that assert at `data["see"]["counts"]["form"] == 1`). (Task 4's HTTP test covers the figure.)
- `tests/test_autopilot.py`, in `test_what_it_sends_on_its_own_takes_nobody_s_minutes`: replace both
  `web.today_view("demo")["know"]` with `web.numbers_view("demo")["month"]`.

- [ ] **Step 2: Run, expect FAIL** (`AttributeError: ... 'needs_you'`).

- [ ] **Step 3: `secondlook/today.py`**

`open_items` gains `today` (the days left on each open PayPal dispute; a shop inquiry has no PayPal deadline). Change
its signature to `def open_items(cases: list, disputes: list, orders: list, today: date | None = None) -> list:`, add to
its docstring `` `today`: with it, each item says the days left on its PayPal deadline (None for an inquiry).``, and
add `"days_left": ledger.days_left(d, today) if today else None` to the dispute item dict and `"days_left": None` to
the inquiry item dict.

Add after `who_has()`:

```python
# Claims: PayPal's high-volume line comes onto the morning screen when this few more would cross it, or once crossed.
NEAR_LINE = 3


def needs_you(me: str | None, head: bool, items: list, assigned: dict, team: dict, handled=(), failed=(), hv=None) -> list:
    """The morning screen's first block: what needs this person now. Their cases, nearest PayPal deadline first (a
    handoff to them says who passed it); the calls nobody could transcribe (anyone listens); and for the head of
    customer care, Second Look's AI's answers nobody checked yet, and PayPal's high-volume line when it is near or
    crossed. In a team of one every open case is the seller's. `items`: open_items(..., today); `assigned`: decision
    id -> {"to", "handoff"}; `handled`: what Second Look's AI answered on its own, not checked yet."""
    solo = bool(team.get("solo"))
    people = {p["id"]: p for p in team.get("people", []) if isinstance(p, dict) and p.get("id")}
    mine = []
    for it in items:
        a = assigned.get(it["id"]) or {}
        if not solo and (not me or a.get("to") != me):
            continue
        hand = a.get("handoff") if isinstance(a.get("handoff"), dict) else None
        frm = (people.get(hand.get("from")) or {}) if hand else {}
        mine.append({**it, "kind": "case",
                     "from_name": (frm.get("name") or hand.get("from_name") or "A colleague") if hand else None,
                     "from_role": (frm.get("role") or "") if hand else None})
    mine.sort(key=lambda x: (x.get("days_left") is None, x.get("days_left") or 0))
    out = mine + ([{"kind": "calls", "wavs": list(failed)}] if failed else [])
    if head:
        out += [{**h, "ai_kind": h.get("kind"), "kind": "ai"} for h in handled]
        if hv and hv.get("counts") and (hv.get("high_volume") or hv.get("claims_to_threshold", NEAR_LINE + 1) <= NEAR_LINE):
            out.append({**hv, "kind": "line"})
    return out
```

- [ ] **Step 4: `today_view` in `secondlook/web.py`** — replace the whole function with:

```python
def today_view(src: str, me: str | None = None) -> dict:
    """The morning screen as data (the page and GET /api/today show the same): what needs `me` (today.needs_you), what
    came in since yesterday (each row says who has it), who has what. The figures are on Numbers (numbers_view)."""
    close_quiet(src)
    demo = src == "demo"
    today = shop_today(src)
    waiting, failed = 0, []
    if CALL_BOXES.get(src):
        file_calls(case_store(src), src)              # a call left in the box since the last look comes in now
        waiting = calls_waiting(case_store(src), src) if transcriber_on() else 0
        failed = calls_failed(case_store(src), src)
    cases, disputes, orders = shop_cases(src), shop_disputes(src), shop_orders(src)
    t = team_for_src(src)
    solo = bool(t.get("solo"))
    who = None if solo else team_mod.person(t, me)
    head = solo or (who is not None and team_mod.limit(t, who["id"]) is None)
    assigned = {} if solo else assignments_for("DEMO-" if demo else None).all()
    rec = autopilot_store(src).view()           # Second Look's AI's record, read once for every row
    see = today_mod.came_in(cases, disputes, orders, today, review_of=lambda did: review_line(did, rec["cases"]))
    if not solo:
        names = {p["id"]: p.get("name") or p["id"] for p in team_mod.people(t)}
        for r in see["rows"]:
            r["has"] = names.get((assigned.get(r["decision_id"]) or {}).get("to"))
    items = today_mod.open_items(cases, disputes, orders, today)
    handled = autopilot_handled(src, today, rec)
    for h in handled:
        h["closes"] = _closes_words(case_store(src).get(h["id"]) if cases_mod.is_case_id(h["id"]) else None)
    hv = ledger.overview(disputes, orders, today)["high_volume"]
    return {"today": today, "team": t, "head": head, "phone": bool(CALL_BOXES.get(src)), "calls_pending": waiting,
            "calls_failed": failed, "see": see,
            "needs": today_mod.needs_you(who["id"] if who else None, head, items, assigned, t,
                                         [h for h in handled if not h.get("checked")], failed, hv),
            "manage": today_mod.who_has(items, assigned, t),
            "autopilot": {"handled": handled,
                          "on": [kind_words(k) for k, x in rec["kinds"].items()
                                 if x.get("on") and autopilot_mod.split_kind(k)[0] in autopilot_mod.SWITCHABLE]}}
```

- [ ] **Step 5: `/api/today`** — replace its block in `do_GET` with:

```python
            if u.path == "/api/today":
                v = today_view("live" if src == "live" else "demo", (qs.get("as") or [None])[0])
                return self._json({"today": v["today"], "see": v["see"], "needs": v["needs"], "manage": v["manage"],
                                   "autopilot": v["autopilot"],
                                   "calls": {"being_transcribed": v["calls_pending"], "not_transcribed": v["calls_failed"]}})
```

`today_page` still calls `month_block(v["know"], ...)` until Task 7: to keep this task's suite green, change that one
line in `today_page` to `f'<section class="block">{month_block(numbers_view(src)["month"], v["today"], q)}'` and the
`claim_line_box(v["know"]["high_volume"], ...)` to `claim_line_box(numbers_view(src)["month"]["high_volume"], v["today"])`
(Task 7 replaces `today_page` entirely). Also pass `me`: `v = today_view(src, me)`.

- [ ] **Step 6: Run** `python3 tests/test_today.py && python3 tests/test_autopilot.py && python3 tests/test_calls.py && python3 tests/test_numbers.py` → pass.

- [ ] **Step 7: Commit**

```bash
git add secondlook/today.py secondlook/web.py tests/test_today.py tests/test_autopilot.py
git commit -m "What needs this person, as data: their cases nearest deadline first, calls nobody heard, and the head's checks; each new row says who has it

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: The morning screen, one column, one question

**Files:** Modify `secondlook/web.py` (`see_block`, new `needs_block`, `team_block`, `today_page`; remove
`handled_block`, `manage_block`; CSS in `PAGE`). Tests: `tests/test_today.py`, `tests/test_autopilot.py`.

- [ ] **Step 1: Rewrite the page tests**

In `tests/test_today.py`, replace the whole function `test_the_morning_screen_says_whose_names_and_roles_and_labels_every_estimate`
with:

```python
def test_the_morning_screen_answers_what_needs_me():
    with morning():
        v = web.today_view("demo", "giulia")
        html_ = web.today_page("demo", "giulia")
        free = len(v["manage"]["unassigned"])
        for words in ("Good morning, Giulia.", "Tue 20 Oct · 6 new since yesterday · 141 new orders", "Needs you · 1",
                      "Second Look's AI answered 1 on its own: check it",
                      "Answered · closes on 23 Oct if Margot doesn&#x27;t write", "Looks right",
                      "I&#x27;d have done it differently", "New since yesterday · 6", "✉️ 3 emails", "📝 1 web form",
                      "📞 1 call", "<b>Pablo Martin</b>, <i>customer</i>", "Margot Lefèvre</b>, <i>customer</i>",
                      "19 days left", "no PayPal deadline", "Marta has it", "Your team is on it",
                      "<b>Marta</b>, <i>Customer care assistant</i> · 4", f"not taken yet {free}"):
            assert words in html_, words
        for gone in ("I know", "I manage", "This month (October 2026)", "Export for accounting", "PayPal's high-volume line"):
            assert gone not in html_, gone                                   # the figures live on Numbers now
        nav = html_.split("<nav>")[1].split("</nav>")[0]
        assert '<a href="/today?shop=demo" aria-current="page">Today</a>' in nav and '<a href="/numbers?shop=demo">Numbers</a>' in nav
        marta = web.today_page("demo", "marta")
        assert "Needs you · 4" in marta and f"Not taken yet · {free}" in marta
        assert "Second Look's AI answered" not in marta and "Your team is on it" not in marta
        assert "Nothing needs you" in web.today_page("demo", "sara")
        assert web.approve("DEMO-034", "REFUND", "You're right: here is your refund.", by="marta")[0] == 202
        giulia = web.today_page("demo", "giulia")
        assert "Needs you · 2" in giulia and "passed to you by Marta, <i>Customer care assistant</i>" in giulia
```

(6 = the six rows `test_the_demo_morning_reads_every_channel_against_its_orders` lists. The nav's Numbers link is
changed in this task, Step 3 item 6; the `/numbers` page itself comes in Task 8.)

In `tests/test_today.py`, in `test_the_morning_screen_over_http_and_as_data`, replace
`assert r.status == 200 and "Today at Linen &amp; Paper" in r.read().decode()` with
`assert r.status == 200 and "Good morning, Marta." in r.read().decode()`.

In `tests/test_today.py`, `test_an_order_given_back_on_both_sides_is_flagged_not_silently_added`: replace
`web.month_block(k, TODAY)` (both places) with `web.both_sides_note(k)`.

In `tests/test_autopilot.py`:
- `test_the_morning_screen_says_what_it_handled_and_why_it_stepped_back`: replace
  ```python
          page = web.today_page("demo", "marta")
          assert "Handled by Second Look's AI: 1 — check them" in page and "I'd have done it differently" in page
          assert "except the kinds Second Look&#x27;s AI answers on its own under your setting" in page
  ```
  with
  ```python
          page = web.today_page("demo", "giulia")
          assert "Second Look's AI answered 1 on its own: check it" in page and "I&#x27;d have done it differently" in page
          assert "except the kinds Second Look&#x27;s AI answers on its own under your setting" in web.today_page("demo", "marta")
  ```
- `test_i_d_have_done_it_differently_switches_the_kind_off_and_restarts_its_count`: replace
  ```python
          page = web.today_page("demo", "marta")
          assert "Handled by Second Look's AI: 0 — check them" in page and "Marta would have done it differently" in page
  ```
  with
  ```python
          assert "Second Look's AI answered" not in web.today_page("demo", "giulia")       # checked: off the list
          assert "Marta would have done it differently" in web.case_file_page(cid, me="giulia")
  ```
- `test_the_demo_s_first_load_has_second_look_s_ai_answer_margot_and_step_back_from_sophie`: replace
  `assert "Handled by Second Look's AI: 1 — check them" in web.today_page("demo", "giulia")` with
  `assert "Second Look's AI answered 1 on its own: check it" in web.today_page("demo", "giulia")`.

`tests/test_calls.py` keeps its four page asserts unchanged: the call chips stay in *New since yesterday*, and a call
nobody could transcribe moves into *Needs you* with the same words.

- [ ] **Step 2: Run, expect FAIL** — `python3 tests/test_today.py` fails on "Good morning, Giulia.".

- [ ] **Step 3: The page in `secondlook/web.py`**

1. Delete `handled_block` and `manage_block` (nothing else calls them: `grep -n "handled_block\|manage_block" secondlook/*.py` must print nothing afterwards).
2. Replace `see_block` with:

```python
def see_block(s: dict, q: str, phone: bool = False, pending: int = 0) -> str:
    """New since yesterday: one line per problem, every channel, nearest PayPal deadline first, each saying who has it
    (in a team) and what Second Look recommends."""
    chips = []
    if pending:      # recordings local whisper is still on: they come in once it has their words
        chips.append(f'<span class="chip off">📞 {pending} call{"s" if pending != 1 else ""} being transcribed</span>')
    for ch, word, n in today_mod.channel_words(s["counts"]):
        if ch == "paypal" and s.get("paypal_messages"):
            word = "PayPal disputes or new PayPal messages"     # it counts a buyer's new message on an older one too
        if ch == "call" and not phone:
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
        has = ("" if "has" not in r else f'<span class="has">{e(r["has"])} has it</span>' if r["has"]
               else '<span class="has none">not taken yet</span>')
        rows.append(f'<li><a href="{e(r["link"])}{q}"><span class="chan">{e(icons)}</span>'
                    f'<span class="what"><b>{e(r["who"] or "")}</b>, <i>customer</i> · '
                    # the customer's own words, or Second Look's AI's reading of them: never one for the other
                    + (f'Second Look\'s AI reads this as: {e(r["summary"])}' if r.get("summary_by") == "ai"
                       else e(r["summary"]) if r.get("summary_by") == "call"
                       else f'they wrote: “{e(r["summary"])}”')
                    + f' · {r["amount"]:.2f} {e(r.get("currency") or "EUR")}{order}{" · closed" if r["status"] != "open" else ""}'
                    f'{has}{_rec(r["review"])}</span>{due}</a></li>')
    listing = (f'<ol class="see">{"".join(rows)}</ol>' if rows else
               '<p class="empty">Nothing new since yesterday.</p>')
    return (f'<h2>New since yesterday · {len(s["rows"])}</h2><p class="t-sub">From every channel, nearest PayPal '
            f'deadline first</p><p class="chips">{"".join(chips)}</p>{listing}')
```

3. Add `needs_block` and `team_block` after it:

```python
def needs_block(needs: list, q: str, me: str | None, src: str) -> str:
    """The morning screen's first block: what needs this person (today.needs_you), or that nothing does."""
    if not needs:
        return ('<section class="needs calm"><h2>Nothing needs you</h2>'
                '<p class="t-sub">Your team has the rest.</p></section>')
    rows, ai = [], [n for n in needs if n["kind"] == "ai"]
    for n in needs:
        if n["kind"] == "case":
            left = n.get("days_left")
            when = ("no PayPal deadline" if left is None else "overdue" if left < 0 else "today" if left == 0
                    else f"{left} day{'s' if left != 1 else ''} left")
            why = (f'passed to you by {e(n["from_name"])}' + (f', <i>{e(n["from_role"])}</i>' if n.get("from_role") else "")
                   if n.get("from_name") else "yours")
            rows.append(f'<li><a href="{e(n["link"])}{q}"><span class="what"><b>{e(n["who"] or "")}</b>, <i>customer</i>'
                        f' · {e(n["summary"])} · {n["amount"]:.2f} {e(n.get("currency") or "EUR")}'
                        f'<span class="t-sub">{why}</span></span>'
                        f'<span class="due{" soft" if left is None else ""}">{e(when)}</span></a></li>')
        elif n["kind"] == "calls":
            w = n["wavs"]
            rows.append(f'<li><span class="what">📞 {len(w)} call{"s" if len(w) != 1 else ""} couldn\'t be transcribed: '
                        f'listen to {"it" if len(w) == 1 else "them"} ({e(", ".join(w))})</span></li>')
        elif n["kind"] == "ai":
            if n is ai[0]:
                rows.append(f'<li class="group">Second Look\'s AI answered {len(ai)} on its own: '
                            f'check {"it" if len(ai) == 1 else "them"}</li>')
            rows.append(f'<li class="ai-check"><a href="{e(n["link"])}{q}"><span class="what"><b>{e(n["who"] or "")}</b>, '
                        f'<i>customer</i> · {e(n["kind_words"])}<span class="t-sub">{e(n["what"])}'
                        + (f' · {e(n["closes"])}' if n.get("closes") else "") + '</span></span></a>'
                        f'{ai_check_form(src, n["id"], me, "/today")}</li>')
        elif n["kind"] == "line":
            rows.append(f'<li><span class="what"><b>PayPal\'s high-volume line</b> · {n["claims"]} claims in '
                        f'{n["sales"]:,} sales: {n["ratio"]:.2%}. '
                        + ("Above the line: every claim costs 28 EUR, even the ones you win." if n["high_volume"]
                           else f'{n["claims_to_threshold"]} more claims this quarter and you cross it.')
                        + f' <a href="/numbers{q}">Numbers</a></span></li>')
    return f'<section class="needs"><h2>Needs you · {len(needs)}</h2><ul class="needs-list">{"".join(rows)}</ul></section>'


def team_block(mg: dict, head: bool, q: str) -> str:
    """For the head of customer care: one line, each person with their role and open cases, and what nobody has yet.
    For a colleague: what nobody has yet. A team of one: nothing (every open case is in Needs you)."""
    if mg["solo"]:
        return ""
    free = len(mg["unassigned"])
    link = f'/?view=unassigned{"&" + q[1:] if q else ""}'
    if not head:
        return (f'<section class="team"><h2>Not taken yet · {free}</h2><p class="t-sub">Nobody has these yet: '
                f'<a href="{e(link)}">open one and take it</a>.</p></section>')
    people = " · ".join(f'<b>{e(p["name"])}</b>, <i>{e(p["role"])}</i> · {len(p["items"])}' for p in mg["people"])
    return (f'<section class="team"><h2>Your team is on it</h2><p>{people} · '
            f'<a href="{e(link)}">not taken yet {free}</a></p></section>')
```

Note: in `needs_block` the AI item's `who` is the customer name from `autopilot_handled` (already a plain string).
The `n is ai[0]` test works because `ai` holds the same dict objects as `needs`.

4. Replace `today_page` with:

```python
def today_page(src: str, me: str | None = None) -> str:
    """The morning screen: what needs this person first, then what came in since yesterday, then who has the rest.
    The figures are on Numbers. "I see, I manage, I know" is the idea behind it, not its layout (Claudia, 27/10)."""
    demo = src == "demo"
    v = today_view(src, me)
    q = "?shop=demo" if demo else ""
    t = v["team"]
    person = None if t.get("solo") else team_mod.person(t, me)
    hour = 9 if demo else datetime.now().hour          # the demo's clock is a morning
    hello = ("Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening") + \
        (f", {person.get('name') or person['id']}" if person else "")
    d, s = v["today"], v["see"]
    line = (f'{d:%a} {d.day} {d:%b} · {len(s["rows"])} new since yesterday · '
            f'{s["orders"]:,} new order{"s" if s["orders"] != 1 else ""}')
    ours = v["autopilot"]["on"]
    rule = ("Nothing goes out until a person approves it, each within their own limit." if not ours else
            "Nothing goes out until a person approves it, each within their own limit, except the kinds Second Look's AI "
            f"answers on its own under your setting: {'; '.join(ours)} (Your rules).")
    body = (f'<div class="morning"><h1 class="page">{e(hello)}.</h1><p class="who">{e(line)}</p>'
            f'{needs_block(v["needs"], q, me, src)}'
            f'<section class="new">{see_block(s, q, v["phone"], v["calls_pending"])}</section>'
            f'{team_block(v["manage"], v["head"], q)}<p class="t-sub rule-line">{e(rule)}</p></div>')
    return page("Today | Second Look", "PayPal sandbox", body, demo, me=me, here="today")
```

5. CSS: in the `PAGE` template, right after the line containing `dl.know{{margin:0}}`, add (braces doubled):

```
.morning{{max-width:880px}} .morning h1.page{{margin-bottom:4px}} .rule-line{{margin-top:18px}}
section.needs,section.new,section.team{{background:#fff;border:1px solid var(--rule);padding:18px 20px;margin-top:20px}}
section.needs{{border-left:4px solid var(--incon)}} section.needs.calm{{border-left-color:var(--pass)}}
.needs-list{{list-style:none;padding:0;margin:0}} .needs-list li{{border-top:1px solid var(--rule);padding:10px 0}}
.needs-list li:first-child{{border-top:0}} .needs-list li a{{display:grid;grid-template-columns:1fr auto;gap:10px;text-decoration:none;color:inherit}}
.needs-list .group{{font-weight:700;padding-top:14px}} .needs-list .what .t-sub{{display:block}}
.ai-check-actions{{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-start;margin-top:8px}}
.ai-check-actions details{{flex:1 1 260px}} .ai-check-actions summary{{display:inline-block;cursor:pointer;list-style:none}}
.ai-check-actions details form{{margin-top:8px}}
.see .has{{display:block;font-size:14px}} .see .has.none{{color:var(--incon)}}
```

6. Nav (also needed by Task 8): in `page()`, replace
`f'<a href="/overview"{cur("overview")}>Overview</a>'` with `f'<a href="/numbers{q}"{cur("numbers")}>Numbers</a>'`,
and in its docstring replace `"overview"` with `"numbers"`. (`/numbers` itself is served in Task 8; the link is
harmless until then.)

- [ ] **Step 4: Run** `python3 tests/test_today.py && python3 tests/test_autopilot.py && python3 tests/test_calls.py && python3 tests/test_closing.py`
Expected: pass. If `test_web.py`'s nav test (`current(web.page("Overview | Second Look", ... here="overview"))`)
fails, that is Task 8's: run `python3 tests/test_web.py` and confirm it is the only failure.

- [ ] **Step 5: Look at it.** Serve the tests' bench (the demo's real data, its state in a temporary folder, no AI)
on a spare port, **never 8765/8766/8767**:

```bash
python3 -c "
import sys, threading; sys.path[:0]=['tests','.']
import test_inquiry as T
from http.server import ThreadingHTTPServer
from secondlook import web
with T.morning():
    srv = ThreadingHTTPServer(('127.0.0.1', 8791), web.Handler)
    print('serving 8791'); srv.serve_forever()
" &
```
Open `http://127.0.0.1:8791/today?shop=demo&as=giulia`, `...&as=marta`, `...&as=sara` (screenshot with the
Playwright tools if you have them; save screenshots under the worktree's `.playwright-mcp/`, never the Desktop).
Check: one column; *Needs you* first; nothing cut off; the "I'd have done it differently" box opens only after its
button; the page reads on a 390 px-wide window. Then stop the server (`kill %1`).

- [ ] **Step 6: Commit**

```bash
git add secondlook/web.py tests/test_today.py tests/test_autopilot.py
git commit -m "The morning screen answers 'what needs me?': one column, Needs you first, new since yesterday one line each, the team in one line

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: The Numbers page replaces the Overview

**Files:** Modify `secondlook/web.py` (new `numbers_page`, `weeks_chart`, `both_sides_note`, `export_link`,
`exposure_box`, `paypal_block`, `_span`, `_change`, `_fmt`, `NUMBERS`; routes `/numbers`, `/overview` redirect;
`customer_page` back link; remove `overview_page`, `overview_whatnow`, `month_block`; CSS). Tests:
`tests/test_numbers.py`, `tests/test_web.py`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_numbers.py`):

```python
def test_the_numbers_page_compares_like_for_like_and_keeps_snapshots_apart():
    with morning():
        html_ = web.numbers_page("demo", "giulia")
        for words in ("October so far (1–20 Oct) against the same days of September (1–20 Sep)",
                      "Requests, every channel", "per 100 orders", "Solved before any PayPal dispute",
                      "Answered by Second Look&#x27;s AI on its own", "Staff time", "Money given back",
                      "PayPal dispute fees", "Requests, week by week", "Right now",
                      "Open cases could still cost at most 1,109.00 EUR", "PayPal's high-volume line",
                      "PayPal disputes, last 90 days",
                      'href="/books.csv?month=2026-10&shop=demo">Export for accounting (CSV, October 2026)',
                      'href="/numbers?by=week&shop=demo">This week', 'href="/?shop=demo">Disputes and requests'):
            assert words in html_, words
        nav = html_.split("<nav>")[1].split("</nav>")[0]
        assert '<a href="/numbers?shop=demo" aria-current="page">Numbers</a>' in nav
        week = web.numbers_page("demo", "giulia", "week")
        assert "This week so far (19–20 Oct) against the same days last week (12–13 Oct)" in week
        kept = web.records_from
        web.records_from = lambda src: date(2026, 10, 1)
        try:
            assert "no record yet" in web.numbers_page("demo", "giulia")
        finally:
            web.records_from = kept


def test_the_change_column_says_which_way_and_by_how_much():
    assert web._change(5, 3, "n", "EUR") == "+2" and web._change(3, 5, "n", "EUR") == "−2"
    assert web._change(3, 3, "n", "EUR") == "same"
    assert web._change(10.5, 30.0, "money", "EUR") == "−19.50 EUR"
    assert web._change(150, 120, "min", "EUR") == "+30 min"
    assert web._span(date(2026, 10, 1), date(2026, 10, 20)) == "1–20 Oct"
    assert web._span(date(2026, 9, 28), date(2026, 10, 4)) == "28 Sep–4 Oct"


def test_an_old_overview_link_lands_on_numbers():
    with morning():
        srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            con = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            con.request("GET", "/overview?shop=demo")
            r = con.getresponse()
            r.read()
            assert r.status == 303 and r.getheader("Location") == "/numbers?shop=demo"
            con.request("GET", "/numbers?shop=demo&by=week")
            r = con.getresponse()
            assert r.status == 200 and "This week so far" in r.read().decode()
            con.request("GET", "/numbers?practice=1")
            r = con.getresponse()
            r.read()
            assert r.status == 303 and r.getheader("Location") == "/?practice=1"
        finally:
            srv.shutdown()
            srv.server_close()
```

In `tests/test_web.py` (around line 696-702, the nav test): replace
`assert current(web.page("Overview | Second Look", "", body, here="overview")) == ["Overview"]` with
`assert current(web.page("Numbers | Second Look", "", body, here="numbers")) == ["Numbers"]`, and if the same test
names `"Overview"` anywhere else as a nav label, change it to `"Numbers"`.

- [ ] **Step 2: Run, expect FAIL** (`AttributeError: ... 'numbers_page'`).

- [ ] **Step 3: Implement in `secondlook/web.py`**

1. Extract from `overview_page` (before deleting it) two functions, placed where `overview_page` was:

```python
def exposure_box(ex: dict, high_volume: bool, cur: str = "EUR") -> str:
    """What the open PayPal disputes could cost: all won, ended like the last ones, all lost."""
    m = lambda v: f"{v:,.0f} {cur}"  # noqa: E731
    top = max(ex["all_lost"], 1)
    bars = [("If you win them all", ex["all_won"], "pass",
             "Nothing leaves your account." if not ex["all_won"] else "High-volume fee on every claim, even won."),
            (f"If they end like your last {ex['closed']} cases", ex["like_before"], "incon",
             f"{ex['share']:.0%} of the money disputed actually left your account." if ex["share"] is not None else "No closed cases yet to compare with."),
            ("If you lose them all", ex["all_lost"], "fail",
             f"Every refund, plus a {m(28 if high_volume else 14)} PayPal fee on each.")]
    chart = "".join(
        f'<li class="{cls}"><span class="x-label">{e(a)}</span><span class="x-track"><span class="x-bar" '
        f'style="width:{0 if v is None else max(0.4, 100 * v / top):.1f}%"></span></span>'
        f'<b>{"—" if v is None else e(m(v))}</b><span class="t-sub">{e(note)}</span></li>' for a, v, cls, note in bars)
    return (f'<section class="exposure"><h3>What the {ex["open"]} open PayPal disputes could cost</h3>'
            f'<p class="who">{m(ex["at_stake"])} in dispute. Money that would leave your account: refunds and '
            'PayPal dispute fees. When you refund, the goods and the postage are lost on top.</p>'
            f'<ul class="xchart">{chart}</ul></section>')


def paypal_block(ov: dict, cur: str = "EUR") -> str:
    """PayPal's own last 90 days, from its outcome codes: how the disputes ended."""
    m = lambda v: f"{v:,.0f} {cur}"  # noqa: E731
    c = ov["counts"]
    tiles = [("Handled", f'{ov["handled"]}', f'closed in the last {ov["window_days"]} days'),
             ("Settled before a claim", f'{ov["settled_before_claim"]} of {ov["handled"]}', "no PayPal dispute fee"),
             ("Money kept", m(ov["kept"]), "won, withdrawn, or closed with no claim"),
             ("Given back", m(ov["refunded"]), "refunds and accepted offers"),
             ("Dispute fees", m(ov["fees_paid"]), "estimated from PayPal's fee table")]
    kpis = "".join(f'<div class="tile"><span class="t-label">{e(a)}</span><b>{e(b)}</b><span class="t-sub">{e(x)}</span></div>'
                   for a, b, x in tiles)
    stayed = [(ledger.OUTCOME_LABEL[k], c[k]) for k in ("won", "withdrew", "closed") if c[k]]
    back = [(ledger.OUTCOME_LABEL[k], c[k]) for k in ("settled_offer", "refunded", "covered", "lost_claim", "lost_no_reply") if c[k]]
    return (f'<section class="paypal90"><h2>PayPal disputes, last {ov["window_days"]} days</h2>'
            f'<p class="who">{ov["disputes"]} disputes in {ov["orders"]:,} orders. From PayPal\'s own records: each '
            f'case\'s stage and outcome.</p><div class="kpis">{kpis}</div>'
            f'<h3 class="bl-h">The money stayed with you</h3>{bar_list(stayed, ov["handled"])}'
            f'<h3 class="bl-h">Money went back</h3>{bar_list(back, ov["handled"])}'
            f'<p class="cost-note">{ov["escalated"]} of {ov["handled"]} went past the inquiry to a PayPal claim.</p></section>')
```

Copy these from the current `overview_page` code and keep any wording it has that differs only in the heading
(`h2` → `h3` for the exposure box, "open cases" → "open PayPal disputes": the page now also counts open requests).

2. Delete `overview_page`, `overview_whatnow` and `month_block`. Then `grep -n "overview_page\|overview_whatnow\|month_block\|pill_for_on" secondlook/*.py`:
   `pill_for_on` may still be used by `pill_for` and the inbox; keep it if so.

3. Add, in the morning-screen section after `numbers_view`:

```python
# Numbers: each flow, its kind of figure, and what it counts.
NUMBERS = [("Orders", "orders", "n", "the shop's sales, for scale"),
           ("Requests, every channel", "requests", "n", "emails, web forms, calls and PayPal disputes, each problem once"),
           ("Solved before any PayPal dispute", "solved_before_dispute", "n", "shop requests closed"),
           ("Answered by Second Look's AI on its own", "ai_answered", "n", "under your setting, signed"),
           ("Staff time", "minutes", "min", "estimated: each written answer at your minutes, a call its own length"),
           ("Money given back", "back", "money", "refunds logged on your cases, and PayPal's"),
           ("PayPal dispute fees", "fees", "money", "estimated from PayPal's fee table")]


def _fmt(v, kind: str, cur: str) -> str:
    return f"{v:,.2f} {cur}" if kind == "money" else _hours(v) if kind == "min" else f"{v:,}"


def _change(a, b, kind: str, cur: str) -> str:
    """This period against the one before: "+2", "−19.50 EUR", "+30 min", or "same"."""
    d = a - b
    if abs(d) < 0.005:
        return "same"
    sign = "+" if d > 0 else "−"
    return sign + (f"{abs(d):,.2f} {cur}" if kind == "money" else _hours(abs(d)) if kind == "min" else f"{abs(d):,.0f}")


def _span(a, b) -> str:
    """Days, inclusive: "1–20 Oct", "28 Sep–4 Oct"."""
    return f"{a.day}–{b.day} {b:%b}" if (a.year, a.month) == (b.year, b.month) else f"{a.day} {a:%b}–{b.day} {b:%b}"


def both_sides_note(k: dict) -> str:
    both = k.get("both_sides") or []
    return (f'<p class="check-sender">{len(both)} order{"s" if len(both) != 1 else ""} counted on both sides: check '
            f'{"it was" if len(both) == 1 else "they were"} paid once ({e(", ".join(both))}): a refund logged on a case, '
            'and PayPal\'s.</p>' if both else "")


def export_link(today, q: str = "") -> str:
    """The facts for the accountant, this month: every money event, with order, invoice, item, who and channel."""
    return (f'<p class="cardlink"><a class="export" href="/books.csv?month={today:%Y-%m}{"&" + q[1:] if q else ""}">'
            f'Export for accounting (CSV, {today:%B %Y})</a> <span class="t-sub">the facts, never a credit note</span></p>')


def weeks_chart(weeks: list) -> str:
    """Requests, week by week, from the first week on record: one bar each, this week so far striped."""
    if not weeks:
        return ""
    top = max(w["requests"] for w in weeks) or 1
    bars = "".join(
        f'<li class="{"so-far" if w["so_far"] else ""}" title="Week of {w["first"].day} {w["first"]:%b}: '
        f'{w["requests"]} requests in {w["orders"]:,} orders{" (so far)" if w["so_far"] else ""}">'
        f'<span class="w-col"><span class="w-bar" style="height:{max(1.5, 100 * w["requests"] / top):.1f}%"></span></span>'
        f'<span class="w-label">{w["first"].day} {w["first"]:%b}<b>{w["requests"]}</b></span></li>' for w in weeks)
    first = weeks[0]["first"]
    return (f'<section class="weeks"><h2>Requests, week by week</h2><p class="t-sub">Monday to Sunday, the weeks on '
            f'record (from {first.day} {first:%b}). This week so far is striped.</p><ol class="wchart">{bars}</ol></section>')


def numbers_page(src: str, me: str | None = None, by: str = "month") -> str:
    """Numbers: every figure beside the same days of the period before (like for like), the weeks on record, what holds
    right now (no comparison: a snapshot), and PayPal's own last 90 days. Replaces the Overview (Claudia, 27/10:
    "benchmark weeks on weeks or months on months: better a dedicated space")."""
    demo = src == "demo"
    v = numbers_view(src, by)
    q, amp = ("?shop=demo", "&shop=demo") if demo else ("", "")
    k, a, b = v["month"], v["this"], v["before"]
    cur = k["currency"]
    if v["by"] == "week":
        now_words = f"This week so far ({_span(a['first'], a['last'])})"
        then_words = f"the same days last week ({_span(b['first'], b['last'])})" if b else "last week"
    else:
        now_words = f"{a['first']:%B} so far ({_span(a['first'], a['last'])})"
        then_words = (f"the same days of {b['first']:%B} ({_span(b['first'], b['last'])})" if b
                      else "the month before")
    here = ' aria-current="page"'
    tabs = "".join(f'<a href="/numbers?by={key}{amp}"{here if v["by"] == key else ""}>{label}</a>'
                   for key, label in (("week", "This week"), ("month", "This month")))
    rows = []
    for label, key, kind, note in NUMBERS:
        before, change = ((_fmt(b[key], kind, cur), _change(a[key], b[key], kind, cur)) if b else ("no record yet", ""))
        rows.append(f'<tr><th scope="row">{e(label)}<span class="t-sub">{e(note)}</span></th>'
                    f'<td>{e(_fmt(a[key], kind, cur))}</td><td>{e(before)}</td><td>{e(change)}</td></tr>')
        if key == "requests":
            per = lambda x: f'{100 * x["requests"] / x["orders"]:.1f}' if x["orders"] else "—"  # noqa: E731
            rows.append(f'<tr class="sub"><th scope="row">per 100 orders</th><td>{per(a)}</td>'
                        f'<td>{per(b) if b else ""}</td><td></td></tr>')
    then_head = _span(b["first"], b["last"]) if b else "Before"
    table = (f'<table class="compare"><thead><tr><th scope="col"></th><th scope="col">{e(_span(a["first"], a["last"]))}</th>'
             f'<th scope="col">{e(then_head)}</th><th scope="col">Change</th></tr></thead><tbody>{"".join(rows)}</tbody></table>')
    right_now = (f'<section class="right-now"><h2>Right now</h2><p class="t-sub">A snapshot: what holds today, so '
                 f'nothing to compare it with.</p><p><b>Open cases could still cost at most {k["could_still_cost"]:,.2f} '
                 f'{e(cur)}</b><span class="t-sub">every open PayPal dispute lost at claim ({k["open_disputes_most"]:,.2f} '
                 f'{e(cur)}) and every open request refunded in full ({k["open_inquiries_most"]:,.2f} {e(cur)})</span></p>'
                 f'{exposure_box(v["exposure"], v["paypal"]["high_volume"]["high_volume"], cur)}'
                 f'{claim_line_box(k["high_volume"], v["today"], cur)}</section>')
    about = f'<p class="demo-note">{e(DemoPayPal().shop["about"])}</p>' if demo else ""
    body = (f'<h1 class="page">Numbers</h1>{about}<p class="tabs">{tabs}</p>'
            f'<h2>{e(now_words)} against {e(then_words)}</h2>{table}{both_sides_note(k)}'
            f'{weeks_chart(v["weeks"])}{right_now}{paypal_block(v["paypal"], cur)}'
            f'{export_link(v["today"], q)}<p class="cardlink">The open cases, one by one: '
            f'<a href="/{q}">Disputes and requests</a> · <a href="/api/numbers{q}">these numbers as data (API)</a></p>')
    return page("Numbers | Second Look", "PayPal sandbox", body, demo, me=me, here="numbers")
```

4. Routes in `do_GET` — replace the `/overview` block with:

```python
            if u.path in ("/overview", "/overview/"):
                return self._redirect("/numbers" + (f"?{u.query}" if u.query else ""))   # an old link still works
            if u.path == "/numbers":
                if src == "practice":
                    return self._redirect("/?practice=1")    # practice cases are a test bench, not a shop's numbers
                return self._send(numbers_page(src, me=me, by=(qs.get("by") or ["month"])[0]))
```

5. `customer_page`: replace `f'<a class="back" href="/overview{q}">Overview</a>'` with
`f'<a class="back" href="/numbers{q}">Numbers</a>'`, and every `here="overview"` in that function with
`here="numbers"`.

6. CSS: add after the morning-screen CSS from Task 7 (braces doubled):

```
.tabs{{display:flex;gap:4px;margin:12px 0 20px}} .tabs a{{padding:6px 14px;border:1px solid var(--rule);text-decoration:none;color:var(--soft)}}
.tabs a[aria-current]{{background:var(--ink);color:var(--paper);border-color:var(--ink)}}
table.compare{{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--rule)}}
table.compare th,table.compare td{{text-align:right;padding:10px 14px;border-top:1px solid var(--rule);font-variant-numeric:tabular-nums}}
table.compare th[scope=row]{{text-align:left;font-weight:500}} table.compare th[scope=row] .t-sub{{display:block;font-weight:400}}
table.compare tr.sub th,table.compare tr.sub td{{border-top:0;padding-top:0;color:var(--soft);font-size:14px}}
.weeks,.right-now,.paypal90{{margin-top:36px}}
.wchart{{list-style:none;display:grid;grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);gap:2px;height:180px;padding:0;margin:12px 0 0}}
.wchart li{{display:grid;grid-template-rows:1fr auto;min-width:0}} .w-col{{display:flex;align-items:flex-end;border-bottom:1px solid var(--soft)}}
.w-bar{{display:block;width:100%;background:var(--pass);border-radius:4px 4px 0 0}} .wchart li:hover .w-bar{{opacity:.8}}
.wchart .so-far .w-bar{{background:repeating-linear-gradient(45deg,var(--pass) 0 3px,#E8F0EA 3px 6px)}}
.w-label{{font-size:13px;color:var(--soft);text-align:center;padding-top:6px}} .w-label b{{display:block;color:var(--ink);font-size:15px}}
@media (max-width:700px){{table.compare th,table.compare td{{padding:8px 6px;font-size:14px}}}}
```

- [ ] **Step 4: Run the whole suite** —
`for f in tests/test_*.py; do python3 "$f" >/dev/null || echo "FAIL $f"; done` → prints nothing.
`grep -rn "overview_page\|month_block\|today_view(\"demo\")\[\"know\"\]" secondlook tests` → nothing.

- [ ] **Step 5: Look at it** — as in Task 7 Step 5 (port 8791): `/numbers?shop=demo`, `/numbers?shop=demo&by=week`,
at full width and at 390 px. Check: the table's columns line up; the week bars stand on one baseline, the current
week striped; no horizontal scroll at 390 px; hover on a bar shows its tooltip.

- [ ] **Step 6: Commit**

```bash
git add secondlook/web.py tests/test_numbers.py tests/test_web.py
git commit -m "Numbers replaces the Overview: every flow beside the same days before, the weeks on record, snapshots apart; /overview redirects

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Whole-branch check

- [ ] **Step 1: The suite** — `for f in tests/test_*.py; do python3 "$f" >/dev/null || echo "FAIL $f"; done` → nothing.
- [ ] **Step 2: The 12-dispute snapshot is byte-identical**

```bash
SP=/private/tmp/claude-501/-Users-claudiamauri-Desktop-hackathons-paypal-ai/7fe40038-1fc8-4bbd-a54c-d74e1e02ecd1/scratchpad
python3 $SP/disputes_snapshot.py "$PWD" > $SP/mn-snap-after.json && cmp $SP/mn-snap-base.json $SP/mn-snap-after.json && echo SAME
```
Expected: `SAME`. If not, `diff` the two and report: the PayPal side must not move.
- [ ] **Step 3: Nothing written outside the bench** — `git status --short` shows no `.tmp/` or `records/` file.
- [ ] **Step 4: Report** the commits (`git log --oneline main..HEAD`) and the test count
(`grep -c "^def test_" tests/test_*.py | awk -F: '{s+=$2} END {print s}'`).

README, the film script, `HANDOVER.md` and `LOG.md` are the controller's, after review: not part of this plan.
