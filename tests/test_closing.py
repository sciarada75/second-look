"""An answered shop request closes itself, as solved before any dispute, once the customer stays quiet for the shop's
days (policy.json "close_answered_after_days", 3). Code, not AI. Run: python3 tests/test_closing.py"""
import copy
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
        assert "Closed: solved before any dispute" in web.case_file_page("DEMO-C004", me="giulia")   # as a person's close reads


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
    with morning():                                                            # the rules page reads the demo's state
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


def test_an_open_paypal_dispute_on_the_case_s_order_keeps_it_open_even_before_it_is_linked():
    with morning():
        store = web.case_store("demo")
        orders = copy.deepcopy(web.shop_orders("demo"))
        sophie = store.get("DEMO-C001")
        o = next(o for o in orders if o.get("order_no") == sophie["order_no"])
        o["transaction_id"], o["paid_with"] = "TX-SOPHIE", "paypal"            # her order paid through PayPal
        web.shop_orders = lambda src: orders if src == "demo" else []          # the bench puts shop_orders back
        store.add("DEMO-C001", cases_mod.entry("2026-10-20T09:00", "email", "out", "We are on it.", "Marta"))
        disputes = web.shop_disputes("demo")
        d = copy.deepcopy(next(x for x in disputes if x.get("status") != "RESOLVED"))
        d.update(dispute_id="DEMO-NEW", create_time="2026-10-22T10:00:00Z", update_time="2026-10-22T10:00:00Z",
                 disputed_transactions=[{"seller_transaction_id": "TX-SOPHIE"}])
        kept = web.shop_disputes
        web.shop_disputes = lambda src: disputes + [d] if src == "demo" else kept(src)
        try:
            assert store.get("DEMO-C001").get("dispute_id") is None             # nothing has linked it yet
            with on_day(date(2026, 10, 23)):
                assert web.close_quiet("demo") == ["DEMO-C004"]                # Margot's; never Sophie's
        finally:
            web.shop_disputes = kept
        assert store.get("DEMO-C001")["status"] == "open"


def test_a_customer_s_message_filed_just_before_the_write_keeps_it_open():
    with morning():
        web.case_store("demo")
        kept, fired = cases_mod.CaseStore.update, []

        def update(self, cid, fn):
            if not fired and cid == "DEMO-C004":
                fired.append(1)       # Margot's email is filed (the store's lock only) after the re-check, before the write
                web.receive("demo", {"channel": "email", "text": "Still nothing. Order LP-90003.", "source_id": "race:1",
                                     "from": {"name": "Margot Lefèvre", "email": "margot.lefevre@example.com"}})
            return kept(self, cid, fn)
        cases_mod.CaseStore.update = update
        try:
            with on_day(date(2026, 10, 23)):
                assert web.close_quiet("demo") == []
        finally:
            cases_mod.CaseStore.update = kept
        assert fired and web.case_store("demo").get("DEMO-C004")["status"] == "open"


def test_a_refund_paypal_didn_t_confirm_keeps_it_open():
    mark = {"request_id": "sl-1", "kind": "refund", "amount": 36.0, "currency": "EUR", "at": "2026-10-20T07:41", "by": "Giulia"}
    assert cases_mod.closes_on(case(("2026-10-20T07:40", "in"), ("2026-10-20T07:41", "out"), unconfirmed=[mark]), 3) is None


def test_a_handoff_waiting_on_the_case_keeps_it_open():
    with morning() as b:
        web.case_store("demo")
        b.store.update("DEMO-C004", lambda a: {"to": "giulia", "handoff": {
            "from": "marta", "from_name": "Marta", "action": "REFUND", "amount": 36.0, "message": "Refund",
            "at": "2026-10-21T10:00"}})
        with on_day(date(2026, 10, 23)):
            assert web.close_quiet("demo") == []
        assert web.case_store("demo").get("DEMO-C004")["status"] == "open"


def test_the_last_word_is_the_last_one_filed_whatever_its_time():
    # a call transcribed after the shop's reply can carry an earlier time: the customer still spoke last
    assert cases_mod.closes_on(case(("2026-10-20T07:40", "in"), ("2026-10-20T10:00", "out"), ("2026-10-20T09:55", "in")),
                               3) is None


def test_it_is_stamped_on_the_day_it_was_due_not_the_day_someone_looked():
    with morning():
        web.case_store("demo")
        with on_day(date(2026, 10, 26)):
            assert web.close_quiet("demo") == ["DEMO-C004"]
        c = web.case_store("demo").get("DEMO-C004")
        assert c["closed_at"] == "2026-10-23T00:00" and c["timeline"][-1]["at"] == "2026-10-23T00:00"


