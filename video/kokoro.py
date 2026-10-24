#!/usr/bin/env python3
# The film's voice since draft 9: Kokoro (open-weight neural TTS, Apache-2.0), voice af_heart.
# narrate.mjs calls this once with every line to speak, as JSON on stdin:
#   [{"text": "...", "out": "/abs/path/s1a.wav"}, ...]
# and gets one 24 kHz mono WAV per line; narrate.mjs converts them to the film's 48 kHz.
#
# Kokoro lives outside the repo, in ~/.local/share/kokoro (venv, model, espeak-ng data):
#   KOKORO_HOME/venv/bin/python kokoro.py   (narrate.mjs does this for you)
# espeak-ng truncates its data path at about 160 characters, so the data sits at a short path of
# its own and is passed in explicitly (24/10: the copy inside the venv's site-packages fails).

import json
import os
import sys

import soundfile as sf
from kokoro_onnx import EspeakConfig, Kokoro

home = os.environ.get("KOKORO_HOME", os.path.expanduser("~/.local/share/kokoro"))
voice = os.environ.get("KOKORO_VOICE", "af_heart")
lang = os.environ.get("KOKORO_LANG", "en-us")

k = Kokoro(f"{home}/model/kokoro-v1.0.onnx", f"{home}/model/voices-v1.0.bin",
           espeak_config=EspeakConfig(data_path=f"{home}/espeak-ng-data"))
for job in json.load(sys.stdin):
    audio, sr = k.create(job["text"], voice=voice, speed=1.0, lang=lang)
    sf.write(job["out"], audio, sr)
