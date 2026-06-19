"""Daemon de Nyx: Gtk.Application (instancia única) que posee el socket de control
y las superficies de UI. v0 (Fase 0/B): bocadillo + IPC. El avatar persistente,
la barra de entrada y la confirmación llegan en fases siguientes."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .bubble import Bubble  # noqa: E402
from .client import socket_path  # noqa: E402
from .ipc import SocketServer  # noqa: E402


class NyxApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.marc.nyx")

    def do_activate(self):
        self.hold()  # seguir vivo sin ventanas visibles
        self.bubble = Bubble(self)
        self.server = SocketServer(socket_path(), self.handle)

    def handle(self, msg: dict) -> dict:
        op = msg.get("op")
        if op == "ping":
            return {"ok": True, "pong": True}
        if op == "status":
            return {"ok": True, "running": True, "version": "0"}
        if op == "say":
            text = (msg.get("text") or "").strip()
            ttl = int(msg.get("ttl_ms") or 12000)
            if text:
                GLib.idle_add(self._say, text, ttl)
            return {"ok": True}
        if op == "quit":
            GLib.idle_add(self.quit)
            return {"ok": True, "quitting": True}
        return {"ok": False, "error": f"unknown op: {op!r}"}

    def _say(self, text: str, ttl: int) -> bool:
        self.bubble.show_text(text, ttl)
        return False


def main() -> None:
    NyxApp().run(None)
