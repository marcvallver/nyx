"""Daemon de Nyx: Gtk.Application (instancia única) que posee el socket de control
y las superficies de UI. Orbe (único indicador, late en terminal+chat), bocadillo,
barra de entrada, y la confirmación de acciones (Fase 4: híbrido con confirmación)."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import policy, streamparse  # noqa: E402
from .activity import ActivityWatcher  # noqa: E402
from .avatar import Orb  # noqa: E402
from .backend import ClaudeBackend  # noqa: E402
from .bubble import Bubble  # noqa: E402
from .client import socket_path  # noqa: E402
from .confirm import ConfirmPopup  # noqa: E402
from .inputbar import InputBar  # noqa: E402
from .ipc import SocketServer  # noqa: E402

ACTIVITY_FILE = os.path.expanduser("~/.cache/claude-thinking.active")


class NyxApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.marc.nyx")

    def do_activate(self):
        self.hold()
        self._terminal_active = False
        self._nyx_state = "idle"
        self.orb = Orb(self)
        self.bubble = Bubble(self)
        self.inputbar = InputBar(self, self.send_turn)
        self.confirm_popup = ConfirmPopup(self)
        self.backend = ClaudeBackend(self._on_signal)
        self.server = SocketServer(socket_path(), self.handle)
        self.activity = ActivityWatcher(ACTIVITY_FILE, self._on_terminal_activity)

    # --- socket (handler diferido: debe llamar a reply) ---
    def handle(self, msg: dict, reply) -> None:
        op = msg.get("op")
        if op == "ping":
            reply({"ok": True, "pong": True})
        elif op == "status":
            reply({"ok": True, "running": True, "busy": self.backend.busy,
                   "session": self.backend.session_id})
        elif op == "say":
            text = (msg.get("text") or "").strip()
            ttl = int(msg.get("ttl_ms") or 12000)
            if text:
                GLib.idle_add(self.bubble.show_text, text, ttl)
            reply({"ok": True})
        elif op == "summon":
            GLib.idle_add(self.inputbar.show)
            reply({"ok": True})
        elif op == "hide":
            GLib.idle_add(self.inputbar.hide)
            reply({"ok": True})
        elif op == "ask":
            text = (msg.get("text") or "").strip()
            if text:
                GLib.idle_add(self.send_turn, text)
            reply({"ok": True, "busy": self.backend.busy})
        elif op == "confirm":
            GLib.idle_add(self._confirm, msg, reply)  # diferido: reply tras decidir
        elif op == "quit":
            GLib.idle_add(self.quit)
            reply({"ok": True, "quitting": True})
        else:
            reply({"ok": False, "error": f"unknown op: {op!r}"})

    def _confirm(self, msg: dict, reply) -> bool:
        tool = msg.get("tool", "")
        command = msg.get("command", "")
        reason = msg.get("reason", "")
        tool_input = msg.get("tool_input") or {}

        def on_decision(decision: str):
            if decision == "always":
                try:
                    policy.learn(tool, tool_input)
                except Exception:
                    pass
                reply({"decision": "allow", "learned": True})
            else:
                reply({"decision": decision})

        self.confirm_popup.show(tool, command, reason, on_decision)
        return False

    # --- estado del orbe (terminal + chat) ---
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
            self._set_nyx("talking")
            self.bubble.append(sig.text)
        elif isinstance(sig, streamparse.AssistantMessage):
            self._set_nyx("talking")
            if not self.bubble._buf.strip():  # fallback si no llegaron deltas
                self.bubble.append(sig.text)
        elif isinstance(sig, streamparse.Result):
            if sig.is_error and not self.bubble._buf.strip():
                self.bubble.append(sig.text or "(error)")
            self.bubble.finalize()
            self._set_nyx("idle")


def main() -> None:
    NyxApp().run(None)
