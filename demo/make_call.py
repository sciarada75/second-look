"""Writes the demo shop's one phone call: Sophie (customer) calls Linen & Paper about her tablecloth, and Marta
(customer care assistant) answers. Made up, like everything in the demo shop, and voiced by Kokoro (an open-weight
text-to-speech model) with two voices, so a viewer hears two people.

What it writes, in demo/calls/ (the demo's "call box", as a shop's phone system would leave it):
  2026-10-19-0831-sophie.wav   the recording: 16 kHz, mono, 16-bit (what local transcription reads)
  2026-10-19-0831-sophie.json  what the phone system knows: the caller's number, when, how long
  2026-10-19-0831-sophie.txt   the transcript that ships with the demo, for a computer without local whisper

Run once, with Kokoro's own Python (it lives outside the repo, in ~/.local/share/kokoro):
  ~/.local/share/kokoro/venv/bin/python demo/make_call.py
The words are fixed below, so the transcript never depends on the voice. The recording is committed.
"""
import json
import os
import wave
from pathlib import Path

import numpy as np
from kokoro_onnx import EspeakConfig, Kokoro

HERE = Path(__file__).resolve().parent
NAME = "2026-10-19-0831-sophie"
CALLER = "+39 051 555 0142"           # Sophie's number, as on her order (demo/make_demo.py)
WHEN = "2026-10-19T08:31:00Z"
RATE = 16000
# (who, Kokoro voice, language, words): two clearly different voices, one for each person
LINES = [
    ("Marta", "bf_emma", "en-gb", "Linen and Paper, this is Marta. How can I help?"),
    ("Sophie", "af_nicole", "en-us", "Hello, this is Sophie Durand. I ordered a linen tablecloth, order L P nine zero "
                                     "zero zero one, and it still hasn't arrived. The tracking says delivered, but I "
                                     "have nothing."),
    ("Marta", "bf_emma", "en-gb", "I'm sorry to hear that. Let me look into it, and I'll write to you by email today."),
    ("Sophie", "af_nicole", "en-us", "Thank you. I'll send you an email too, with the order number."),
    ("Marta", "bf_emma", "en-gb", "Perfect. Have a good day, Sophie."),
]
# How the transcript writes what was said (the spoken order number written as the shop writes it)
WRITTEN = {"order L P nine zero zero zero one": "order LP-90001"}


def resample(audio, sr):
    """Kokoro's 24 kHz to 16 kHz, by linear interpolation: plenty for speech."""
    n = int(len(audio) * RATE / sr)
    return np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio)


def main():
    home = Path(os.environ.get("KOKORO_HOME", os.path.expanduser("~/.local/share/kokoro")))
    k = Kokoro(str(home / "model" / "kokoro-v1.0.onnx"), str(home / "model" / "voices-v1.0.bin"),
               espeak_config=EspeakConfig(data_path=str(home / "espeak-ng-data")))
    pause = np.zeros(int(0.5 * RATE))
    parts, script = [], []
    for who, voice, lang, words in LINES:
        audio, sr = k.create(words, voice=voice, speed=1.0, lang=lang)
        parts += [resample(np.asarray(audio, dtype=np.float64), sr), pause]
        said = words
        for spoken, written in WRITTEN.items():
            said = said.replace(spoken, written)
        script.append(f"{who}: {said}")
    audio = np.concatenate(parts)
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    (HERE / "calls").mkdir(exist_ok=True)
    with wave.open(str(HERE / "calls" / f"{NAME}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    seconds = round(len(pcm) / RATE)
    (HERE / "calls" / f"{NAME}.json").write_text(json.dumps(
        {"_comment": "Demo shop, made up: what the shop's phone system knows about one call. Written by demo/make_call.py.",
         "recording": f"{NAME}.wav", "from_phone": CALLER, "time": WHEN, "seconds": seconds}, indent=1) + "\n")
    (HERE / "calls" / f"{NAME}.txt").write_text("\n".join(script) + "\n")
    print(f"{NAME}.wav: {seconds} s, {len(pcm) * 2 // 1024} KB")


if __name__ == "__main__":
    main()
