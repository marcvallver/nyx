"""Centro de control de Nyx: VENTANA NORMAL del sistema (KWin la decora con
Klassy → arrastrable, reescalable y recolocable como cualquier app), estética
HUD cyberpunk dentro (HudFrame + scanlines) teñida por el mood. Al abrirse, el
orbe se desliza con ease al centro de la pantalla (misma altura) y al cerrarla
vuelve a su esquina.

Estado del daemon (modelo, sesión, coste), interruptores en vivo (voz, notifs,
takeover, DND, eco de terminal), mood persistente, watchers y acciones. Todos
los toggles respaldados por config pasan por la MISMA ruta que `nyx-ctl config
set` (config.update + reload del daemon): una sola fuente de verdad.
"""

from __future__ import annotations

import subprocess

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import config, hud, theme  # noqa: E402

_WIDTH = 400
_HEIGHT = 660
_MODELS = ("sonnet", "opus", "haiku")

_PANEL_CSS = f"""
.nyx-panel {{
  background: rgba(10,15,30,0.96);
  padding: 18px 20px;
}}
.nyx-panel-section {{
  color: {theme.YELLOW};
  font-family: {theme.FONT};
  font-size: 10px;
  opacity: 0.75;
  margin-top: 12px;
}}
.nyx-panel-label {{
  color: {theme.TEXT};
  font-family: {theme.FONT};
  font-size: 12px;
}}
.nyx-panel-value {{
  color: rgba(214,255,247,0.55);
  font-family: {theme.FONT};
  font-size: 12px;
}}
.nyx-panel switch {{
  background: rgba({theme.GLOW_RGB}, 0.10);
  border: 1px solid rgba({theme.GLOW_RGB}, 0.4);
  min-height: 0;
}}
.nyx-panel switch:checked {{ background: rgba({theme.GLOW_RGB}, 0.45); }}
.nyx-panel-mood {{
  font-family: {theme.FONT};
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  background: transparent;
  border: 1px solid rgba({theme.GLOW_RGB}, 0.35);
  color: {theme.TEXT};
  min-height: 0;
}}
.nyx-panel-mood-active {{ background: rgba({theme.GLOW_RGB}, 0.30); }}
.nyx-panel-action {{
  font-family: {theme.FONT};
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 6px;
  background: rgba({theme.GLOW_RGB}, 0.08);
  border: 1px solid rgba({theme.GLOW_RGB}, 0.45);
  color: {theme.TEAL};
  min-height: 0;
}}
.nyx-panel-action:hover {{ background: rgba({theme.GLOW_RGB}, 0.20); }}
"""


