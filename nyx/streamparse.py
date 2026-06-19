"""Parser puro de los eventos `stream-json` del Claude Code CLI.

Sin dependencias de GTK (solo stdlib) para poder testearlo en CI. Convierte la
secuencia de eventos JSON que emite

    claude -p --output-format stream-json --include-partial-messages --verbose

en señales de alto nivel que la UI de Nyx consume (deltas de texto, fin de
turno, sesión, rate-limit...). Reutilizable entre turnos en un mismo proceso
persistente (`--input-format stream-json`).

Esquema verificado contra @anthropic-ai/claude-code 2.1.183.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class Init:
    """`system/init`: arranque de la sesión."""

    session_id: str | None
    model: str | None = None
    cwd: str | None = None
    tools: list[str] = field(default_factory=list)
    permission_mode: str | None = None


@dataclass
class Status:
    """`system/status`: p.ej. status="requesting"."""

    status: str


@dataclass
class TextDelta:
    """Fragmento de texto de la respuesta (streaming)."""

    text: str


@dataclass
class ThinkingDelta:
    """Fragmento de "extended thinking" (si está activo)."""

    text: str


@dataclass
class ToolUse:
    """El asistente va a usar una herramienta (inicio de bloque tool_use)."""

    name: str
    id: str | None = None


@dataclass
class AssistantMessage:
    """Mensaje completo del asistente; solo se emite como fallback si no hubo deltas."""

    text: str


@dataclass
class RateLimit:
    """`rate_limit_event`: info de cuota (suscripción Max, ventana de 5h, etc.)."""

    info: dict


@dataclass
class Result:
    """`result`: fin de turno, con métricas."""

    subtype: str
    text: str | None
    duration_ms: int | None = None
    cost_usd: float | None = None
    num_turns: int | None = None
    session_id: str | None = None
    is_error: bool = False


@dataclass
class Unknown:
    """Evento no reconocido; se preserva en crudo para no perder información."""

    raw: dict


Signal = (
    Init
    | Status
    | TextDelta
    | ThinkingDelta
    | ToolUse
    | AssistantMessage
    | RateLimit
    | Result
    | Unknown
)


class StreamParser:
    """Acumula el estado de un turno y emite señales.

    Uso típico::

        p = StreamParser()
        for line in proc_stdout:
            for sig in p.feed_line(line):
                ui.handle(sig)
    """

    def __init__(self) -> None:
        self.session_id: str | None = None
        self.text: str = ""  # texto acumulado del turno en curso

    def feed_line(self, line: str) -> list[Signal]:
        """Parsea una línea JSONL. Líneas vacías o no-JSON se ignoran (devuelven [])."""
        line = line.strip()
        if not line:
            return []
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            return []
        if not isinstance(ev, dict):
            return []
        return self.feed(ev)

    def feed(self, ev: dict) -> list[Signal]:
        t = ev.get("type")
        if t == "system":
            return self._system(ev)
        if t == "stream_event":
            return self._stream(ev.get("event") or {})
        if t == "assistant":
            return self._assistant(ev)
        if t == "rate_limit_event":
            return [RateLimit(ev.get("rate_limit_info") or {})]
        if t == "result":
            return self._result(ev)
        return [Unknown(ev)]

    def _system(self, ev: dict) -> list[Signal]:
        sub = ev.get("subtype")
        if sub == "init":
            self.session_id = ev.get("session_id")
            return [
                Init(
                    session_id=ev.get("session_id"),
                    model=ev.get("model"),
                    cwd=ev.get("cwd"),
                    tools=ev.get("tools") or [],
                    permission_mode=ev.get("permissionMode"),
                )
            ]
        if sub == "status":
            return [Status(ev.get("status", ""))]
        return [Unknown(ev)]

    def _stream(self, e: dict) -> list[Signal]:
        et = e.get("type")
        if et == "message_start":
            self.text = ""
            return []
        if et == "content_block_start":
            block = e.get("content_block") or {}
            if block.get("type") == "tool_use":
                return [ToolUse(name=block.get("name", "?"), id=block.get("id"))]
            return []
        if et == "content_block_delta":
            d = e.get("delta") or {}
            dt = d.get("type")
            if dt == "text_delta":
                chunk = d.get("text", "")
                self.text += chunk
                return [TextDelta(chunk)]
            if dt == "thinking_delta":
                return [ThinkingDelta(d.get("thinking", ""))]
            return []
        # content_block_stop / message_delta / message_stop: nada que emitir
        return []

    def _assistant(self, ev: dict) -> list[Signal]:
        msg = ev.get("message") or {}
        parts = [
            block.get("text", "")
            for block in (msg.get("content") or [])
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        full = "".join(parts)
        # Solo fallback: si ya llegaron deltas (self.text), no dupliques.
        return [AssistantMessage(full)] if full and not self.text else []

    def _result(self, ev: dict) -> list[Signal]:
        sig = Result(
            subtype=ev.get("subtype", ""),
            text=ev.get("result"),
            duration_ms=ev.get("duration_ms"),
            cost_usd=ev.get("total_cost_usd"),
            num_turns=ev.get("num_turns"),
            session_id=ev.get("session_id"),
            is_error=bool(ev.get("is_error")),
        )
        self.text = ""  # listo para el siguiente turno
        return [sig]
