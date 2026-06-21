"""Daemon de Nyx: Gtk.Application (instancia única) que posee el socket de control
y las superficies de UI. Orbe (único indicador, late en terminal+chat), bocadillo,
barra de entrada, y la confirmación de acciones (Fase 4: híbrido con confirmación)."""

from __future__ import annotations

import json
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
from .history import HistoryPanel  # noqa: E402
from .inputbar import InputBar  # noqa: E402
from .ipc import SocketServer  # noqa: E402
from .voice import SttListener, TtsSpeaker  # noqa: E402

ACTIVITY_FILE = os.path.expanduser("~/.cache/claude-thinking.active")
CONFIG_FILE = os.path.expanduser("~/.config/nyx/config.json")
_MOODS = ("normal", "alert", "heated")


def _load_config() -> dict:
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


class NyxApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.marc.nyx")

    def do_activate(self):
        self.hold()
        self._config = _load_config()
        self._terminal_active = False
        self._nyx_state = "idle"
        self._current_mood = "normal"
        self._flash_id: int | None = None  # timer del flash de mood en `say`/notify/deny
        self._turn_text = ""  # texto de Nyx del turno en curso (para el historial)
        self._listening = False
        self.orb = Orb(self)
        self.bubble = Bubble(self)
        self.history = HistoryPanel(self)
        self.inputbar = InputBar(self, self.send_turn, self._dismiss_input)
        self.confirm_popup = ConfirmPopup(self)
        self.tts = TtsSpeaker()
        self.stt = SttListener(self._on_stt_text)
        self.backend = ClaudeBackend(self._on_signal)
        self.server = SocketServer(socket_path(), self.handle)
        self.activity = ActivityWatcher(ACTIVITY_FILE, self._on_terminal_activity)
        self.notifyd = None
        if self._config.get("dbus_notifications"):  # opt-in: reemplaza al daemon de KDE
            self._start_notifyd()

    def _start_notifyd(self) -> None:
        """Arranca el daemon D-Bus org.freedesktop.Notifications (opt-in por config)."""
        try:
            from .notifyd import NotificationServer

            takeover = bool(self._config.get("dbus_notifications_takeover"))
            self.notifyd = NotificationServer(self._on_dbus_notify, takeover=takeover)
            self.notifyd.start()
        except Exception:
            self.notifyd = None  # nunca tumbar el daemon por un fallo de D-Bus

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
            mood = msg.get("mood") if msg.get("mood") in _MOODS else "normal"
            if text:
                GLib.idle_add(self.bubble.show_text, text, ttl, mood)
                if mood != "normal":
                    GLib.idle_add(self._flash_mood, mood, ttl)
                self.tts.feed(text)  # cola thread-safe; habla si está activado
                self.tts.flush()
            reply({"ok": True})
        elif op == "history":
            GLib.idle_add(self.history.toggle)
            reply({"ok": True})
        elif op == "notify":
            GLib.idle_add(
                self._show_notification,
                (msg.get("app") or "").strip(),
                (msg.get("summary") or "").strip(),
                (msg.get("body") or "").strip(),
                int(msg.get("urgency") or 1),
            )
            reply({"ok": True})
        elif op == "tts":
            if "on" in msg:  # set explícito (nyx-ctl tts on|off)
                self.tts.set_enabled(bool(msg.get("on")), persist=True)
            else:  # sin "on" → alterna (atajo Meta+M / nyx-ctl tts)
                self.tts.toggle()
            on = self.tts.enabled
            GLib.idle_add(self.bubble.show_text,
                          "🔊 Voz activada" if on else "🔇 Voz en silencio", 2500)
            if on:  # confirmación audible: Marc oye que el audio sale (y por qué salida)
                self.tts.feed("Voz activada.")
                self.tts.flush()
            reply({"ok": True, "tts": on})
        elif op == "listen":
            GLib.idle_add(self._listen_toggle)
            reply({"ok": True})
        elif op == "listen_stop":
            GLib.idle_add(self._listen_stop)
            reply({"ok": True})
        elif op == "summon":
            GLib.idle_add(self._summon)
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
            GLib.idle_add(self._quit_clean)
            reply({"ok": True, "quitting": True})
        else:
            reply({"ok": False, "error": f"unknown op: {op!r}"})

    def _quit_clean(self) -> bool:
        """Cierre ordenado: termina el worker STT y corta la voz antes de salir."""
        try:
            self.stt.close()
        except Exception:
            pass
        try:
            self.tts.stop()
        except Exception:
            pass
        self.quit()
        return False

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
        if self._nyx_state == "talking" and self._current_mood in ("alert", "heated"):
            self.orb.set_state(self._current_mood)
        elif self._nyx_state == "talking":
            self.orb.set_state("talking")
        elif self._nyx_state == "thinking" or self._terminal_active:
            self.orb.set_state("thinking")
        elif self._listening:
            self.orb.set_state("listening")
        else:
            self.orb.set_state("idle")

    def _flash_mood(self, mood: str, hold_ms: int) -> bool:
        """Tiñe el orbe (alert/heated) un rato, sin depender del estado de turno.

        Lo usan `say`/`notify`/deny: no hay un turno de chat que cierre el color, así
        que se restaura solo tras `hold_ms` volviendo a lo que toque (idle/thinking…).
        """
        if self._flash_id is not None:
            GLib.source_remove(self._flash_id)
        self.orb.set_state(mood)
        self.inputbar.set_mood(mood)  # la barra rápida también se tiñe
        self._flash_id = GLib.timeout_add(max(1500, hold_ms), self._end_flash)
        return False

    def _end_flash(self) -> bool:
        self._flash_id = None
        self.inputbar.set_mood("normal")
        self._refresh_orb()
        return False

    def _show_notification(self, app: str, summary: str, body: str, urgency: int) -> bool:
        """Pinta una notificación como bocadillo estilizado (sustituto del nativo de KDE)."""
        head = f"**{app}** · {summary}" if app and summary else (summary or app or "Notificación")
        text = f"{head}\n{body}" if body else head
        mood = "alert" if urgency >= 2 else "normal"  # crítica → rojo
        ttl = 9000 if urgency >= 2 else 6000
        self.bubble.show_text(text, ttl, mood)
        if mood != "normal":
            self._flash_mood(mood, ttl)
        return False

    def _on_dbus_notify(self, n: dict) -> None:
        """Callback del daemon D-Bus (corre en el bucle GLib); marshalea a la UI."""
        GLib.idle_add(
            self._show_notification,
            n.get("app", ""), n.get("summary", ""), n.get("body", ""), int(n.get("urgency", 1)),
        )

    def _summon(self) -> bool:
        self._listening = True
        self._refresh_orb()
        self.inputbar.show()
        return False

    def _dismiss_input(self) -> None:
        self._listening = False
        self._refresh_orb()

    # --- voz (push-to-talk) ---
    def _listen_toggle(self) -> bool:
        if not self.stt.available():
            self.bubble.show_text("Voz no disponible (falta el venv-voice / faster-whisper).", 4000)
            return False
        if self.stt.recording:
            self.stt.stop()  # transcribe; el texto llega async a _on_stt_text
        elif not self.stt.ready:  # worker arrancado pero el modelo aún carga → no fingir escucha
            self.bubble.show_text("Cargando el modelo de voz… prueba en unos segundos.", 3000)
        else:
            self.stt.start()
            self._listening = True
            self._refresh_orb()  # orbe en 'listening'
        return False

    def _listen_stop(self) -> bool:
        if self.stt.recording:
            self.stt.stop()
        return False

    def _on_stt_text(self, text: str) -> None:
        GLib.idle_add(self._handle_stt, text)  # llega desde un hilo → marshalear

    def _handle_stt(self, text: str) -> bool:
        self._listening = False
        if text.strip():
            self.send_turn(text)  # mismo flujo que la barra/ask → orbe 'thinking'
        else:
            self.bubble.show_text("No te he oído (revisa el micro / stt_source).", 3000)
            self._refresh_orb()  # nada captado → vuelve a idle, pero avisando
        return False

    # --- chat ---
    def send_turn(self, text: str) -> bool:
        if self.backend.busy:
            self.bubble.show_text("Espera, aún estoy con lo anterior…", 4000)
            return False
        self._listening = False
        self._current_mood = "normal"
        self.inputbar.set_mood("normal")
        self._turn_text = ""
        self.history.add_turn("operativo", text)
        self.tts.stop()  # corta cualquier voz anterior antes del nuevo turno
        self._set_nyx("thinking")
        self.bubble.start_stream()
        self.backend.ask(text)
        return False

    def _on_signal(self, sig) -> None:
        if isinstance(sig, streamparse.MoodSignal):
            self._current_mood = sig.mood
            self.bubble.set_mood(sig.mood)
            self.inputbar.set_mood(sig.mood)
            self._refresh_orb()
        elif isinstance(sig, streamparse.TextDelta):
            self._set_nyx("talking")
            self._turn_text += sig.text
            self.bubble.append(sig.text)
            self.tts.feed(sig.text)  # habla frase a frase (si TTS activado)
        elif isinstance(sig, streamparse.AssistantMessage):
            self._set_nyx("talking")
            if not self.bubble._buf.strip():  # fallback si no llegaron deltas
                self._turn_text += sig.text
                self.bubble.append(sig.text)
                self.tts.feed(sig.text)
        elif isinstance(sig, streamparse.Result):
            if sig.is_error and not self.bubble._buf.strip():
                self.bubble.append(sig.text or "(error)")
            self.bubble.finalize()
            self.tts.flush()  # habla lo que quede del turno
            if self._turn_text.strip():
                self.history.add_turn("Nyx", self._turn_text, self._current_mood)
            self._turn_text = ""
            self.inputbar.set_mood("normal")
            self._set_nyx("idle")


def main() -> None:
    NyxApp().run(None)
