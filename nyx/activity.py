"""Vigila el fichero de actividad de Claude Code (~/.cache/claude-thinking.active)
para que el orbe de Nyx reaccione también a las sesiones de terminal de Marc.

Event-driven (Gio.FileMonitor): cero polling en reposo. Unifica el viejo sparkle de
`claude-thinking` con el orbe — los hooks UserPromptSubmit (touch) / Stop (rm) siguen
escribiendo el fichero; ahora lo lee el orbe en vez del daemon de claude-thinking.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable

from gi.repository import Gio

STALE_SEC = 1800  # red de seguridad si una sesión crasheó sin borrar el fichero


class ActivityWatcher:
    def __init__(self, path: str, on_change: Callable[[bool], None]):
        self.path = path
        self.on_change = on_change
        self.active = self._check()
        gfile = Gio.File.new_for_path(path)
        self.monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect("changed", self._on_event)
        if self.active:
            on_change(True)

    def _check(self) -> bool:
        try:
            return (time.time() - os.stat(self.path).st_mtime) < STALE_SEC
        except OSError:
            return False

    def _on_event(self, _monitor, _file, _other, _event):
        now = self._check()
        if now != self.active:
            self.active = now
            self.on_change(now)
