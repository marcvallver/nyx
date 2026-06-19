"""Extrae la última frase del asistente de un transcript de Claude Code.

Lo usa `nyx-bubble-capture` (hook Stop). Puro (solo stdlib) → testeable en CI.
Esquema verificado: cada línea es un registro JSON; los del asistente llevan
`type=="assistant"` y `message.content[]` con bloques `{"type":"text","text":…}`
(también puede haber bloques `thinking`/`tool_use`, que se ignoran).
"""

from __future__ import annotations

import json
from typing import Iterable


def extract_last_assistant_text(lines: Iterable[str]) -> str | None:
    """Devuelve el texto del ÚLTIMO mensaje de asistente con contenido textual."""
    last: str | None = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict) or rec.get("type") != "assistant":
            continue
        msg = rec.get("message") or {}
        parts = [
            block.get("text", "")
            for block in (msg.get("content") or [])
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        text = "".join(parts).strip()
        if text:
            last = text
    return last


def last_assistant_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return extract_last_assistant_text(f)
    except OSError:
        return None
