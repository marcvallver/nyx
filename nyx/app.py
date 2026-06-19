"""Daemon de Nyx: Gtk.Application (instancia única) que posee el socket de control
y las superficies de UI. Fase 2: orbe avatar (estados) + bocadillo + chat con Claude
(streaming) por socket. La confirmación de acciones llega en la Fase 4."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import streamparse  # noqa: E402
from .avatar import Orb  # noqa: E402
from .backend import ClaudeBackend  # noqa: E402
from .bubble import Bubble  # noqa: E402
from .client import socket_path  # noqa: E402
from .inputbar import InputBar  # noqa: E402
from .ipc import SocketServer  # noqa: E402


class NyxApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.marc.nyx")

    def do_activate(self):
        self.hold()  # seguir vivo sin ventanas visibles
        self.orb = Orb(self)
        self.bubble = Bubble(self)
        self.inputbar = InputBar(self, self.send_turn)
        self.backend = ClaudeBackend(self._on_signal)
        self.server = SocketServer(socket_path(), self.handle)

    # --- socket ---
    def handle(self, msg: dict) -> dict:
        op = msg.get("op")
        if op == "ping":
            return {"ok": True, "pong": True}
        if op == "status":
            return {"ok": True, "running": True, "busy": self.backend.busy,
                    "session": self.backend.session_id}
        if op == "say":
            text = (msg.get("text") or "").strip()
            ttl = int(msg.get("ttl_ms") or 12000)
            if text:
                GLib.idle_add(self.bubble.show_text, text, ttl)
            return {"ok": True}
        if op == "summon":
            GLib.idle_add(self.inputbar.show)
            return {"ok": True}
        if op == "hide":
            GLib.idle_add(self.inputbar.hide)
            return {"ok": True}
        if op == "ask":
            text = (msg.get("text") or "").strip()
            if text:
                GLib.idle_add(self.send_turn, text)
            return {"ok": True, "busy": self.backend.busy}
        if op == "quit":
            GLib.idle_add(self.quit)
            return {"ok": True, "quitting": True}
        return {"ok": False, "error": f"unknown op: {op!r}"}

    # --- chat ---
    def send_turn(self, text: str) -> bool:
        if self.backend.busy:
            self.bubble.show_text("Espera, aún estoy con lo anterior…", 4000)
            return False
        self.orb.set_state("thinking")     # orbe latiendo al instante
        self.bubble.start_stream()
        self.backend.ask(text)
        return False

    def _on_signal(self, sig) -> None:
        if isinstance(sig, streamparse.TextDelta):
            self.orb.set_state("talking")  # idempotente; pasa a "hablando" al primer token
            self.bubble.append(sig.text)
        elif isinstance(sig, streamparse.Result):
            if sig.is_error and not self.bubble._buf.strip():
                self.bubble.append(sig.text or "(error)")
            self.bubble.finalize()
            self.orb.set_state("idle")     # se desvanece y para (cero consumo)


def main() -> None:
    NyxApp().run(None)
