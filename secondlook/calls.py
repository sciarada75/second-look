"""The call box: a folder where the shop's phone system leaves its recorded calls. Each call is a recording (.wav)
and what the phone system knows about it (.json: the caller's number, when, how many seconds). The demo's call box
is demo/calls/; a shop points SECONDLOOK_CALL_BOX at its own.

Second Look turns each new recording into a request on the channel "call": it transcribes the recording on this
computer with local whisper (an open-weight speech-to-text model, if it is installed: nothing leaves the machine),
or, when it isn't, uses the transcript that ships beside the recording (.txt), labelled so. Without either, the call
waits. A call's length is its staff time. Nothing here calls a paid service.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import wave
from pathlib import Path

# Local whisper runs in its own Python (it needs packages Second Look doesn't): set SECONDLOOK_WHISPER_PYTHON to
# another one. The model is read from this computer's cache only (HF_HUB_OFFLINE): never downloaded mid-call.
WHISPER_PYTHON = Path(os.environ.get("SECONDLOOK_WHISPER_PYTHON",
                                     "~/.local/share/whisper/venv/bin/python")).expanduser()
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
_WHISPER = ("import sys, wave, numpy as np, mlx_whisper\n"
            "w = wave.open(sys.argv[1])\n"
            "a = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').astype(np.float32) / 32768\n"
            "print(mlx_whisper.transcribe(a, path_or_hf_repo=sys.argv[2], language='en')['text'].strip())\n")
SHIPPED = "transcript shipped with the demo"
MAX_TEXT = 10000                    # a call's words are capped like an email's (POST /api/requests)
WHISPERED = "transcribed on this computer (local whisper)"


def recordings(box: Path | None) -> list:
    """Every call in the box, oldest first: {source_id, wav, txt, from_phone, time, seconds}. A call whose recording
    or record is missing or unreadable is skipped, never guessed."""
    if not box or not Path(box).is_dir():
        return []
    out = []
    for meta in sorted(Path(box).glob("*.json")):
        try:
            m = json.loads(meta.read_text())
        except (OSError, ValueError):
            _skip(meta, "not readable JSON")
            continue
        if not isinstance(m, dict):
            _skip(meta, "not one JSON object")
            continue
        name = m.get("recording") or meta.stem + ".wav"
        # the recording is a file in the box itself: a plain name, never a path elsewhere
        if not isinstance(name, str) or "/" in name or "\\" in name or name.startswith("."):
            _skip(meta, "its recording is not a file name in the call box")
            continue
        if not isinstance(m.get("from_phone"), (str, int)) or not isinstance(m.get("time"), str):
            _skip(meta, "no caller's number or time")
            continue
        try:
            wav = meta.with_name(name)
        except ValueError:
            _skip(meta, "its recording is not a file name in the call box")
            continue
        if not wav.is_file() or not str(m["from_phone"]).strip() or not m["time"].strip():
            continue
        seconds = m.get("seconds")
        out.append({"source_id": f"callbox:{meta.stem}", "wav": wav, "txt": meta.with_suffix(".txt"),
                    "from_phone": str(m["from_phone"]), "time": str(m["time"]),
                    "seconds": float(seconds) if isinstance(seconds, (int, float)) and seconds > 0 else 0.0})
    return sorted(out, key=lambda r: r["time"])


def _skip(meta: Path, why: str) -> None:
    """A record the call box can't use: said once on the server's log, and the call is left out, never guessed."""
    print(f"call box: skipped {meta.name}: {why}", file=sys.stderr)


def _seconds(wav: Path) -> float:
    try:
        with wave.open(str(wav)) as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except (OSError, EOFError, wave.Error):
        return 0.0


def whisper(wav: Path, run=subprocess.run) -> str | None:
    """The recording's words by local whisper, or None when it isn't installed, fails or hears nothing. It runs
    outside any page or API request (web.transcribe_calls, in the server's background), with a time limit of ten
    times the recording's length (at least a minute, at most ten)."""
    if not WHISPER_PYTHON.is_file():
        return None
    limit = int(min(600, max(60, 10 * round(_seconds(wav)))))
    try:
        r = run([str(WHISPER_PYTHON), "-c", _WHISPER, str(wav), WHISPER_MODEL], capture_output=True, text=True,
                timeout=limit, env={**os.environ, "HF_HUB_OFFLINE": "1"})
    except (OSError, subprocess.SubprocessError):
        return None
    text = (r.stdout or "").strip() if r.returncode == 0 else ""
    return text or None


def transcript(rec: dict, transcribe=whisper) -> tuple:
    """(words, how): local whisper first, else the transcript shipped beside the recording, else (None, None)."""
    text = transcribe(rec["wav"])
    if text:
        return text, WHISPERED
    try:
        shipped = rec["txt"].read_text().strip()
    except OSError:
        shipped = ""
    return (shipped, SHIPPED) if shipped else (None, None)


def as_request(rec: dict, transcribe=whisper) -> dict | None:
    """A call as a request, the shape POST /api/requests files: channel "call", the caller's number instead of an
    address, its transcript as the text, and its length in minutes (its staff time). None: no words to file yet."""
    text, how = transcript(rec, transcribe)
    if not text:
        return None
    return {"channel": "call", "from": {"name": None, "email": None, "phone": rec["from_phone"]}, "time": rec["time"],
            "subject": "Phone call", "text": text[:MAX_TEXT], "source_id": rec["source_id"],
            "minutes": round(rec["seconds"] / 60, 2), "transcript": how, "recording": rec["wav"].name}
