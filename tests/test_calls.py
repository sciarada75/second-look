"""Phone calls reach their case through the call box; the shop's orders and its courier answer through the API.
Run: python3 tests/test_calls.py (no test runs Kokoro or local whisper: both are faked)."""
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import wave
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secondlook import calls, demo as demo_mod, judge, sort as sort_mod, team as team_mod, web  # noqa: E402
from secondlook.demo import DemoPayPal  # noqa: E402
# Tests never run local whisper: a call's words are the transcript shipped beside it (26/10).
web.TRANSCRIBE = lambda wav: None

ROOT = Path(__file__).resolve().parent.parent
BOX = ROOT / "demo" / "calls"
SOPHIE = "2026-10-19-0831-sophie"


def test_the_demo_call_box_holds_sophie_s_call_as_a_phone_system_leaves_it():
    [rec] = calls.recordings(BOX)
    assert (rec["source_id"], rec["from_phone"], rec["time"]) == (f"callbox:{SOPHIE}", "+39 051 555 0142", "2026-10-19T08:31:00Z")
    with wave.open(str(rec["wav"])) as w:                # small: 16 kHz, mono, 16-bit, its length as the record says
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        assert round(w.getnframes() / 16000) == rec["seconds"] == 34
    shipped = rec["txt"].read_text()
    assert shipped.startswith("Marta: Linen and Paper") and "order LP-90001" in shipped and "Sophie:" in shipped


def test_local_whisper_first_then_the_shipped_transcript_labelled_then_nothing():
    [rec] = calls.recordings(BOX)
    assert calls.transcript(rec, lambda wav: "Hello, this is Sophie.") == ("Hello, this is Sophie.", calls.WHISPERED)
    text, how = calls.transcript(rec, lambda wav: None)
    assert how == "transcript shipped with the demo" and text.startswith("Marta:")
    box = Path(tempfile.mkdtemp())
    shutil.copy(rec["wav"], box / "a.wav")
    (box / "a.json").write_text(json.dumps({"recording": "a.wav", "from_phone": "+39 051 555 0142",
                                            "time": "2026-10-20T09:00:00Z", "seconds": 60}))
    (box / "b.json").write_text("{broken")                          # an unreadable record is skipped, not guessed
    (box / "c.json").write_text(json.dumps({"recording": "missing.wav", "from_phone": "1", "time": "x"}))
    [only] = calls.recordings(box)
    assert only["source_id"] == "callbox:a" and calls.as_request(only, lambda wav: None) is None   # no words: it waits
    req = calls.as_request(only, lambda wav: "My parcel never came.")
    assert (req["channel"], req["from"], req["minutes"], req["transcript"]) == (
        "call", {"name": None, "email": None, "phone": "+39 051 555 0142"}, 1.0, calls.WHISPERED)


def test_whisper_runs_in_its_own_python_offline_and_any_failure_is_simply_no_transcript():
    seen = []

    def run(cmd, **kw):
        seen.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, stdout="  Hello there.\n", stderr="")
    kept = calls.WHISPER_PYTHON
    try:
        calls.WHISPER_PYTHON = Path(sys.executable)                 # a Python that exists: the fake does the work
        assert calls.whisper(BOX / f"{SOPHIE}.wav", run=run) == "Hello there."
        cmd, kw = seen[0]
        assert cmd[0] == sys.executable and cmd[-1] == calls.WHISPER_MODEL and kw["env"]["HF_HUB_OFFLINE"] == "1"
        assert calls.whisper(BOX / f"{SOPHIE}.wav", run=lambda c, **k: subprocess.CompletedProcess(c, 1, "", "boom")) is None

        def broken(c, **k):
            raise subprocess.TimeoutExpired(c, 600)
        assert calls.whisper(BOX / f"{SOPHIE}.wav", run=broken) is None
        calls.WHISPER_PYTHON = Path(tempfile.mkdtemp()) / "no-python-here"
        assert calls.whisper(BOX / f"{SOPHIE}.wav", run=run) is None and len(seen) == 1   # not installed: never run
    finally:
        calls.WHISPER_PYTHON = kept


def test_a_call_is_sorted_by_the_caller_s_number_and_never_onto_two_customers():
    orders = [{"order_no": "LP-1", "email": "sophie@example.com", "name": "Sophie", "phone": "+39 051 555 0142",
               "time": "2026-10-12T10:00:00Z", "items": [{"item_name": "Linen tablecloth", "item_quantity": "1"}]},
              {"order_no": "LP-2", "email": "ann@example.com", "name": "Ann", "phone": "+43 1 555 0177",
               "time": "2026-10-12T10:00:00Z", "items": [{"item_name": "Linen shirt", "item_quantity": "1"}]},
              {"order_no": "LP-3", "email": "bob@example.com", "name": "Bob", "phone": "+43 1 555 0177",
               "time": "2026-10-12T10:00:00Z", "items": [{"item_name": "Art print", "item_quantity": "1"}]}]
    call = {"channel": "call", "from": {"phone": "0515550142"}, "subject": "Phone call", "text": "My tablecloth never came."}
    s = sort_mod.sort(call, orders, set())
    assert s["settled"] and s["order_no"] == "LP-1" and s["customer"]["email"] == "sophie@example.com"
    assert s["how"].startswith("Sorted by Second Look's rules: the caller's number is Sophie's")
    assert s["summary"] == "Phone call: says it never arrived"
    shared = sort_mod.sort({**call, "from": {"phone": "+43 1 555 0177"}}, orders, set())
    assert not shared["settled"] and shared["how"].startswith("The caller's number is on none of the shop's orders")


