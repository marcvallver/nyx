"""WatcherManager: ciclo de vida de los watchers proactivos (todos OPT-IN:
un watcher ausente o sin `enabled: true` en config no arranca).

Cada watcher es un módulo con una clase `__init__(params, emit)`, `start()`,
`stop()` y `status() -> dict`. Nada de ABC ni plugin-discovery: registro dict
con import perezoso, y try/except alrededor de todo (norma de la casa: ningún
watcher tumba el daemon).
"""

from __future__ import annotations

import importlib
import json
import os
import time

from .base import Nudge, NudgeGate

NUDGE_STATE = os.path.expanduser("~/.cache/nyx/nudges.json")

# nombre en config -> (módulo, clase)
_REGISTRY: dict[str, tuple[str, str]] = {
    "sessions": ("nyx.watchers.sessions", "SessionsWatcher"),
    "repos": ("nyx.watchers.repos", "ReposWatcher"),
    "usb_backup": ("nyx.watchers.usb", "UsbWatcher"),
    "system": ("nyx.watchers.system", "SystemWatcher"),
    "eod": ("nyx.watchers.eod", "EodWatcher"),
}


def _load_state() -> dict[str, float]:
    try:
        with open(NUDGE_STATE, encoding="utf-8") as f:
            raw = json.load(f)
        return {str(k): float(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state: dict[str, float]) -> None:
    try:
        os.makedirs(os.path.dirname(NUDGE_STATE), exist_ok=True)
        tmp = NUDGE_STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, NUDGE_STATE)
    except OSError:
        pass


class WatcherManager:
    def __init__(self, cfg: dict | None, emit):
        """`cfg` = sección `watchers` del config; `emit(nudge)` la pone la app."""
        self._cfg = cfg or {}
        self._emit_cb = emit
        quiet = self._cfg.get("quiet_hours") or ["", ""]
        gate_state = _load_state()
        self._gate = NudgeGate(quiet=(str(quiet[0]), str(quiet[1])), state=gate_state)
        self._gate.prune(time.time())
        self._watchers: dict[str, object] = {}
        self._errors: dict[str, str] = {}

    def start(self) -> None:
        for name in _REGISTRY:
            params = self._cfg.get(name)
            if isinstance(params, dict) and params.get("enabled"):
                self._start_one(name, params)

    def _start_one(self, name: str, params: dict) -> None:
        mod_name, cls_name = _REGISTRY[name]
        try:
            module = importlib.import_module(mod_name)
            watcher = getattr(module, cls_name)(dict(params), self.emit)
            watcher.start()
            self._watchers[name] = watcher
            self._errors.pop(name, None)
        except Exception as e:  # un watcher roto queda visible en status, no tumba nada
            self._errors[name] = f"{type(e).__name__}: {e}"

    def stop(self) -> None:
        for watcher in self._watchers.values():
            try:
                watcher.stop()
            except Exception:
                pass
        self._watchers = {}

    def emit(self, nudge: Nudge) -> bool:
        """Puerta única de salida: gate anti-spam → persistir estado → app."""
        now = time.time()
        if not self._gate.check(nudge.key, nudge.mood, now,
                                time.strftime("%H:%M"), nudge.cooldown_s):
            return False
        _save_state(self._gate.state())
        try:
            self._emit_cb(nudge)
        except Exception:
            pass
        return True

    def status(self) -> dict:
        out: dict[str, dict] = {}
        for name in _REGISTRY:
            params = self._cfg.get(name)
            enabled = bool(isinstance(params, dict) and params.get("enabled"))
            entry: dict = {"enabled": enabled, "running": name in self._watchers}
            if name in self._errors:
                entry["error"] = self._errors[name]
            watcher = self._watchers.get(name)
            if watcher is not None:
                try:
                    entry.update(watcher.status())
                except Exception:
                    pass
            out[name] = entry
        return out
