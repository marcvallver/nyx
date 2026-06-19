#!/usr/bin/env python3
"""Smoke test del backend Gemini TTS de Nyx.

Lee la key de ~/.config/nyx/gemini.key (o $GEMINI_API_KEY), sintetiza una frase con el
modelo/voz de ~/.config/nyx/config.json y la reproduce por el sink configurado (la Scarlett).
Si el modelo no existe (404/400), lista los modelos TTS disponibles para corregir config.

Uso:  PYTHONPATH=. python3 scripts/gemini_tts_smoke.py  ["texto opcional"]
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request

from nyx.voice import GEMINI_RATE, TtsSpeaker, _gemini_key


def list_tts_models(key: str) -> None:
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": key},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    for m in data.get("models", []):
        name = m.get("name", "")
        methods = m.get("supportedGenerationMethods", [])
        if "tts" in name.lower():
            print(f"   {name}  métodos={methods}")


def main() -> int:
    key = _gemini_key()
    if not key:
        print("Sin key: guarda ~/.config/nyx/gemini.key o exporta GEMINI_API_KEY")
        return 1
    tts = TtsSpeaker()
    print(f"modelo={tts.gemini_model}  voz={tts.gemini_voice}  sink={tts.sink or 'default'}")
    text = sys.argv[1] if len(sys.argv) > 1 else (
        "Hola Marc. Soy Nyx, tu asistente cyberpunk. Esta es mi voz neuronal por la nube. ¿Suena natural?"
    )
    try:
        pcm = tts._gemini_pcm(text)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        print(f"HTTP {e.code}: {body[:400]}")
        if e.code in (400, 404):
            print("Modelos TTS disponibles en tu cuenta:")
            try:
                list_tts_models(key)
            except Exception as ee:
                print("  (no pude listar modelos:", ee, ")")
        return 2
    except Exception as e:
        print("error:", e)
        return 3
    if not pcm:
        print("respuesta sin audio (revisa voz/modalidad)")
        return 4
    print(f"PCM recibido: {len(pcm)} bytes ({len(pcm) / 2 / GEMINI_RATE:.1f}s @ {GEMINI_RATE}Hz)")
    play = subprocess.Popen(tts._raw_player(GEMINI_RATE), stdin=subprocess.PIPE)
    play.communicate(pcm)
    print("reproducido por el sink configurado ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
