"""W1 · Colisión de sesiones Claude: ≥2 sesiones ESCRIBIENDO en el mismo repo a
la vez (el incidente del 21/06: una 2ª instancia + el backend del daemon
auto-editando el repo en paralelo).

Señal: los hooks de Claude Code (bin/nyx-session-mark) dejan un marcador
~/.cache/nyx/sessions/<session_id>.json con {"cwd": ...} en cada Edit/Write;
un Gio.FileMonitor sobre el directorio dispara la detección (cero polling).
Los worktrees (wt/wtj) son roots git distintos → correctamente NO colisionan.
"""

from __future__ import annotations

import json
import os
import time

from .base import Nudge

SESSIONS_DIR = os.path.expanduser("~/.cache/nyx/sessions")
STALE_S = 24 * 3600  # marcadores de más de un día se limpian


def find_root(path: str, isdir=os.path.isdir) -> str:
    """Sube desde `path` hasta el directorio con .git (root del repo). Si no hay
    repo, devuelve el propio path (colisiones por cwd exacto). `isdir` inyectable."""
    cur = os.path.abspath(path or "/")
    while True:
        if isdir(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return os.path.abspath(path or "/")
        cur = parent


def detect_collisions(entries: list[tuple[str, str, float]],
                      window_s: float, now: float) -> list[str]:
    """entries = [(session_id, root, ts)]. Devuelve los roots con ≥2 sesiones
    DISTINTAS activas dentro de la ventana. Pura."""
    by_root: dict[str, set[str]] = {}
    for sid, root, ts in entries:
        if sid and root and now - ts <= window_s:
            by_root.setdefault(root, set()).add(sid)
    return sorted(root for root, sids in by_root.items() if len(sids) >= 2)


class SessionsWatcher:
    def __init__(self, params: dict, emit):
        self._emit = emit
        self._window_s = float(params.get("window_s", 120))
        self._cooldown_s = int(params.get("cooldown_s", 600))
        self._monitor = None

    def start(self) -> None:
        from gi.repository import Gio

        os.makedirs(SESSIONS_DIR, exist_ok=True)
        gfile = Gio.File.new_for_path(SESSIONS_DIR)
        self._monitor = gfile.monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self._monitor.connect("changed", self._on_change)
        self._check()  # estado presente al arrancar

    def stop(self) -> None:
        if self._monitor is not None:
            self._monitor.cancel()
            self._monitor = None

    def status(self) -> dict:
        try:
            marks = len([f for f in os.listdir(SESSIONS_DIR) if f.endswith(".json")])
        except OSError:
            marks = 0
        return {"marks": marks}

    def _on_change(self, *_):
        self._check()

    def _scan(self, now: float) -> list[tuple[str, str, float]]:
        entries: list[tuple[str, str, float]] = []
        try:
            names = os.listdir(SESSIONS_DIR)
        except OSError:
            return entries
        for name in names:
            if not name.endswith(".json"):
                continue
            path = os.path.join(SESSIONS_DIR, name)
            try:
                ts = os.path.getmtime(path)
                if now - ts > STALE_S:
                    os.remove(path)  # limpieza de marcadores muertos
                    continue
                with open(path, encoding="utf-8") as f:
                    cwd = (json.load(f).get("cwd") or "").strip()
                if cwd:
                    entries.append((name[:-5], find_root(cwd), ts))
            except (OSError, ValueError):
                continue
        return entries

    def _check(self) -> None:
        now = time.time()
        for root in detect_collisions(self._scan(now), self._window_s, now):
            self._emit(Nudge(
                key=f"collision:{root}",
                text=(f"Dos manos escribiendo en `{os.path.basename(root)}` "
                      "a la vez, operativo. Para una."),
                mood="alert",
                cooldown_s=self._cooldown_s,
            ))
