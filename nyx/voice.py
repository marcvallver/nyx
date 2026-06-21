"""Voz de Nyx.

TtsSpeaker: habla la respuesta de Claude por CHUNKS con prefetch (síntesis ‖ reproducción en
dos hilos → sin huecos; NUNCA bloquea el bucle GLib). Backend pluggable (`tts_backend`):
  - "edge"   → voces neuronales de MS Edge vía edge-tts (GRATIS, sin key) — por defecto.
  - "gemini" → voz neuronal HD por la nube (REST, sin SDK), opt-in con API key.
  - "piper"  → local sin red. Cascada de fallback: edge → piper → espeak-ng.
El audio crudo (s16 mono) se reproduce vía pw-play al sink configurado (la Scarlett) o aplay.
"""

from __future__ import annotations

import base64
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import urllib.request

from . import markup, phonetics

VOICES_DIR = os.path.expanduser("~/.local/share/nyx/voices")
DEFAULT_VOICE = os.path.join(VOICES_DIR, "es_ES-davefx-medium.onnx")
CONFIG_PATH = os.path.expanduser("~/.config/nyx/config.json")

# --- edge-tts (voces neuronales de Microsoft Edge, GRATIS, sin key/cuota) ---
EDGE_BIN = os.path.expanduser("~/.local/share/nyx/venv-voice/bin/edge-tts")
EDGE_RATE = 24000  # edge-tts entrega mp3; lo decodificamos a PCM s16le 24kHz mono con ffmpeg

# --- Gemini TTS (nube, opcional) ---
GEMINI_KEY_FILE = os.path.expanduser("~/.config/nyx/gemini.key")  # fuera de git
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_RATE = 24000  # Gemini TTS devuelve PCM s16le 24kHz mono


