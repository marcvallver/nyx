"""Núcleo PURO de la capa proactiva (sin gi): Nudge, Action y el NudgeGate
anti-spam. Regla de oro: un nudge se dispara UNA vez por estado nuevo (la clave
es una huella del estado); si Marc lo ignora, Nyx se calla.

El tiempo entra siempre por parámetro → todo testeable en CI.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_COOLDOWN_S = 4 * 3600  # re-emisión de la MISMA clave: como pronto en 4 h
STATE_MAX_AGE_S = 7 * 86400  # claves sin re-disparo en una semana se olvidan

TERMINAL = "terminal"  # abre kitty con el comando preparado (sudo = 2ª confirmación)
SUBPROCESS = "subprocess"  # lo ejecuta el daemon (solo comandos seguros, veto de policy)


@dataclass
class Action:
    """Acción propuesta. NUNCA se ejecuta sin clic en el popup de confirmación."""

    label: str
    kind: str  # TERMINAL | SUBPROCESS
    command: str
    cwd: str = ""


@dataclass
class Nudge:
    """Aviso proactivo de un watcher. `key` = huella del estado que lo causa
    (p.ej. "kernel:6.18.35" o "collision:/home/marc/Projects/fulgor")."""

    key: str
    text: str
    mood: str = "normal"
    action: Action | None = None
    ttl_ms: int = 12000
    cooldown_s: int | None = None  # None → DEFAULT_COOLDOWN_S


def in_quiet_hours(hhmm: str, start: str, end: str) -> bool:
    """¿`hhmm` ("23:45") cae dentro de la franja silenciosa? Soporta cruzar
    medianoche ("23:30"→"08:30"). Sin franja (vacío o start==end) → False."""
    if not start or not end or start == end:
        return False
    if start <= end:
        return start <= hhmm < end
    return hhmm >= start or hhmm < end


class NudgeGate:
    """Decide si un nudge se emite: quiet hours (los alert pasan igual) +
    cooldown por clave. El estado (última emisión por clave) entra y sale como
    dict para que el manager lo persista donde quiera."""

    def __init__(self, quiet: tuple[str, str] = ("", ""),
                 state: dict[str, float] | None = None):
        self.quiet = quiet
        self._last: dict[str, float] = dict(state or {})

    def check(self, key: str, mood: str, now_ts: float, hhmm: str,
              cooldown_s: int | None = None) -> bool:
        """True = emitir (y queda registrado). En quiet hours los `normal` se
        DESCARTAN sin registrar: si el estado importa, re-disparará después."""
        if mood != "alert" and in_quiet_hours(hhmm, *self.quiet):
            return False
        cd = DEFAULT_COOLDOWN_S if cooldown_s is None else cooldown_s
        last = self._last.get(key)
        if last is not None and now_ts - last < cd:
            return False
        self._last[key] = now_ts
        return True

    def state(self) -> dict[str, float]:
        return dict(self._last)

    def prune(self, now_ts: float, max_age_s: float = STATE_MAX_AGE_S) -> None:
        self._last = {k: t for k, t in self._last.items() if now_ts - t < max_age_s}
