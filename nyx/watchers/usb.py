"""W3 · Seagate off-site: al enchufar el USB de backup, Nyx propone lanzar el
flujo `bin/nyx-offsite` en una kitty (montar → sudo restic-offsite → marcar
→ ofrecer power-off). El daemon NUNCA ejecuta sudo: la contraseña en esa
terminal es la segunda confirmación de Marc.

Señal: bus de SISTEMA, InterfacesAdded de UDisks2 (evento real de hotplug,
cero polling). Además, un chequeo diario recuerda si el último off-site tiene
más de `remind_days` días.
"""

from __future__ import annotations

import os
import time

from .base import Action, Nudge

LAST_OFFSITE = os.path.expanduser("~/.cache/nyx/last-offsite")
UDISKS = "org.freedesktop.UDisks2"
DAY_S = 86400


def match_usb(model: str, label: str, pattern: str) -> bool:
    """¿El disco recién enchufado es el de backup? Substring case-insensitive
    sobre el modelo del drive o la etiqueta del filesystem. Pura."""
    pat = (pattern or "").strip().lower()
    if not pat:
        return False
    return pat in (model or "").lower() or pat in (label or "").lower()


def offsite_age_days(last_ts: float | None, now: float) -> float | None:
    """Días desde el último off-site (None si nunca). Pura."""
    if last_ts is None:
        return None
    return max(0.0, (now - last_ts) / DAY_S)


class UsbWatcher:
    def __init__(self, params: dict, emit):
        self._emit = emit
        self._pattern = params.get("match") or "One Touch"
        self._remind_days = float(params.get("remind_days", 14))
        self._sub_id: int | None = None
        self._bus = None
        self._daily_timer: int | None = None

    def start(self) -> None:
        from gi.repository import Gio, GLib

        self._bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self._sub_id = self._bus.signal_subscribe(
            UDISKS, "org.freedesktop.DBus.ObjectManager", "InterfacesAdded",
            "/org/freedesktop/UDisks2", None, Gio.DBusSignalFlags.NONE,
            self._on_interfaces_added,
        )
        self._daily_timer = GLib.timeout_add_seconds(DAY_S, self._daily)
        self._remind_check()  # también al arrancar

    def stop(self) -> None:
        from gi.repository import GLib

        if self._bus is not None and self._sub_id is not None:
            self._bus.signal_unsubscribe(self._sub_id)
            self._sub_id = None
        if self._daily_timer is not None:
            GLib.source_remove(self._daily_timer)
            self._daily_timer = None

    def status(self) -> dict:
        age = offsite_age_days(self._last_ts(), time.time())
        return {"last_offsite_days": None if age is None else round(age, 1)}

    # --- hotplug ---
    def _on_interfaces_added(self, _bus, _sender, _path, _iface, _signal, params):
        try:
            obj_path, ifaces = params.unpack()
        except Exception:
            return
        block = ifaces.get("org.freedesktop.UDisks2.Block")
        if not block or "org.freedesktop.UDisks2.Filesystem" not in ifaces:
            return  # solo filesystems montables
        label = str(block.get("IdLabel") or "")
        device = bytes(block.get("Device") or b"").rstrip(b"\x00").decode(
            "utf-8", "replace")
        drive_path = str(block.get("Drive") or "/")
        self._get_drive_model(drive_path, label, device)

    def _get_drive_model(self, drive_path: str, label: str, device: str) -> None:
        if self._bus is None or drive_path in ("", "/"):
            self._maybe_propose("", label, device)
            return
        from gi.repository import GLib

        def _done(bus, res):
            model = ""
            try:
                variant = bus.call_finish(res)
                model = str(variant.unpack()[0])
            except Exception:
                pass
            self._maybe_propose(model, label, device)

        self._bus.call(
            UDISKS, drive_path, "org.freedesktop.DBus.Properties", "Get",
            GLib.Variant("(ss)", ("org.freedesktop.UDisks2.Drive", "Model")),
            None, 0, -1, None, _done,
        )

    def _maybe_propose(self, model: str, label: str, device: str) -> None:
        if not match_usb(model, label, self._pattern) or not device:
            return
        age = offsite_age_days(self._last_ts(), time.time())
        tail = f" Último: hace {age:.0f} días." if age is not None else ""
        self._emit(Nudge(
            key=f"offsite:plug:{device}",
            text=f"Seagate detectado en `{device}`.{tail} ¿Off-site?",
            mood="glad",
            action=Action(label="backup off-site", kind="terminal",
                          command=f"{self._offsite_bin()} {device}"),
            cooldown_s=6 * 3600,
        ))

    # --- recordatorio diario ---
    def _daily(self) -> bool:
        self._remind_check()
        return True  # timer recurrente

    def _remind_check(self) -> None:
        age = offsite_age_days(self._last_ts(), time.time())
        if age is not None and age >= self._remind_days:
            week = time.strftime("%G-W%V")
            self._emit(Nudge(
                key=f"offsite:remind:{week}",
                text=f"{age:.0f} días sin off-site. Enchufa el Seagate.",
                mood="dim",
            ))

    @staticmethod
    def _last_ts() -> float | None:
        try:
            return os.path.getmtime(LAST_OFFSITE)
        except OSError:
            return None

    @staticmethod
    def _offsite_bin() -> str:
        return os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.realpath(__file__)))), "bin", "nyx-offsite")