def test_a_look_through_the_api_closes_what_is_due():
    with morning():
        with on_day(date(2026, 10, 23)):
            assert web.api_case_of("DEMO-C004")["status"] == "closed"


def test_a_call_waiting_in_the_box_is_filed_before_anything_closes():
    with morning():
        web.case_store("demo")
        kept = web.file_calls

        def file_calls(store, src, later=None):      # Margot called on 21 Oct; the call is filed at the next look
            if not any(x.get("source") == "call:margot" for x in store.get("DEMO-C004")["timeline"]):
                store.add("DEMO-C004", cases_mod.entry("2026-10-21T10:00", "call", "in", "Still nothing.",
                                                       "Margot Lefèvre", source="call:margot"))
            return 1
        web.file_calls = file_calls
        try:
            with on_day(date(2026, 10, 23)):
                web.today_view("demo", "giulia")
        finally:
            web.file_calls = kept
        assert web.case_store("demo").get("DEMO-C004")["status"] == "open"


def test_when_paypal_can_t_be_read_nothing_closes_on_that_look():
    with morning():
        store = web.case_store("live")
        code, out = web.receive("live", {"channel": "email", "text": "Where is my order?", "source_id": "live:1",
                                         "time": "2026-10-20T07:40:00Z",
                                         "from": {"name": "Ann Lee", "email": "ann@example.com"}})
        store.add(out["case_id"], cases_mod.entry("2026-10-20T08:00", "email", "out", "It is on its way.", "Giulia"))

        def down(*a):
            raise RuntimeError("PayPal answered 503")
        kept = (web.client_from_env, web.evidence_mod.shop_disputes, web.evidence_mod._orders)
        web.client_from_env = lambda root: object()                            # a live client, not the practice one
        web.evidence_mod.shop_disputes = web.evidence_mod._orders = down
        web._live_forget()
        try:
            with on_day(date(2026, 10, 30)):
                assert web.close_quiet("live") == []                           # an open dispute may be on it: unknown
                assert web.shop_disputes("live") == []                         # every other caller reads as before
        finally:
            web.client_from_env, web.evidence_mod.shop_disputes, web.evidence_mod._orders = kept
            web._live_forget()
        assert store.get(out["case_id"])["status"] == "open"


def test_every_look_files_the_call_box_first_and_waits_for_a_call_still_being_transcribed():
    with morning():
        web.case_store("demo")
        kept = web.file_calls

        def file_calls(store, src, later=None):      # Margot called on 21 Oct; the call is filed at the next look
            if not any(x.get("source") == "call:margot" for x in store.get("DEMO-C004")["timeline"]):
                store.add("DEMO-C004", cases_mod.entry("2026-10-21T10:00", "call", "in", "Still nothing.",
                                                       "Margot Lefèvre", source="call:margot"))
            return 1
        web.file_calls = file_calls
        try:
            with on_day(date(2026, 10, 23)):
                web.inbox_page("demo", me="giulia")                            # the Disputes list, not the morning screen
        finally:
            web.file_calls = kept
        assert web.case_store("demo").get("DEMO-C004")["status"] == "open"
    with morning():
        web.case_store("demo")
        kept = (web.calls_waiting, web.TRANSCRIBE)
        web.calls_waiting, web.TRANSCRIBE = (lambda store, src: 1), (lambda wav: None)   # whisper is on a recording
        try:
            with on_day(date(2026, 10, 23)):
                assert web.close_quiet("demo") == []
        finally:
            web.calls_waiting, web.TRANSCRIBE = kept
        with on_day(date(2026, 10, 23)):
            assert web.close_quiet("demo") == ["DEMO-C004"]                    # its words came: nothing else held it


def test_the_case_never_promises_a_day_it_won_t_close_on():
    with morning() as b:
        web.case_store("demo")
        assert "closes on 23 Oct" in web._closes_words(web.case_store("demo").get("DEMO-C004"))
        b.store.update("DEMO-C004", lambda a: {"to": "giulia", "handoff": {
            "from": "marta", "from_name": "Marta", "action": "REFUND", "amount": 36.0, "message": "Refund",
            "at": "2026-10-21T10:00"}})
        assert web._closes_words(web.case_store("demo").get("DEMO-C004")) == ""          # a handoff waits on it
        assert "closes on" not in web.case_file_page("DEMO-C004", me="giulia")
    with morning():
        web.case_store("demo")
        kept = web.close_quiet
        web.close_quiet = lambda src: []                                       # something held it past its day
        try:
            with on_day(date(2026, 10, 26)):
                assert web._closes_words(web.case_store("demo").get("DEMO-C004")) == ""
        finally:
            web.close_quiet = kept


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
