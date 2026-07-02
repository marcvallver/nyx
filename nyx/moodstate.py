"""Decisión del estado visual del orbe — PURA (sin gi) para testearla en CI.

`app._refresh_orb` delega aquí la prioridad de estados; el flash de mood
(say/notify/deny) se gestiona fuera (timer GLib) y simplemente no llama a esto
mientras está activo.
"""

from __future__ import annotations


def resolve_orb_state(
    nyx_state: str,
    current_mood: str,
    terminal_active: bool,
    listening: bool,
    persistent_mood: str,
    dnd: bool = False,
) -> str:
    """Prioridad: mood del turno hablando > talking > thinking/terminal >
    listening > mood persistente en reposo > idle.

    Con DND la actividad AMBIENTAL (terminal) no despierta el orbe — se queda
    en reposo (luna ☾); la interacción directa (hablarle, su propio turno)
    sí se muestra: no molestar no es no responder."""
    if nyx_state == "talking" and current_mood != "normal":
        return current_mood
    if nyx_state == "talking":
        return "talking"
    if nyx_state == "thinking" or (terminal_active and not dnd):
        return "thinking"
    if listening:
        return "listening"
    if persistent_mood != "normal":
        return persistent_mood
    return "idle"
