"""Panel de historial de chat de Nyx: VENTANA NORMAL del sistema (KWin la
decora con Klassy → arrastrable, reescalable y recolocable). Acumula los turnos
del daemon (operativo ⇄ Nyx, recargados del hilo persistente al arrancar) y las
notificaciones compactas. Se muestra/oculta con toggle() (Meta+H)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import hud, markup, theme  # noqa: E402

_PANEL_CSS = f"""
.nyx-history-panel {{
  background: rgba(10,15,30,0.94);
  border-right: 1px solid rgba(85,234,212,0.18);
}}
.nyx-history-user {{
  color: rgba(214,255,247,0.65);
  font-family: {theme.FONT};
  font-size: 13px;
  padding: 4px 14px;
}}
.nyx-history-nyx {{
  color: #d6fff7;
  font-family: {theme.FONT};
  font-size: 13px;
  padding: 4px 14px;
}}
.nyx-history-nyx-alert  {{ color: #ff6666; }}
.nyx-history-nyx-heated {{ color: #ff9e00; }}
.nyx-history-nyx-glad   {{ color: {theme.GLAD}; }}
.nyx-history-nyx-dim    {{ color: {theme.DIM}; }}
.nyx-history-notif {{
  color: rgba(214,255,247,0.45);
  font-family: {theme.FONT};
  font-size: 12px;
  padding: 2px 14px;
}}
.nyx-history-notif-silenced {{ color: rgba(139,131,91,0.55); }}
"""

_WIDTH = 320


class HistoryPanel:
    def __init__(self, app, width: int = _WIDTH):
        width = int(width)
        # ventana NORMAL (no layer-shell): KWin la decora, mueve, escala y snapea
        w = Gtk.ApplicationWindow(application=app)
        w.set_title("Nyx · Historial")
        w.set_default_size(width, 700)
        w.add_css_class("nyx-square")  # esquinas rectas: no cortar los brackets
        w.connect("close-request", self._on_close_request)
        self._titlebar = hud.HudTitlebar("NYX · HISTORIAL", self._on_close_clicked)
        w.set_titlebar(self._titlebar)
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        w.add_controller(key)

        theme.apply_css(_PANEL_CSS)

        self._listbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_child(self._listbox)
        self._scroll = scroll

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.add_css_class("nyx-history-panel")
        vbox.append(scroll)

        w.set_child(vbox)
        self.win = w
        self._visible = False
        w.set_visible(False)

    def toggle(self) -> bool:
        self._visible = not self._visible
        self.win.set_visible(self._visible)
        if self._visible:
            GLib.idle_add(self._scroll_to_bottom)  # tras el relayout del frame, no antes
        return False

    def _on_close_request(self, *_) -> bool:
        """El × de la decoración oculta (no destruye)."""
        if self._visible:
            self.toggle()
            return True
        return False

    def _on_close_clicked(self) -> None:
        """El × de la titlebar HUD: misma ruta que el close-request de KWin."""
        self._on_close_request()

    def set_mood(self, mood: str) -> None:
        """Tiñe la titlebar (llamado por app._apply_persistent_mood)."""
        self._titlebar.set_mood(mood)

    def _on_key(self, _ctrl, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape and self._visible:
            self.toggle()
            return True
        return False

    def add_turn(self, role: str, text: str, mood: str = "normal") -> None:
        label = Gtk.Label()
        label.set_wrap(True)
        label.set_xalign(0.0)
        label.set_max_width_chars(36)

        prefix = "→ " if role == "operativo" else "Nyx · "
        try:
            label.set_markup(markup.to_pango(f"{prefix}{text}"))
        except Exception:
            label.set_text(f"{prefix}{text}")

        if role == "operativo":
            label.add_css_class("nyx-history-user")
        else:
            label.add_css_class("nyx-history-nyx")  # base: fuente/tamaño/padding
            if mood != "normal" and mood in theme.MOODS:
                label.add_css_class(f"nyx-history-nyx-{mood}")  # solo override de color

        self._listbox.append(label)
        if self._visible:
            GLib.idle_add(self._scroll_to_bottom)

    def add_notification(self, n: dict, shown: bool = True) -> None:
        """Fila compacta de notificación (las silenciadas también: esa es la gracia)."""
        label = Gtk.Label()
        label.set_wrap(True)
        label.set_xalign(0.0)
        label.set_max_width_chars(36)
        app = n.get("app") or "sistema"
        summary = n.get("summary") or ""
        suffix = "" if shown else "  (silenciada)"
        label.set_text(f"✶ {app} · {summary}{suffix}")
        label.add_css_class("nyx-history-notif")
        if not shown:
            label.add_css_class("nyx-history-notif-silenced")
        self._listbox.append(label)
        if self._visible:
            GLib.idle_add(self._scroll_to_bottom)

    def clear(self) -> bool:
        """Vacía el panel (sesión core nueva)."""
        while (child := self._listbox.get_first_child()) is not None:
            self._listbox.remove(child)
        return False

    def _scroll_to_bottom(self) -> bool:
        adj = self._scroll.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return False
