#!/usr/bin/env python3
"""Worker de STT de Nyx — corre en el VENV (~/.local/share/nyx/venv-voice).

Carga el modelo faster-whisper UNA vez (caliente) → READY. Luego, por stdin:
  start  -> graba el micro (pw-record raw 16k mono) y corta SOLA cuando detecta
            ~800 ms de silencio tras hablar (webrtcvad), o por 'stop', o tope 30 s.
  stop   -> corta ya (override manual del push-to-talk)
  quit   -> sale
Al cortar transcribe en español e imprime  TEXT:<transcripción>.
Lean: faster-whisper + webrtcvad + numpy (NO torch, NO CUDA). Solo stdlib + venv.
Config por env: NYX_STT_MODEL (def small), NYX_STT_SOURCE (target PipeWire; vacío=default).
"""

import os
import subprocess
import sys
import threading

MODEL = os.environ.get("NYX_STT_MODEL", "small")
SOURCE = os.environ.get("NYX_STT_SOURCE", "")

RATE = 16000
FRAME_MS = 20
FRAME_BYTES = int(RATE * FRAME_MS / 1000) * 2  # 640 (s16 mono 20ms)
SILENCE_HANG_MS = 800       # corta tras este silencio una vez ha habido voz
PRE_SPEECH_TIMEOUT_MS = 6000  # si no se habla nada, abandona
MAX_MS = 30000              # tope duro

_start = threading.Event()
_stop = threading.Event()


def _stdin_loop():
    for line in sys.stdin:
        cmd = line.strip()
        if cmd == "start":
            _start.set()
        elif cmd == "stop":
            _stop.set()
        elif cmd == "quit":
            os._exit(0)


def record_and_transcribe(model, vad) -> str:
    import numpy as np

    args = ["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16", "--raw"]
    if SOURCE:
        args += ["--target", SOURCE]
    args += ["-"]
    rec = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    pcm = bytearray()
    spoke = False
    silence_ms = 0
    pre_ms = 0
    total_ms = 0
    try:
        while True:
            if _stop.is_set():
                break
            frame = rec.stdout.read(FRAME_BYTES)
            if len(frame) < FRAME_BYTES:
                break
            pcm += frame
            total_ms += FRAME_MS
            try:
                speech = vad.is_speech(frame, RATE)
            except Exception:
                speech = True
            if speech:
                spoke = True
                silence_ms = 0
            elif spoke:
                silence_ms += FRAME_MS
            else:
                pre_ms += FRAME_MS
            if spoke and silence_ms >= SILENCE_HANG_MS:
                break  # auto-stop: ha callado
            if not spoke and pre_ms >= PRE_SPEECH_TIMEOUT_MS:
                break  # nada dicho
            if total_ms >= MAX_MS:
                break
    finally:
        rec.terminate()
        rec.wait()
    if not spoke or not pcm:
        return ""
    audio = np.frombuffer(bytes(pcm), dtype=np.int16).astype(np.float32) / 32768.0
    try:
        segs, _info = model.transcribe(audio, language="es", beam_size=1)
        return " ".join(s.text.strip() for s in segs).strip().replace("\n", " ")
    except Exception:
        return ""


def main() -> None:
    import webrtcvad
    from faster_whisper import WhisperModel

    model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    vad = webrtcvad.Vad(2)
    threading.Thread(target=_stdin_loop, daemon=True).start()
    print("READY", flush=True)
    while True:
        _start.wait()
        _start.clear()
        _stop.clear()
        text = record_and_transcribe(model, vad)
        print("TEXT:" + text, flush=True)


if __name__ == "__main__":
    main()
