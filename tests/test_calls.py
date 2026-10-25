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


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
