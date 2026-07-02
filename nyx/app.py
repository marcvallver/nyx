"""Daemon de Nyx: Gtk.Application (instancia única) que posee el socket de control
y las superficies de UI. Orbe (único indicador, late en terminal+chat), bocadillo,
barra de entrada, y la confirmación de acciones (Fase 4: híbrido con confirmación)."""

from __future__ import annotations

import os
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import chatlog, config, notifqueue, policy, streamparse, theme  # noqa: E402
from .actions import ActionRunner  # noqa: E402
from .activity import ActivityWatcher  # noqa: E402
from .avatar import Orb  # noqa: E402
from .backend import ClaudeBackend  # noqa: E402
from .bubble import Bubble  # noqa: E402
from .client import socket_path  # noqa: E402
from .confirm import ConfirmPopup  # noqa: E402
from .control import ControlPanel  # noqa: E402
from .history import HistoryPanel  # noqa: E402
from .inputbar import InputBar  # noqa: E402
from .ipc import SocketServer  # noqa: E402
from .moodstate import resolve_orb_state  # noqa: E402
from .voice import SttListener, TtsSpeaker  # noqa: E402
from .watchers import WatcherManager  # noqa: E402
from .watchers.base import Nudge  # noqa: E402

ACTIVITY_FILE = os.path.expanduser("~/.cache/claude-thinking.active")
_MOODS = theme.MOODS  # normal, alert, heated, glad, dim

# qué cambios de config se aplican EN VIVO con el op `reload`; el resto de rutas
# conocidas requiere reiniciar el daemon (voz/STT: workers ya arrancados)
_RELOAD_LIVE_PREFIXES = (
    "ui.orb.", "ui.bubble.", "ui.inputbar.",
    "backend.model",
    "notifications.",
    "terminal_echo.",
    "voice.tts_enabled",
    "mood",
    "version",
    "watchers.",
)


class NyxApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.marc.nyx")

    def do_activate(self):
        self.hold()
        self._config = config.load()
        self._terminal_active = False
        self._nyx_state = "idle"
        self._current_mood = "normal"
        # mood persistente: sobrevive reinicios (config "mood") y tiñe el reposo
        m = self._config.get("mood")
        self._persistent_mood = m if m in _MOODS else "normal"
        self._flash_id: int | None = None  # timer del flash de mood en `say`/notify/deny
        self._turn_text = ""  # texto de Nyx del turno en curso (para el historial)
        self._listening = False
        # métricas de turno (para `status` y el futuro panel de control)
        self._cost_last: float | None = None
        self._cost_total = 0.0
        self._turns = 0
        ui = self._config["ui"]
        self.orb = Orb(self, **ui["orb"])
        self.bubble = Bubble(self, **ui["bubble"])
        self.history = HistoryPanel(self, **ui["history"])
        self.inputbar = InputBar(self, self.send_turn, self._dismiss_input,
                                 **ui["inputbar"])
        self.confirm_popup = ConfirmPopup(self)
        self.tts = TtsSpeaker()
        self.stt = SttListener(self._on_stt_text)
        self.backend = ClaudeBackend(self._on_signal,
                                     model=config.get_path(self._config, "backend.model"))
        self.server = SocketServer(socket_path(), self.handle)
        self.activity = ActivityWatcher(ACTIVITY_FILE, self._on_terminal_activity)
        self.notifyd = None
        if config.get_path(self._config, "notifications.enabled"):
            self._start_notifyd()
        # cola de notificaciones: el bocadillo muestra de una en una, sin metralleta
        self._notif_queue = notifqueue.NotifQueue(
            max_per_minute=config.get_path(self._config, "notifications.max_per_minute", 6))
        self._notif_current: dict | None = None
        self.bubble.on_hidden = self._on_bubble_hidden
        if self._persistent_mood != "normal":  # restaurar el tinte de reposo
            self.bubble.base_mood = self._persistent_mood
            self.bubble.set_mood(self._persistent_mood)
            self._refresh_orb()
        # hilo persistente de la sesión core: recuperar los últimos turnos al panel
        chatlog.rotate()
        for rec in chatlog.load_recent():
            self.history.add_turn(rec["role"], rec["text"], rec.get("mood", "normal"))
        # capa proactiva (opt-in por watcher en config)
        self.actions = ActionRunner(self._action_notify)
        self._nudge_backlog: list[Nudge] = []  # nudges retenidos mientras hay turno
        self.watchers = WatcherManager(self._config.get("watchers"), self._on_nudge)
        self.watchers.start()
        self.control = ControlPanel(self)  # el drawer de control (Meta+N sugerido)

    def _start_notifyd(self) -> None:
        """Arranca el daemon D-Bus org.freedesktop.Notifications (opt-in por config)."""
        try:
            from .notifyd import NotificationServer

            takeover = bool(config.get_path(self._config, "notifications.takeover"))
            self.notifyd = NotificationServer(self._on_dbus_notify, takeover=takeover)
            self.notifyd.start()
        except Exception:
            self.notifyd = None  # nunca tumbar el daemon por un fallo de D-Bus

    def _stop_notifyd(self) -> None:
        if self.notifyd is not None:
            try:
                self.notifyd.stop()
            except Exception:
                pass
            self.notifyd = None

    # --- recarga de config en caliente (op `reload`) ---
    def _reload_config(self) -> dict:
        """Relee config.json y aplica lo aplicable en vivo. Devuelve qué rutas
        cambiaron: `applied` (ya en efecto) y `restart_needed` (piden reinicio)."""
        old, new = self._config, config.load()
        self._config = new
        changed = config.diff_paths(old, new)
        applied = [p for p in changed if p.startswith(_RELOAD_LIVE_PREFIXES)]
        restart_needed = [p for p in changed if p not in applied]
        if any(p.startswith("ui.orb.") for p in applied):
            self.orb.set_margins(**new["ui"]["orb"])
        if any(p.startswith("ui.bubble.margin") for p in applied):
            self.bubble.set_margins(margin_top=new["ui"]["bubble"]["margin_top"],
                                    margin_right=new["ui"]["bubble"]["margin_right"])
        if "ui.bubble.ttl_ms" in applied:
            self.bubble.default_ttl = int(new["ui"]["bubble"]["ttl_ms"])
        if any(p.startswith("ui.inputbar.") for p in applied):
            self.inputbar.set_margins(**new["ui"]["inputbar"])
        if "backend.model" in applied:
            self.backend.model = config.get_path(new, "backend.model")
        if "voice.tts_enabled" in applied:
            self.tts.set_enabled(bool(config.get_path(new, "voice.tts_enabled")))
        if "mood" in applied:
            m = new.get("mood")
            self._persistent_mood = m if m in _MOODS else "normal"
            self.bubble.base_mood = self._persistent_mood
            GLib.idle_add(self._apply_persistent_mood)
        if any(p.startswith("notifications.") for p in applied):
            self._stop_notifyd()
            if config.get_path(new, "notifications.enabled"):
                self._start_notifyd()
        if any(p.startswith("watchers") for p in applied):
            self.watchers.stop()
            self.watchers = WatcherManager(new.get("watchers"), self._on_nudge)
            self.watchers.start()
        return {"ok": True, "applied": applied, "restart_needed": restart_needed}

    # --- socket (handler diferido: debe llamar a reply) ---
    def handle(self, msg: dict, reply) -> None:
        op = msg.get("op")
        if op == "ping":
            reply({"ok": True, "pong": True})
        elif op == "status":
            reply({
                "ok": True, "running": True, "busy": self.backend.busy,
                "session": self.backend.session_id,
                "model": self.backend.model,
                "mood": self._persistent_mood,
                "tts": self.tts.enabled,
                "stt_available": self.stt.available(),
                "notifyd": self.notifyd is not None,
                "cost_last_usd": self._cost_last,
                "cost_total_usd": round(self._cost_total, 4),
                "turns": self._turns,
            })
        elif op == "say":
            text = (msg.get("text") or "").strip()
            ttl = int(msg.get("ttl_ms") or self.bubble.default_ttl)
            mood = msg.get("mood") if msg.get("mood") in _MOODS else "normal"
            if text:
                GLib.idle_add(self._ephemeral, text, ttl, mood, True)
            reply({"ok": True})
        elif op == "reload":
            reply(self._reload_config())
        elif op == "watchers":
            reply({"ok": True, "watchers": self.watchers.status()})
        elif op == "panel":
            GLib.idle_add(self.control.toggle)
            reply({"ok": True})
        elif op == "session_new":
            self.backend.reset_session()
            archived = chatlog.archive()
            self._cost_last, self._cost_total, self._turns = None, 0.0, 0
            GLib.idle_add(self.history.clear)
            reply({"ok": True, "archived": archived})
        elif op == "session_done":
            # eco COMPACTO de una sesión de terminal (hook Stop): solo "sesión + repo",
            # sin texto y NUNCA por voz — la voz de Nyx es exclusiva de su sesión core.
            sid = (msg.get("session_id") or "").strip()
            repo = (msg.get("repo") or "terminal").strip()
            own = sid and sid == (self.backend.session_id or "")
            if config.get_path(self._config, "terminal_echo.enabled", True) and not own:
                GLib.idle_add(self._ephemeral,
                              f"⌁ sesión `{repo}` · turno terminado", 5000, "normal", False)
            reply({"ok": True})
        elif op == "history":
            GLib.idle_add(self.history.toggle)
            reply({"ok": True})
        elif op == "notify":
            urg = msg.get("urgency")
            n = {
                "id": 0,
                "app": (msg.get("app") or "").strip(),
                "summary": (msg.get("summary") or "").strip(),
                "body": (msg.get("body") or "").strip(),
                "urgency": 1 if urg is None else int(urg),
                "icon": (msg.get("icon") or "").strip(),
                "actions": msg.get("actions") or [],  # [key, label, …] como la spec
            }
            GLib.idle_add(self._notif_push, n)  # mismo pipeline que las D-Bus
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
        elif op == "mood":
            m = msg.get("mood") if msg.get("mood") in _MOODS else "normal"
            self.set_persistent_mood(m)
            reply({"ok": True, "mood": m})
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
            self.watchers.stop()
        except Exception:
            pass
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
        if self._flash_id is not None:
            return  # un flash de mood (say/notify/deny) manda el orbe hasta que expire su timer
        self.orb.set_state(resolve_orb_state(
            self._nyx_state, self._current_mood, self._terminal_active,
            self._listening, self._persistent_mood,
        ))

    def set_persistent_mood(self, mood: str) -> None:
        """Fija el mood persistente (op mood / panel de control): config + superficies."""
        m = mood if mood in _MOODS else "normal"
        self._persistent_mood = m
        self._config = config.update({"mood": m})  # sobrevive reinicios
        self.bubble.base_mood = m
        GLib.idle_add(self._apply_persistent_mood)

    def _apply_persistent_mood(self) -> bool:
        """Tiñe TODAS las superficies en reposo con el mood persistente."""
        m = self._persistent_mood
        self._refresh_orb()
        self.inputbar.set_mood(m)
        if not self.backend.busy:  # no pisar el tinte de un turno en streaming
            self.bubble.set_mood(m)
        return False

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
        self.inputbar.set_mood(self._persistent_mood)  # el reposo vuelve al mood persistente
        self._refresh_orb()
        return False

    def _ephemeral(self, text: str, ttl: int, mood: str, speak: bool = False) -> bool:
        """Mensaje efímero (say/notify): si hay un turno en streaming NO pisa el bocadillo
        (solo el flash del orbe), para no corromper la respuesta en curso."""
        if self.backend.busy:
            if mood != "normal":
                self._flash_mood(mood, ttl)
            return False
        # un efímero "normal" hereda el tinte del mood persistente (el mood unifica todo)
        self.bubble.show_text(text, ttl, mood if mood != "normal" else self._persistent_mood)
        if mood != "normal":
            self._flash_mood(mood, ttl)
        if speak:
            self.tts.feed(text)  # cola thread-safe; habla si está activado
            self.tts.flush()
        return False

    # --- pipeline de notificaciones (op notify + D-Bus): clasifica → cola → bocadillo ---
    def _notif_push(self, n: dict) -> bool:
        rules = config.get_path(self._config, "notifications.rules", {}) or {}
        dnd = bool(config.get_path(self._config, "notifications.dnd", False))
        shown = notifqueue.classify(n, rules, dnd) == notifqueue.SHOW
        self.history.add_notification(n, shown)
        notifqueue.log_notification(n, shown=shown, ts=time.time())
        if not shown:
            return False  # silenciada: registrada, sin bocadillo
        if self._notif_current and n.get("id") and n["id"] == self._notif_current.get("id"):
            self._notif_show(n)  # replaces_id del visible: actualizar, no duplicar
            return False
        self._notif_queue.push(n, time.monotonic())
        if self._notif_current is None and not self.backend.busy:
            self._notif_show_next()
        return False

    def _notif_show_next(self) -> bool:
        if self._notif_current is not None or self.backend.busy:
            return False
        n = self._notif_queue.next(time.monotonic())
        if n:
            self._notif_show(n)
        return False

    def _notif_show(self, n: dict) -> None:
        self._notif_current = n
        app, summary, body = n.get("app", ""), n.get("summary", ""), n.get("body", "")
        head = f"**{app}** · {summary}" if app and summary else (summary or app or "Notificación")
        text = f"{head}\n{body}" if body else head
        urgency = int(n.get("urgency", 1))
        mood = "alert" if urgency >= 2 else "normal"  # crítica → rojo
        ttl = 9000 if urgency >= 2 else 6000
        shown_mood = mood if mood != "normal" else self._persistent_mood
        pairs = notifqueue.action_pairs(n.get("actions"))
        nid = int(n.get("id") or 0)
        if pairs or n.get("icon"):
            ttl = max(ttl, 12000) if pairs else ttl  # con botones, dar tiempo a decidir
            self.bubble.show_notification(
                text, ttl, shown_mood, icon=n.get("icon", ""), actions=pairs,
                on_action=lambda key: self._notif_action(nid, key),
            )
        else:
            self.bubble.show_text(text, ttl, shown_mood)
        if mood != "normal":
            self._flash_mood(mood, ttl)

    def _notif_action(self, nid: int, key: str) -> None:
        """Clic en un botón de acción: ActionInvoked por D-Bus y cierre (dismissed)."""
        if self.notifyd and nid:
            self.notifyd.action(nid, key)
        self.bubble.dismiss()  # on_hidden emitirá NotificationClosed y drenará la cola

    def _on_bubble_hidden(self, dismissed: bool) -> None:
        """El bocadillo se ocultó (TTL o ×): cerrar la notificación visible por spec
        y mostrar la siguiente de la cola."""
        n, self._notif_current = self._notif_current, None
        if n and n.get("id") and self.notifyd:
            from .notifyd import CLOSE_REASON_DISMISSED, CLOSE_REASON_EXPIRED
            self.notifyd.close(int(n["id"]),
                               CLOSE_REASON_DISMISSED if dismissed else CLOSE_REASON_EXPIRED)
        GLib.idle_add(self._notif_show_next)

    def _on_dbus_notify(self, n: dict) -> None:
        """Callback del daemon D-Bus (corre en el bucle GLib); marshalea a la UI."""
        GLib.idle_add(self._notif_push, dict(n))

    # --- capa proactiva: nudges de los watchers ---
    def _on_nudge(self, nudge: Nudge) -> None:
        """Salida de un watcher (ya filtrada por el NudgeGate). En el bucle GLib."""
        if nudge.action is not None and (self.backend.busy or self.confirm_popup.win.get_visible()):
            self._nudge_backlog.append(nudge)  # no pisar un turno ni otro popup
            return
        self._present_nudge(nudge)

    def _present_nudge(self, nudge: Nudge) -> None:
        if nudge.action is None:
            GLib.idle_add(self._ephemeral, nudge.text, nudge.ttl_ms, nudge.mood, False)
            return

        def on_decision(decision: str, action=nudge.action):
            if decision == "allow":
                self.actions.run(action)
            GLib.idle_add(self._drain_nudges)  # siguiente propuesta retenida, si la hay

        GLib.idle_add(self.confirm_popup.show_proposal,
                      nudge.text, nudge.action.command,
                      f"acción propuesta · {nudge.action.kind}", on_decision)
        if nudge.mood != "normal":
            GLib.idle_add(self._flash_mood, nudge.mood, 6000)

    def _drain_nudges(self) -> bool:
        if self._nudge_backlog and not self.backend.busy \
                and not self.confirm_popup.win.get_visible():
            self._present_nudge(self._nudge_backlog.pop(0))
        return False

    def _action_notify(self, text: str, mood: str) -> None:
        """Resultado de una acción (puede llegar desde un callback async)."""
        GLib.idle_add(self._ephemeral, text, 8000,
                      mood if mood in _MOODS else "normal", False)

    def _summon(self) -> bool:
        self._listening = True
        self._refresh_orb()
        self.inputbar.set_mood(self._persistent_mood)  # la barra sale ya teñida del reposo
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
        if self._flash_id is not None:  # cancela un flash de mood pendiente (say/notify/deny)
            GLib.source_remove(self._flash_id)
            self._flash_id = None
        self.inputbar.set_mood(self._persistent_mood)
        self._turn_text = ""
        if self._notif_current is not None:  # el turno le quita el bocadillo a la notif
            n, self._notif_current = self._notif_current, None
            if n.get("id") and self.notifyd:
                from .notifyd import CLOSE_REASON_EXPIRED
                self.notifyd.close(int(n["id"]), CLOSE_REASON_EXPIRED)
        self.history.add_turn("operativo", text)
        chatlog.append_turn("operativo", text, ts=time.time())
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
                chatlog.append_turn("Nyx", self._turn_text, self._current_mood,
                                    ts=time.time())
            self._turn_text = ""
            if sig.cost_usd is not None:  # métricas para `status`/panel de control
                self._cost_last = sig.cost_usd
                self._cost_total += sig.cost_usd
            self._turns += 1
            self.inputbar.set_mood(self._persistent_mood)
            self._set_nyx("idle")
            # las notifs retenidas durante el turno salen cuando el bocadillo de la
            # respuesta se oculte (on_hidden → _notif_show_next), no antes
            GLib.idle_add(self._drain_nudges)  # propuestas retenidas durante el turno
            GLib.idle_add(self.control.refresh_if_visible)  # coste/turnos al día


def main() -> None:
    NyxApp().run(None)
