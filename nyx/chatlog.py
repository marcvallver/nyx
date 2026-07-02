"""Hilo de chat persistente de la sesión core de Nyx (JSONL en disco) — PURO
(sin gi), testeable en CI. El panel de historial se rellena de aquí al arrancar,
para que Marc no pierda el hilo de SU conversación con Nyx entre reinicios.

Un registro por línea: {"role": "operativo"|"Nyx", "text": str, "mood": str, "ts": float}.
"""

from __future__ import annotations

import json
import os

CHAT_LOG = os.path.expanduser("~/.local/state/nyx/chat.jsonl")
MAX_LINES = 2000  # al superarlo, rotate() recorta al último millar
KEEP_LINES = 1000


def append_turn(role: str, text: str, mood: str = "normal",
                ts: float | None = None, path: str | None = None) -> None:
    """Añade un turno al hilo (append-only, un JSON por línea). Nunca lanza."""
    p = path or CHAT_LOG
    rec = {"role": role, "text": text, "mood": mood, "ts": ts}
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass  # el hilo persistente es best-effort; el chat en vivo no depende de él


def load_recent(n: int = 50, path: str | None = None) -> list[dict]:
    """Los últimos `n` turnos válidos (líneas corruptas se saltan). [] si no hay."""
    p = path or CHAT_LOG
    try:
        with open(p, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in lines[-n:]:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("role") and rec.get("text"):
            out.append(rec)
    return out


def rotate(path: str | None = None, max_lines: int = MAX_LINES,
           keep: int = KEEP_LINES) -> bool:
    """Si el hilo supera `max_lines`, recorta al último `keep` (escritura atómica).
    Devuelve True si rotó. Pensado para llamarse una vez al arrancar."""
    p = path or CHAT_LOG
    try:
        with open(p, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return False
    if len(lines) <= max_lines:
        return False
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(lines[-keep:])
        os.replace(tmp, p)
        return True
    except OSError:
        return False


def archive(path: str | None = None) -> str | None:
    """Aparta el hilo actual a <path>.old (pisa el .old anterior) al empezar
    sesión nueva. Devuelve la ruta del archivo o None si no había hilo."""
    p = path or CHAT_LOG
    if not os.path.exists(p):
        return None
    dst = p + ".old"
    try:
        os.replace(p, dst)
        return dst
    except OSError:
        return None
