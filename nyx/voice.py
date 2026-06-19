"""Voz de Nyx.

F1 — TtsSpeaker: habla la respuesta de Claude FRASE A FRASE (efecto Siri), en un hilo
worker (NUNCA bloquea el bucle GLib). Backend pluggable: Piper (local, por defecto) con
fallback a espeak-ng si falta Piper/voz. El audio crudo se reproduce con `aplay` (ALSA→PipeWire).
(STT/SttListener llega en F2; barge-in afina stop() en F3.)
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading

VOICES_DIR = os.path.expanduser("~/.local/share/nyx/voices")
DEFAULT_VOICE = os.path.join(VOICES_DIR, "es_ES-davefx-medium.onnx")

# parte texto en frases completas (mantiene el resto para el siguiente chunk)
_SENT = re.compile(r".*?[.!?…\n]+", re.DOTALL)
# limpia markdown ligero para que no lea "asterisco asterisco"
_MD = re.compile(r"[*_`#>]+")


def _strip_md(text: str) -> str:
    return _MD.sub("", text).strip()


def _voice_rate(voice_onnx: str) -> int:
    try:
        with open(voice_onnx + ".json", encoding="utf-8") as f:
            return int(json.load(f).get("audio", {}).get("sample_rate", 22050))
    except (OSError, ValueError):
        return 22050


class TtsSpeaker:
    def __init__(self, voice: str = DEFAULT_VOICE):
        self.voice = voice
        self.enabled = False
        self._buf = ""
        self._q: queue.Queue[str] = queue.Queue()
        self._proc: subprocess.Popen | None = None
        self._piper = shutil.which("piper") or shutil.which("piper-tts")
        self._espeak = shutil.which("espeak-ng")
        self._rate = _voice_rate(voice)
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    # --- API (se llama desde el bucle GLib) ---
    def set_enabled(self, on: bool) -> None:
        self.enabled = bool(on)
        if not on:
            self.stop()

    def feed(self, chunk: str) -> None:
        """Acumula texto del streaming y encola las frases COMPLETAS."""
        if not self.enabled:
            return
        self._buf += chunk
        last = 0
        for m in _SENT.finditer(self._buf):
            sent = m.group().strip()
            if sent:
                self._q.put(sent)
            last = m.end()
        if last:
            self._buf = self._buf[last:]

    def flush(self) -> None:
        """Fin de turno: habla lo que quede en el buffer."""
        if not self.enabled:
            return
        rest = self._buf.strip()
        self._buf = ""
        if rest:
            self._q.put(rest)

    def stop(self) -> None:
        """Corta ya: vacía la cola y mata la reproducción en curso (disable / barge-in)."""
        self._buf = ""
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()

    # --- worker ---
    def _worker(self) -> None:
        while True:
            text = self._q.get()
            if self.enabled:
                self._speak(_strip_md(text))

    def _speak(self, text: str) -> None:
        if not text:
            return
        try:
            if self._piper and os.path.exists(self.voice):
                piper = subprocess.Popen(
                    [self._piper, "--model", self.voice, "--output_raw"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                play = subprocess.Popen(
                    ["aplay", "-q", "-r", str(self._rate), "-f", "S16_LE", "-c", "1", "-t", "raw", "-"],
                    stdin=piper.stdout, stderr=subprocess.DEVNULL,
                )
                with self._lock:
                    self._proc = play
                piper.stdin.write(text.encode("utf-8"))
                piper.stdin.close()
                play.wait()
                piper.wait()
            elif self._espeak:  # fallback robótico
                with self._lock:
                    self._proc = subprocess.Popen(
                        [self._espeak, "-v", "es", text], stderr=subprocess.DEVNULL
                    )
                self._proc.wait()
        except Exception:
            pass
        finally:
            with self._lock:
                self._proc = None
