"""Panel de historial de chat de Nyx: ventana layer-shell lateral que acumula
todos los turnos del daemon (user + Nyx). Se muestra/oculta con toggle().
Los turnos se guardan en memoria; se vacía al reiniciar el daemon."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LS  # noqa: E402

from . import markup, theme  # noqa: E402

_PANEL_CSS = f"""
.nyx-history-panel {{
  background: rgba(10,15,30,0.94);
  border-right: 1px solid rgba(85,234,212,0.18);
}}
.nyx-history-title {{
  color: #55ead4;
  font-family: {theme.FONT};
  font-size: 11px;
  opacity: 0.7;
  padding: 8px 14px 4px;
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
"""

_WIDTH = 320


class HistoryPanel:
    def __init__(self, app, width: int = _WIDTH):
        width = int(width)
        w = Gtk.ApplicationWindow(application=app)
        LS.init_for_window(w)
        LS.set_layer(w, LS.Layer.OVERLAY)
        LS.set_anchor(w, LS.Edge.TOP, True)
        LS.set_anchor(w, LS.Edge.BOTTOM, True)
        LS.set_anchor(w, LS.Edge.LEFT, True)
        LS.set_exclusive_zone(w, width)
        LS.set_keyboard_mode(w, LS.KeyboardMode.NONE)
        LS.set_namespace(w, "nyx-history")
        w.set_decorated(False)
        w.set_default_size(width, -1)

        theme.apply_css(_PANEL_CSS)

        title = Gtk.Label(label="▸ HISTORIAL")
        title.add_css_class("nyx-history-title")
        title.set_xalign(0.0)

        self._listbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_child(self._listbox)
        self._scroll = scroll

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.add_css_class("nyx-history-panel")
        vbox.append(title)
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
            if mood in ("alert", "heated"):
                label.add_css_class(f"nyx-history-nyx-{mood}")  # solo override de color

        self._listbox.append(label)
        if self._visible:
            GLib.idle_add(self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> bool:
        adj = self._scroll.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return False
