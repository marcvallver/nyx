"""Daemon de Nyx: Gtk.Application (instancia única) que posee el socket de control
y las superficies de UI. El orbe es el ÚNICO indicador: late tanto en los turnos de
Nyx (chat) como en las sesiones de terminal de Marc (fichero claude-thinking.active),
unificando el viejo sparkle. La confirmación de acciones llega en la Fase 4."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import streamparse  # noqa: E402
from .activity import ActivityWatcher  # noqa: E402
from .avatar import Orb  # noqa: E402
from .backend import ClaudeBackend  # noqa: E402
from .bubble import Bubble  # noqa: E402
from .client import socket_path  # noqa: E402
from .inputbar import InputBar  # noqa: E402
from .ipc import SocketServer  # noqa: E402

ACTIVITY_FILE = os.path.expanduser("~/.cache/claude-thinking.active")


class NyxApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.marc.nyx")

    def do_activate(self):
        self.hold()  # seguir vivo sin ventanas visibles
        self._terminal_active = False
        self._nyx_state = "idle"  # idle | thinking | talking (turnos propios de Nyx)
        self.orb = Orb(self)
        self.bubble = Bubble(self)
        self.inputbar = InputBar(self, self.send_turn)
        self.backend = ClaudeBackend(self._on_signal)
        self.server = SocketServer(socket_path(), self.handle)
        # el orbe también reacciona a las sesiones de terminal (unifica el sparkle)
        self.activity = ActivityWatcher(ACTIVITY_FILE, self._on_terminal_activity)

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

    # --- estado del orbe (combina terminal + chat) ---
    def _on_terminal_activity(self, active: bool) -> None:
        self._terminal_active = active
        self._refresh_orb()

    def _set_nyx(self, state: str) -> None:
        self._nyx_state = state
        self._refresh_orb()

    def _refresh_orb(self) -> None:
        if self._nyx_state == "talking":
            self.orb.set_state("talking")
        elif self._nyx_state == "thinking" or self._terminal_active:
            self.orb.set_state("thinking")
        else:
            self.orb.set_state("idle")

    # --- chat ---
    def send_turn(self, text: str) -> bool:
        if self.backend.busy:
            self.bubble.show_text("Espera, aún estoy con lo anterior…", 4000)
            return False
        self._set_nyx("thinking")
        self.bubble.start_stream()
        self.backend.ask(text)
        return False

    def _on_signal(self, sig) -> None:
        if isinstance(sig, streamparse.TextDelta):
            self._set_nyx("talking")  # idempotente; "hablando" al primer token
            self.bubble.append(sig.text)
        elif isinstance(sig, streamparse.Result):
            if sig.is_error and not self.bubble._buf.strip():
                self.bubble.append(sig.text or "(error)")
            self.bubble.finalize()
            self._set_nyx("idle")


def main() -> None:
    NyxApp().run(None)
