"""Popup de confirmación de Nyx (Fase 4): cuando una acción cae en la zona gris,
Nyx pregunta antes de ejecutarla. Ventana layer-shell INTERACTIVA (no click-through)
con foco de teclado: Esc = denegar, Enter = permitir una vez. Botones: Denegar /
Permitir una vez / Permitir siempre."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LS  # noqa: E402

from . import theme  # noqa: E402

CSS = """
window { background: transparent; }
.nyx-confirm {
  background: rgba(13,20,38,0.97);
  border: 1px solid #55ead4;
  border-radius: 14px;
  padding: 14px 16px;
}
.nyx-confirm-title { color: #f3e600; font-weight: bold; font-size: 13px; }
.nyx-confirm-cmd {
  color: #d6fff7; font-family: "MesloLGL Nerd Font Mono","DejaVu Sans Mono",monospace;
  font-size: 14px; background: #0a0a12; border-radius: 8px; padding: 8px 10px;
}
.nyx-confirm-reason { color: #7fb6ad; font-size: 11px; }
button.nyx-deny {
  background: rgba(197,0,60,0.22); color: #ff6b8e;
  border: 1px solid #c5003c; border-radius: 8px; padding: 6px 12px;
}
button.nyx-once {
  background: rgba(85,234,212,0.18); color: #55ead4;
  border: 1px solid #55ead4; border-radius: 8px; padding: 6px 12px;
}
button.nyx-always {
  background: transparent; color: #7fb6ad;
  border: 1px solid #2c5c55; border-radius: 8px; padding: 6px 12px;
}
"""


class ConfirmPopup:
    def __init__(self, app):
        w = Gtk.ApplicationWindow(application=app)
        LS.init_for_window(w)
        LS.set_layer(w, LS.Layer.OVERLAY)
        LS.set_anchor(w, LS.Edge.BOTTOM, True)
        LS.set_margin(w, LS.Edge.BOTTOM, 220)
        LS.set_keyboard_mode(w, LS.KeyboardMode.ON_DEMAND)
        LS.set_namespace(w, "nyx-confirm")
        w.set_decorated(False)
        w.set_default_size(620, -1)
        theme.apply_css(CSS)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.add_css_class("nyx-confirm")
        self.title = Gtk.Label(xalign=0)
        self.title.add_css_class("nyx-confirm-title")
        self.cmd = Gtk.Label(xalign=0)
        self.cmd.add_css_class("nyx-confirm-cmd")
        self.cmd.set_wrap(True)
        self.cmd.set_max_width_chars(60)
        self.cmd.set_selectable(True)
        self.reason = Gtk.Label(xalign=0)
        self.reason.add_css_class("nyx-confirm-reason")

        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.END)
        b_deny = Gtk.Button(label="Denegar  (Esc)")
        b_deny.add_css_class("nyx-deny")
        b_deny.connect("clicked", lambda *_: self._decide("deny"))
        b_once = Gtk.Button(label="Permitir una vez  (Enter)")
        b_once.add_css_class("nyx-once")
        b_once.connect("clicked", lambda *_: self._decide("allow"))
        b_always = Gtk.Button(label="Permitir siempre")
        b_always.add_css_class("nyx-always")
        b_always.connect("clicked", lambda *_: self._decide("always"))
        btns.append(b_deny)
        btns.append(b_always)
        btns.append(b_once)

        box.append(self.title)
        box.append(self.cmd)
        box.append(self.reason)
        box.append(btns)
        w.set_child(box)

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        w.add_controller(key)
        self._b_once = b_once

        self.win = w
        self._cb: Callable[[str], None] | None = None
        w.set_visible(False)

    def show(
        self, tool: str, command: str, reason: str, on_decision: Callable[[str], None]
    ) -> bool:
        self._cb = on_decision
        verb = "ejecutar" if tool == "Bash" else "usar"
        self.title.set_text(f"🌙 Nyx quiere {verb} ({tool}):")
        self.cmd.set_text(command or tool)
        self.reason.set_text(f"⚠ {reason}" if reason else "")
        self.win.set_visible(True)
        self._b_once.grab_focus()
        return False  # usable como callback de GLib.idle_add

    def _decide(self, decision: str):
        cb, self._cb = self._cb, None
        self.win.set_visible(False)
        if cb:
            cb(decision)

    def _on_key(self, _ctrl, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            self._decide("deny")
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._decide("allow")
            return True
        return False
