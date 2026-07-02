"""Barra de entrada de Nyx (Fase 1): ventana layer-shell con foco de teclado.

`KeyboardMode.ON_DEMAND` + grab_focus en "map" recibe teclas al instante SIN clic
(validado en KWin 6). Se invoca con un atajo (op `summon`); Enter envía, Esc cierra.
"""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LS  # noqa: E402

from . import hud, theme  # noqa: E402


class InputBar:
    def __init__(
        self, app, on_submit: Callable[[str], None],
        on_dismiss: Callable[[], None] | None = None,
        margin_bottom: int = 220,
    ):
        self.on_submit = on_submit
        self.on_dismiss = on_dismiss
        w = Gtk.ApplicationWindow(application=app)
        LS.init_for_window(w)
        LS.set_layer(w, LS.Layer.OVERLAY)
        LS.set_anchor(w, LS.Edge.BOTTOM, True)
        LS.set_margin(w, LS.Edge.BOTTOM, int(margin_bottom))
        LS.set_keyboard_mode(w, LS.KeyboardMode.ON_DEMAND)
        LS.set_namespace(w, "nyx-input")
        w.set_decorated(False)
        w.set_default_size(580, -1)

        theme.apply_css(theme.INPUT_CSS)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.add_css_class("nyx-input-box")
        glyph = Gtk.Label(label="🌙")
        glyph.add_css_class("nyx-input-glyph")
        self.entry = Gtk.Entry()
        self.entry.add_css_class("nyx-input-entry")
        self.entry.set_hexpand(True)
        self.entry.set_placeholder_text("Pregúntale a Nyx…   (Enter envía · Esc cierra)")
        self.entry.connect("activate", self._submit)
        box.append(glyph)
        box.append(self.entry)
        self._box = box
        self._hud = hud.HudFrame()  # marco animado, recoloreable por mood
        panel = Gtk.Overlay()
        panel.set_child(box)
        panel.add_overlay(self._hud)
        panel.set_measure_overlay(self._hud, False)
        w.set_child(panel)

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        w.add_controller(key)
        w.connect("map", lambda *_: self.entry.grab_focus())

        self.win = w
        w.set_visible(False)

    def set_margins(self, margin_bottom: int) -> None:
        """Reposiciona la barra en vivo (op `reload` tras cambiar ui.inputbar.*)."""
        LS.set_margin(self.win, LS.Edge.BOTTOM, int(margin_bottom))

    def show(self) -> bool:
        self.entry.set_text("")
        self.win.set_visible(True)
        self.entry.grab_focus()
        return False  # usable como callback de GLib.idle_add

    def hide(self) -> None:
        self.win.set_visible(False)

    def set_mood(self, mood: str) -> None:
        """Tiñe la barra rápida igual que el resto de superficies (glow + marco HUD)."""
        for cls in ("nyx-input-box-alert", "nyx-input-box-heated"):
            self._box.remove_css_class(cls)
        if mood in ("alert", "heated"):
            self._box.add_css_class(f"nyx-input-box-{mood}")
        self._hud.set_mood(mood)

    def _submit(self, entry):
        text = entry.get_text().strip()
        self.win.set_visible(False)
        if text:
            self.on_submit(text)
        elif self.on_dismiss:
            self.on_dismiss()

    def _on_key(self, _ctrl, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            self.win.set_visible(False)
            if self.on_dismiss:
                self.on_dismiss()
            return True
        return False