@contextmanager
def morning(live_box=None):
    """The demo shop's real data and its call box; its case file, assignments, reviews and logs in a temporary
    folder; no AI key; local whisper never runs. `live_box`: a call box for the live shop (a temporary folder)."""
    tmp = Path(tempfile.mkdtemp())
    kept = (web.CASE_FILES, web.OUTBOX_LOGS, web.REVIEWS, web.SUGGESTED, web.assignments_for, web.has_ai_key, web.notify,
            sort_mod.read_with_ai, judge.INQUIRY_BACKENDS["claude"], judge.BACKENDS["claude"], demo_mod.ACTION_LOG,
            web.CALL_BOXES, web.TRANSCRIBE)
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
        web.CALL_BOXES = {"demo": BOX, "live": live_box}
        web.TRANSCRIBE = lambda wav: None
        yield tmp
    finally:
        (web.CASE_FILES, web.OUTBOX_LOGS, web.REVIEWS, web.SUGGESTED, web.assignments_for, web.has_ai_key, web.notify,
         sort_mod.read_with_ai, judge.INQUIRY_BACKENDS["claude"], judge.BACKENDS["claude"], demo_mod.ACTION_LOG,
         web.CALL_BOXES, web.TRANSCRIBE) = kept


def test_sophie_calls_first_and_her_email_joins_the_same_case():
    with morning():
        c = web.case_store("demo").get("DEMO-C001")
        assert [(x["channel"], x["by"]) for x in c["timeline"]] == [("call", "Sophie Durand"), ("email", "Sophie Durand")]
        call = c["timeline"][0]
        assert (call["minutes"], call["transcript"], call["recording"]) == (0.57, calls.SHIPPED, f"{SOPHIE}.wav")
        assert c["order_no"] == "LP-90001" and "the caller's number is Sophie Durand's" in c["sorted"]["how"]
        assert web.case_view("DEMO-C001")["costs"]["minutes"] == 0.57          # a call's length is its staff time
        page = web.case_file_page("DEMO-C001", me="marta")
        assert "📞</span> Call in · Sophie Durand, <i>customer</i>" in page and "34 s call · transcript shipped with the demo" in page
        s = web.today_view("demo")["see"]
        assert s["counts"]["call"] == 1 and next(r for r in s["rows"] if r["case_id"] == "DEMO-C001")["channels"] == ["call", "email"]
        assert "📞 1 call" in web.today_page("demo", "giulia")


def test_a_new_recording_comes_in_once_and_without_a_call_box_the_phone_says_so():
    box = Path(tempfile.mkdtemp())
    with morning():
        assert "📞 Phone: not connected yet" in web.today_page("live")          # the live shop has no call box here
    with morning(live_box=box):
        assert web.today_view("live")["phone"] and web.case_store("live").all() == []
        shutil.copy(BOX / f"{SOPHIE}.wav", box / "call1.wav")
        (box / "call1.json").write_text(json.dumps({"recording": "call1.wav", "from_phone": "+1 555 000 1111",
                                                    "time": "2026-10-25T09:00:00Z", "seconds": 90}))
        (box / "call1.txt").write_text("My order never arrived.")
        web.today_view("live")
        web.today_view("live")                                               # the second look files nothing new
        [c] = web.case_store("live").all()
        assert c["timeline"][0]["minutes"] == 1.5 and c["sorted"]["by"] is None   # an unknown number: a person picks
        assert "The caller's number is on none of the shop's orders" in c["sorted"]["how"]


def test_the_shop_s_orders_and_courier_answer_through_the_api_labelled_made_up():
    with morning():
        o = web.order_record("demo", "lp-90001")
        assert (o["paid_with"], o["amount"], o["customer"]["name"]) == ("card", 64.0, "Sophie Durand")
        assert o["source"] == "Orders: made-up stand-in (demo shop)" and web.order_record("demo", "LP-0") is None
        t = web.tracking_record("demo", "LP-90002")
        assert t["tracking"]["delivered_to"] == "handed to the customer" and t["return"]["delivered_to"] == "the shop"
        assert web.tracking_record("demo", "DEMOTX02334")["tracking"]["tracking_number"] == "LC02334IT"   # DEMO-031's
        assert web.tracking_record("demo", "DEMOTX00001")["tracking"] is None
        sophie = web.customer_json("sophie.durand@example.com", "demo")    # she paid by card: no PayPal record
        assert (sophie["payer_id"], sophie["orders"], sophie["paid_with"], sophie["disputes"]) == (None, 1, ["card"], [])
        assert "paid by card" in web.customer_page("sophie.durand@example.com", "demo")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            def get(path):
                con = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
                con.request("GET", path)
                r = con.getresponse()
                return r.status, json.loads(r.read())
            assert get("/api/orders/LP-90001?shop=demo")[1]["paid_with"] == "card"
            assert get("/api/tracking/LP-90001?shop=demo")[1]["tracking"]["status"] == "DELIVERED"
            assert get("/api/orders/NOPE?shop=demo")[0] == 404
            assert get("/api/customers/sophie.durand@example.com?shop=demo")[1]["name"] == "Sophie Durand"
        finally:
            srv.shutdown()


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