def _gemini_key() -> str:
    """API key de AI Studio: env GEMINI_API_KEY o ~/.config/nyx/gemini.key. '' si no hay."""
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if k:
        return k
    try:
        with open(GEMINI_KEY_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def load_config() -> dict:
    """Lee ~/.config/nyx/config.json (enrutado de audio, voz, toggles). {} si falta/roto."""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
            return cfg if isinstance(cfg, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:  # JSONDecodeError ⊂ ValueError → no tragar en silencio
        print(f"nyx: config.json no usable, usando defaults: {e}", file=sys.stderr)
        return {}


def save_config(updates: dict) -> None:
    """Mezcla `updates` en config.json y reescribe ATÓMICAMENTE (tmp + os.replace), sin perder
    las demás claves (sink, voz, key…). Lo usa el toggle de voz para que la decisión de Marc
    persista entre reinicios del daemon. ensure_ascii=False conserva tildes (p.ej. gemini_style)."""
    cfg = load_config()
    cfg.update(updates)
    tmp = CONFIG_PATH + ".tmp"
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, CONFIG_PATH)  # atómico: nunca deja el config a medias
    except OSError as e:
        print(f"nyx: no pude guardar config.json: {e}", file=sys.stderr)


def _resolve_voice(voice: str) -> str:
    """Acepta ruta absoluta, nombre.onnx, o nombre pelado → ruta en VOICES_DIR."""
    if os.path.isabs(voice):
        return voice
    if not voice.endswith(".onnx"):
        voice += ".onnx"
    return os.path.join(VOICES_DIR, voice)

# parte texto en frases completas (mantiene el resto para el siguiente chunk)
_SENT = re.compile(r".*?[.!?…\n]+", re.DOTALL)
# emojis y símbolos que NO se deben LEER en voz (sí se ven en el bocadillo)
_EMOJI = re.compile(
    "["
    "\U0001f000-\U0001faff"  # emoji / pictogramas / transporte / banderas
    "\U00002600-\U000027bf"  # símbolos misc + dingbats (✶ ✻ ✅ ✨)
    "\U00002190-\U000021ff"  # flechas (→ ←)
    "\U00002b00-\U00002bff"  # símbolos y flechas misc (⭐ ⬛)
    "\U00002500-\U000025ff"  # box-drawing + bloques + formas (─ │ ● ■)
    "\U0000fe00-\U0000fe0f"  # selectores de variación
    "•‣⁃‍"  # viñetas (•) + ZWJ
    "]+"
)
_WS = re.compile(r"[ \t]{2,}")
# respelling SOLO para la voz: que el TTS pronuncie nombres bien (el bocadillo muestra el original).
# "Nyx" → "Niks" para que Ximena lo diga /niks/ (≈ IPA /nˈɪks/; el español no tiene ɪ).
_PRONUN = [(re.compile(r"\bNyx\b", re.IGNORECASE), "Niks")]


def _strip_md(text: str) -> str:
    """Texto para VOZ: quita la estructura markdown (vía `markup.to_plain`) y los emojis/símbolos
    (se leen raro), conserva la puntuación, y aplica respelling de pronunciación. El bocadillo
    SÍ muestra todo (con 'Nyx' y emojis)."""
    s = markup.to_plain(text)
    s = _EMOJI.sub("", s)
    for pat, rep in _PRONUN:
        s = pat.sub(rep, s)
    s = phonetics.respell(s)  # términos ingleses → grafía es-ES (solo voz)
    return _WS.sub(" ", s).strip()


def split_sentences(buf: str) -> tuple[list[str], str]:
    """Separa `buf` en (frases completas, resto incompleto).

    Una frase termina en . ! ? … o salto de línea. El resto (sin terminador) se
    devuelve para acumularlo con el siguiente chunk del streaming. Función PURA (testeable)."""
    sents: list[str] = []
    last = 0
    for m in _SENT.finditer(buf):
        s = m.group().strip()
        if s:
            sents.append(s)
        last = m.end()
    return sents, buf[last:]


# umbral de agrupado para TTS: por debajo se espera (respuesta entera = mejor prosodia y 1 sola llamada)
TTS_CHUNK_CHARS = 280


def group_chunks(buf: str, min_chars: int = TTS_CHUNK_CHARS) -> tuple[list[str], str]:
    """Agrupa frases en chunks GRANDES para el TTS: emite un párrafo completo (\\n\\n) o una
    tanda de frases que ya sume >= min_chars; lo más corto se queda en el resto (→ flush).
    Sintetizar trozos grandes da prosodia natural y gasta menos cuota. Pura/testeable."""
    chunks: list[str] = []
    while "\n\n" in buf:  # párrafos completos
        head, buf = buf.split("\n\n", 1)
        head = head.strip()
        if head:
            chunks.append(head)
    sents, rest = split_sentences(buf)  # tandas de frases hasta el umbral
    acc = ""
    for s in sents:
        acc = f"{acc} {s}".strip()
        if len(acc) >= min_chars:
            chunks.append(acc)
            acc = ""
    buf = f"{acc} {rest}".strip() if acc else rest  # lo corto vuelve al buffer
    return chunks, buf


def _voice_rate(voice_onnx: str) -> int:
    try:
        with open(voice_onnx + ".json", encoding="utf-8") as f:
            return int(json.load(f).get("audio", {}).get("sample_rate", 22050))
    except (OSError, ValueError):
        return 22050


class TtsSpeaker:
    def __init__(self, voice: str | None = None, sink: str | None = None):
        cfg = load_config()
        self.voice = _resolve_voice(voice or cfg.get("voice") or DEFAULT_VOICE)
        # node.name del sink de salida (vacío = sink por defecto del sistema vía aplay)
        self.sink = sink if sink is not None else cfg.get("tts_sink", "")
        self.enabled = bool(cfg.get("tts_enabled", False))
        # backend: "edge" (gratis, por defecto) · "gemini" (nube HD opt-in) · "piper" (local).
        # Cascada de fallback edge→piper→espeak si el elegido falla (sin red/cuota/binario).
        self.backend = (cfg.get("tts_backend") or "edge").lower()
        self.gemini_model = cfg.get("gemini_tts_model", "gemini-2.5-flash-preview-tts")
        self.gemini_voice = cfg.get("gemini_voice", "Kore")  # voz prebuilt (femenina)
        self.gemini_style = cfg.get("gemini_style", "")  # instrucción de estilo opcional
        self._gemini_key = _gemini_key()
        self.edge_voice = cfg.get("edge_voice", "es-ES-XimenaNeural")  # voz neuronal MS gratis
        self._edge = EDGE_BIN if os.path.exists(EDGE_BIN) else shutil.which("edge-tts")
        self._buf = ""
        self._gen = 0  # generación: stop() la incrementa para descartar trabajo en vuelo
        self._text_q: queue.Queue[tuple[int, str]] = queue.Queue()  # frases a sintetizar
        self._audio_q: queue.Queue[tuple[int, bytes, int]] = queue.Queue(maxsize=6)  # PCM listo
        self._proc: subprocess.Popen | None = None
        self._piper = shutil.which("piper") or shutil.which("piper-tts")
        self._espeak = shutil.which("espeak-ng")
        self._pwplay = shutil.which("pw-play")
        self._ffmpeg = shutil.which("ffmpeg")  # decodifica el mp3 de edge-tts a PCM
        self.speaker = cfg.get("tts_speaker", "")  # id de locutor para voces multi-speaker
        self._rate = _voice_rate(self.voice)
        self._lock = threading.Lock()
        # pipeline: el sintetizador va POR DELANTE del reproductor (prefetch → sin huecos)
        threading.Thread(target=self._synth_worker, daemon=True).start()
        threading.Thread(target=self._play_worker, daemon=True).start()

    def _raw_player(self, rate: int | None = None) -> list[str]:
        """Reproductor de PCM crudo s16 mono al rate dado (def: el de la voz). Enruta al
        sink configurado vía pw-play; si no, aplay al default del sistema."""
        r = str(rate or self._rate)
        if self.sink and self._pwplay:
            return [self._pwplay, "--target", self.sink, "--rate", r,
                    "--channels", "1", "--format", "s16", "--raw", "-"]
        return ["aplay", "-q", "-r", r, "-f", "S16_LE", "-c", "1", "-t", "raw", "-"]

    # --- API (se llama desde el bucle GLib) ---
    def set_enabled(self, on: bool, persist: bool = False) -> None:
        """Activa/silencia la voz. Al silenciar corta lo que esté sonando. Con persist=True
        guarda la decisión en config.json (tts_enabled) para que sobreviva al reinicio."""
        self.enabled = bool(on)
        if not self.enabled:
            self.stop()
        if persist:
            save_config({"tts_enabled": self.enabled})

    def toggle(self, persist: bool = True) -> bool:
        """Alterna la voz y devuelve el nuevo estado. Persiste por defecto: 'cuando Marc decida'
        significa que la decisión se respeta también tras reiniciar el daemon."""
        self.set_enabled(not self.enabled, persist=persist)
        return self.enabled

    def feed(self, chunk: str) -> None:
        """Acumula texto del streaming y encola CHUNKS GRANDES para sintetizar (mejor
        prosodia, menos llamadas). Una respuesta breve sale entera en flush = 1 sola llamada."""
        if not self.enabled:
            return
        self._buf += chunk
        chunks, self._buf = group_chunks(self._buf)
        for c in chunks:
            self._text_q.put((self._gen, c))

    def flush(self) -> None:
        """Fin de turno: sintetiza lo que quede en el buffer."""
        if not self.enabled:
            return
        rest = self._buf.strip()
        self._buf = ""
        if rest:
            self._text_q.put((self._gen, rest))

    def stop(self) -> None:
        """Corta ya: invalida lo en vuelo, vacía colas y mata la reproducción
        (disable / barge-in / turno nuevo)."""
        self._buf = ""
        self._gen += 1  # frases/PCM con gen anterior se descartan en los workers
        for q in (self._text_q, self._audio_q):
            try:
                while True:
                    q.get_nowait()
            except queue.Empty:
                pass
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()

    # --- pipeline: síntesis (productor) ‖ reproducción (consumidor) ---
    def _synth_worker(self) -> None:
        """Sintetiza frases POR ADELANTADO y deja el PCM listo en _audio_q (prefetch:
        mientras suena una frase, la siguiente ya se está sintetizando → sin huecos)."""
        while True:
            gen, text = self._text_q.get()
            if gen != self._gen or not self.enabled:
                continue
            pcm, rate = self._synth(_strip_md(text))
            if pcm and gen == self._gen and self.enabled:
                self._audio_q.put((gen, pcm, rate))

    def _play_worker(self) -> None:
        """Reproduce el PCM ya sintetizado, en orden y sin pausas entre frases."""
        while True:
            gen, pcm, rate = self._audio_q.get()
            if gen != self._gen or not self.enabled:
                continue
            self._play_pcm(pcm, rate)

    def _synth(self, text: str) -> tuple[bytes, int]:
        """Texto → (PCM s16le mono, rate). Gemini (nube HD) → Piper → espeak.
        Cada clip lleva un colchón de silencio para que pw-play no corte la cola."""
        if not text:
            return b"", 0
        if self.backend == "edge" and self._edge and self._ffmpeg:
            try:
                pcm = self._edge_pcm(text)
                if pcm:
                    return self._pad(pcm, EDGE_RATE), EDGE_RATE
            except Exception as e:  # sin red → cae a local sin que se note
                sys.stderr.write(f"nyx: edge-tts falló ({e}); fallback local\n")
                sys.stderr.flush()
        if self.backend == "gemini" and self._gemini_key:
            try:
                pcm = self._gemini_pcm(text)
                if pcm:
                    return self._pad(pcm, GEMINI_RATE), GEMINI_RATE
            except Exception as e:  # sin red/cuota/key/modelo → cae a local sin que se note
                sys.stderr.write(f"nyx: Gemini TTS falló ({e}); fallback local\n")
                sys.stderr.flush()
        if self._piper and os.path.exists(self.voice):
            pcm = self._piper_pcm(text)
            if pcm:
                return self._pad(pcm, self._rate), self._rate
        if self._espeak:
            pcm = self._espeak_pcm(text)
            if pcm:
                return self._pad(pcm, 22050), 22050
        return b"", 0

    @staticmethod
    def _pad(pcm: bytes, rate: int, ms: int = 120) -> bytes:
        """~ms de silencio al final: evita que pw-play corte la última sílaba al cerrar."""
        return pcm + b"\x00" * (int(rate * ms / 1000) * 2)

    def _piper_pcm(self, text: str) -> bytes:
        args = [self._piper, "--model", self.voice]
        if self.speaker != "":
            args += ["--speaker", str(self.speaker)]  # voces multi-locutor (sharvard F=1)
        p = subprocess.run(
            [*args, "--output_raw"], input=text.encode("utf-8"),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        return p.stdout

    def _espeak_pcm(self, text: str) -> bytes:
        """espeak-ng --stdout (WAV) → PCM crudo s16 22050 (quita la cabecera WAV de 44 bytes)."""
        p = subprocess.run(
            [self._espeak, "-v", "es", "--stdout", text],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        wav = p.stdout
        return wav[44:] if len(wav) > 44 else b""

    def _play_pcm(self, pcm: bytes, rate: int) -> None:
        try:
            play = subprocess.Popen(
                self._raw_player(rate), stdin=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
            with self._lock:
                self._proc = play
            play.stdin.write(pcm)
            play.stdin.close()
            play.wait()
        except Exception:
            pass
        finally:
            with self._lock:
                self._proc = None

    def _edge_pcm(self, text: str) -> bytes:
        """edge-tts (voces neuronales de MS Edge, gratis, mp3) → PCM s16le 24kHz mono vía ffmpeg.
        Bloqueante (corre en el hilo de síntesis, nunca en el bucle GLib)."""
        edge = subprocess.Popen(
            [self._edge, "--voice", self.edge_voice, "--text", text, "--write-media", "/dev/stdout"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        ff = subprocess.Popen(
            [self._ffmpeg, "-loglevel", "error", "-i", "pipe:0",
             "-f", "s16le", "-ar", str(EDGE_RATE), "-ac", "1", "pipe:1"],
            stdin=edge.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        edge.stdout.close()  # ffmpeg es el único lector del pipe de edge
        pcm, _ = ff.communicate()
        edge.wait()
        return pcm

    def _gemini_pcm(self, text: str) -> bytes:
        """POST a Gemini generateContent (modalidad AUDIO) → PCM s16le 24kHz. Bloqueante
        (corre en el hilo worker del TTS, nunca en el bucle GLib)."""
        prompt = f"{self.gemini_style}: {text}" if self.gemini_style else text
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.gemini_voice}}
                },
            },
        }
        req = urllib.request.Request(
            GEMINI_ENDPOINT.format(model=self.gemini_model),
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": self._gemini_key},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.load(resp)
        for part in payload["candidates"][0]["content"]["parts"]:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
        return b""


# --- STT (escuchar): worker persistente en el venv, controlado por stdin ---
VENV_PY = os.path.expanduser("~/.local/share/nyx/venv-voice/bin/python")
STT_WORKER = os.path.join(os.path.dirname(os.path.realpath(__file__)), "stt_worker.py")
STT_LOG = os.path.expanduser("~/.cache/nyx/stt.log")


class SttListener:
    """Push-to-talk: arranca/para la grabación y transcribe. El modelo vive caliente en
    un worker del venv (faster-whisper); el daemon lo controla por stdin y lee el texto.
    `on_text(text)` se llama desde un hilo → el app debe marshalear con GLib.idle_add."""

    def __init__(self, on_text, source: str | None = None, model: str | None = None):
        cfg = load_config()
        # node.name del micro (vacío = fuente por defecto de PipeWire)
        self.source = source if source is not None else cfg.get("stt_source", "")
        self.model = model if model is not None else cfg.get("stt_model", "")
        self.on_text = on_text
        self.recording = False
        self.ready = False
        self._proc: subprocess.Popen | None = None
        if os.path.exists(VENV_PY) and os.path.exists(STT_WORKER):
            self._start_worker()

    def available(self) -> bool:
        return self._proc is not None

    def ready_to_record(self) -> bool:
        """True solo si el worker existe Y el modelo ya cargó (READY)."""
        return self._proc is not None and self.ready

    def _start_worker(self):
        env = os.environ.copy()
        env["NYX_STT_SOURCE"] = self.source or ""  # nunca None (rompería Popen)
        if self.model:
            env["NYX_STT_MODEL"] = self.model
        try:
            os.makedirs(os.path.dirname(STT_LOG), exist_ok=True)
            log = open(STT_LOG, "a")  # stderr del worker → log (carga modelo, pw-record…)
            self._proc = subprocess.Popen(
                [VENV_PY, STT_WORKER],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=log, env=env, text=True, bufsize=1,
            )
        except OSError:
            self._proc = None
            return
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        if not self._proc or not self._proc.stdout:
            return
        for line in self._proc.stdout:
            line = line.rstrip("\n")
            if line == "READY":
                self.ready = True
            elif line.startswith("TEXT:"):
                self.recording = False
                self.on_text(line[5:].strip())  # vacío incluido (el app decide)
        # EOF: el worker murió → no mentir con available()/ready
        self.ready = False
        self.recording = False
        self._proc = None

    def toggle(self) -> bool:
        if self.recording:
            self.stop()
        else:
            self.start()
        return self.recording

    def start(self):
        if self.recording or not self.ready_to_record():
            return
        self.recording = True
        if not self._send("start"):  # worker caído → no quedarse pegado en recording
            self.recording = False

    def stop(self):
        if not self.recording:
            return
        self._send("stop")  # recording baja al recibir TEXT

    def _send(self, cmd: str) -> bool:
        try:
            self._proc.stdin.write(cmd + "\n")
            self._proc.stdin.flush()
            return True
        except (OSError, ValueError, AttributeError):
            self.ready = False  # worker no escribible → degradar a no-disponible
            self.recording = False
            return False

    def close(self) -> None:
        """Termina el worker del venv (al cerrar el daemon). Evita huérfanos. Idempotente."""
        p, self._proc = self._proc, None
        self.ready = False
        self.recording = False
        if not p or p.poll() is not None:
            return
        self._send_raw(p, "quit")  # el worker hace os._exit(0); funciona incluso grabando
        try:
            p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            p.terminate()
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                p.kill()

    @staticmethod
    def _send_raw(proc: subprocess.Popen, cmd: str) -> None:
        try:
            proc.stdin.write(cmd + "\n")
            proc.stdin.flush()
        except (OSError, ValueError, AttributeError):
            pass
