#!/usr/bin/env python3
"""Worker de STT de Nyx — corre en el VENV (~/.local/share/nyx/venv-voice), NO en el
python del daemon (que es del sistema y no tiene faster-whisper).

Carga el modelo UNA vez (caliente) e imprime READY. Luego, por stdin:
  start  -> empieza a grabar el micro con pw-record a un WAV temporal
  stop   -> para, transcribe en español e imprime  TEXT:<transcripción>
  quit   -> sale
Standalone: solo faster-whisper + stdlib (no importa el paquete nyx ni GTK).
Config por env: NYX_STT_MODEL (def. small), NYX_STT_SOURCE (target PipeWire; vacío=default).
"""

import os
import subprocess
import sys
import tempfile

MODEL = os.environ.get("NYX_STT_MODEL", "small")
SOURCE = os.environ.get("NYX_STT_SOURCE", "")


def main() -> None:
    from faster_whisper import WhisperModel

    model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    print("READY", flush=True)

    rec: subprocess.Popen | None = None
    wav: str | None = None
    for line in sys.stdin:
        cmd = line.strip()
        if cmd == "start":
            if rec is not None:
                continue
            wav = tempfile.mktemp(suffix=".wav", prefix="nyx-stt-")
            args = ["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16"]
            if SOURCE:
                args += ["--target", SOURCE]
            args += [wav]
            rec = subprocess.Popen(args, stderr=subprocess.DEVNULL)
        elif cmd == "stop":
            if rec is not None:
                rec.terminate()
                rec.wait()
                rec = None
            text = ""
            if wav and os.path.exists(wav):
                try:
                    segs, _info = model.transcribe(wav, language="es", beam_size=1)
                    text = " ".join(s.text.strip() for s in segs).strip()
                except Exception:
                    text = ""
                try:
                    os.remove(wav)
                except OSError:
                    pass
            wav = None
            print("TEXT:" + text.replace("\n", " "), flush=True)
        elif cmd == "quit":
            break


if __name__ == "__main__":
    main()