class ControlPanel:
    def __init__(self, app):
        self.app = app
        self._updating = False  # refresco programático: no disparar handlers
        # ventana NORMAL (no layer-shell): KWin la decora, mueve, escala y snapea
        w = Gtk.ApplicationWindow(application=app)
        w.set_title("Nyx · Control")
        w.set_default_size(_WIDTH, _HEIGHT)
        w.add_css_class("nyx-win")  # shape Klassy (radius 8), como el resto del sistema
        w.connect("close-request", self._on_close_request)
        self._titlebar = hud.HudTitlebar("NYX · CONTROL", self._on_close_clicked)
        w.set_titlebar(self._titlebar)
        theme.apply_css(_PANEL_CSS)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.add_css_class("nyx-panel")

        # ── ESTADO ──
        box.append(self._section("ESTADO"))
        self._v_model = self._kv(box, "modelo")
        self._v_session = self._kv(box, "sesión")
        self._v_cost = self._kv(box, "turnos")
        self._v_notifs = self._kv(box, "notifs")

        # ── INTERRUPTORES ──
        box.append(self._section("INTERRUPTORES"))
        self._sw_tts = self._switch(box, "Voz (TTS)", self._on_tts)
        self._sw_notifs = self._switch(box, "Notificaciones D-Bus",
                                       self._cfg_toggle("notifications.enabled"))
        self._sw_takeover = self._switch(box, "Takeover (popup de Plasma)",
                                         self._cfg_toggle("notifications.takeover"))
        self._sw_dnd = self._switch(box, "No molestar",
                                    self._cfg_toggle("notifications.dnd"))
        self._sw_echo = self._switch(box, "Eco de terminal",
                                     self._cfg_toggle("terminal_echo.enabled"))

        # ── MOOD ──
        box.append(self._section("MOOD"))
        moods_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._mood_btns: dict[str, Gtk.Button] = {}
        for m in theme.MOODS:
            btn = Gtk.Button(label=m)
            btn.add_css_class("nyx-panel-mood")
            btn.connect("clicked", lambda _b, mm=m: self._on_mood(mm))
            moods_box.append(btn)
            self._mood_btns[m] = btn
        box.append(moods_box)

        # ── POSICIÓN DEL ORBE ──
        box.append(self._section("POSICIÓN DEL ORBE"))
        pos_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._pos_btns: dict[str, Gtk.Button] = {}
        for c, sym in (("tl", "↖"), ("tr", "↗"), ("bl", "↙"), ("br", "↘")):
            btn = Gtk.Button(label=sym)
            btn.add_css_class("nyx-panel-mood")
            btn.connect("clicked", lambda _b, cc=c: self._on_corner(cc))
            pos_box.append(btn)
            self._pos_btns[c] = btn
        box.append(pos_box)

        # ── MODELO ──
        box.append(self._section("MODELO DEL BACKEND"))
        self._dd_model = Gtk.DropDown.new_from_strings(list(_MODELS))
        self._dd_model.connect("notify::selected", self._on_model)
        box.append(self._dd_model)

        # ── WATCHERS ──
        box.append(self._section("WATCHERS"))
        self._watcher_switches: dict[str, Gtk.Switch] = {}
        self._watchers_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.append(self._watchers_box)

        # ── ACCIONES ──
        box.append(self._section("ACCIONES"))
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, cb in (("Historial", lambda: self.app.history.toggle()),
                          ("Recargar", self._on_reload),
                          ("Reiniciar", self._on_restart)):
            btn = Gtk.Button(label=label)
            btn.add_css_class("nyx-panel-action")
            btn.connect("clicked", lambda _b, c=cb: c())
            actions.append(btn)
        box.append(actions)

        hint = Gtk.Label(label="Esc cierra · nyx-ctl config para el resto", xalign=0.0)
        hint.add_css_class("nyx-panel-value")
        hint.set_margin_top(10)
        box.append(hint)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(box)
        # mini marco interior: sin él, el clip del scroll corta el contenido
        # a ras de los brackets en la esquina inferior (feedback de Marc)
        scroll.set_margin_top(6)
        scroll.set_margin_bottom(14)
        scroll.set_margin_start(6)
        scroll.set_margin_end(6)

        # inset 4: el clip redondeado de la ventana (radius 8) no toca los brackets
        self._hud = hud.HudFrame(inset=4.0, radius=8.0)
        overlay = Gtk.Overlay()
        overlay.set_child(scroll)
        overlay.add_overlay(self._hud)
        overlay.set_measure_overlay(self._hud, False)
        w.set_child(overlay)

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        w.add_controller(key)

        self.win = w
        self._visible = False
        w.set_visible(False)

    # --- construcción ---
    @staticmethod
    def _section(text: str) -> Gtk.Label:
        lbl = Gtk.Label(label=f"── {text} ──", xalign=0.0)
        lbl.add_css_class("nyx-panel-section")
        return lbl

    def _kv(self, box: Gtk.Box, label: str) -> Gtk.Label:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        k = Gtk.Label(label=label, xalign=0.0)
        k.add_css_class("nyx-panel-label")
        k.set_hexpand(True)
        v = Gtk.Label(label="—", xalign=1.0)
        v.add_css_class("nyx-panel-value")
        row.append(k)
        row.append(v)
        box.append(row)
        return v

    def _switch(self, box: Gtk.Box, label: str, on_change) -> Gtk.Switch:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl = Gtk.Label(label=label, xalign=0.0)
        lbl.add_css_class("nyx-panel-label")
        lbl.set_hexpand(True)
        sw = Gtk.Switch(valign=Gtk.Align.CENTER)
        sw.connect("state-set", lambda _s, state: on_change(state))
        row.append(lbl)
        row.append(sw)
        box.append(row)
        return sw

    # --- handlers ---
    def _cfg_toggle(self, path: str):
        def _cb(state: bool) -> bool:
            if not self._updating:
                config.update({path: bool(state)})
                GLib.idle_add(self._reload_and_refresh)
            return False  # deja que el switch cambie
        return _cb

    def _on_tts(self, state: bool) -> bool:
        if not self._updating:
            self.app.tts.set_enabled(bool(state), persist=True)
        return False

    def _on_mood(self, mood: str) -> None:
        self.app.set_persistent_mood(mood)
        GLib.idle_add(self.refresh)

    def _on_corner(self, corner: str) -> None:
        """Cambia la esquina de reposo: misma ruta que nyx-ctl config set
        ui.orb.corner (el reload dispara el warp CRT del orbe)."""
        config.update({"ui.orb.corner": corner})
        GLib.idle_add(self._reload_and_refresh)

    def _on_model(self, *_):
        if self._updating:
            return
        idx = self._dd_model.get_selected()
        if 0 <= idx < len(_MODELS):
            config.update({"backend.model": _MODELS[idx]})
            GLib.idle_add(self._reload_and_refresh)

    def _on_reload(self) -> None:
        self._reload_and_refresh()

    def _reload_and_refresh(self) -> bool:
        self.app._reload_config()
        self.refresh()
        return False

    def _on_restart(self) -> None:
        subprocess.Popen(["systemctl", "--user", "restart", "nyx.service"],
                         start_new_session=True)

    def _on_key(self, _ctrl, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            self.toggle()
            return True
        return False

    def _on_close_request(self, *_) -> bool:
        """El × de la decoración oculta (no destruye) y devuelve el orbe a su sitio."""
        if self._visible:
            self.toggle()
            return True  # ya gestionado
        return False

    def _on_close_clicked(self) -> None:
        """El × de la titlebar HUD: misma ruta que el close-request de KWin."""
        self._on_close_request()

    def set_mood(self, mood: str) -> None:
        """Tiñe el marco HUD y la titlebar (llamado por app._apply_persistent_mood)."""
        self._hud.set_mood(mood)
        self._titlebar.set_mood(mood)

    # --- ciclo ---
    def refresh_if_visible(self) -> bool:
        if self._visible:
            self.refresh()
        return False

    def toggle(self) -> bool:
        self._visible = not self._visible
        if self._visible:
            self.refresh()
        self.win.set_visible(self._visible)
        self.app.orb.warp_center(self._visible)  # el orbe preside su panel (warp CRT)
        return False

    def refresh(self) -> bool:
        """Vuelca el estado real del daemon a los widgets (sin disparar handlers)."""
        if not self._visible and not self.win.get_visible():
            pass  # refrescar barato también en frío (se abre ya al día)
        app = self.app
        self._updating = True
        try:
            self._v_model.set_text(app.backend.model)
            sid = app.backend.session_id or "(nueva)"
            self._v_session.set_text(sid[:13] + "…" if len(sid) > 14 else sid)
            last = f"${app._cost_last:.4f}" if app._cost_last is not None else "—"
            self._v_cost.set_text(f"{app._turns} · último {last}"
                                  f" · total ${app._cost_total:.4f}")
            self._v_notifs.set_text(
                ("activas" if app.notifyd else "off")
                + (f" · {app._notif_queue.pending_count()} en cola"
                   if app._notif_queue.pending_count() else ""))
            cfg = app._config
            self._sw_tts.set_active(app.tts.enabled)
            self._sw_notifs.set_active(bool(config.get_path(cfg, "notifications.enabled")))
            self._sw_takeover.set_active(bool(config.get_path(cfg, "notifications.takeover")))
            self._sw_dnd.set_active(bool(config.get_path(cfg, "notifications.dnd")))
            self._sw_echo.set_active(bool(config.get_path(cfg, "terminal_echo.enabled", True)))
            for m, btn in self._mood_btns.items():
                btn.remove_css_class("nyx-panel-mood-active")
                if m == app._persistent_mood:
                    btn.add_css_class("nyx-panel-mood-active")
            corner = config.get_path(cfg, "ui.orb.corner", "tr")
            for c, btn in self._pos_btns.items():
                btn.remove_css_class("nyx-panel-mood-active")
                if c == corner:
                    btn.add_css_class("nyx-panel-mood-active")
            model = config.get_path(cfg, "backend.model", "sonnet")
            if model in _MODELS:
                self._dd_model.set_selected(_MODELS.index(model))
            self._refresh_watchers()
            self.set_mood(app._persistent_mood)
        finally:
            self._updating = False
        return False

    def _refresh_watchers(self) -> None:
        status = self.app.watchers.status()
        if not self._watcher_switches:  # primera vez: crear filas
            for name in status:
                sw = self._switch(self._watchers_box, name,
                                  self._cfg_toggle(f"watchers.{name}.enabled"))
                self._watcher_switches[name] = sw
        for name, st in status.items():
            sw = self._watcher_switches.get(name)
            if sw is not None:
                sw.set_active(bool(st.get("enabled")))
                sw.set_tooltip_text("running" if st.get("running")
                                    else st.get("error", "off"))
