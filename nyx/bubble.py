"""Bocadillo cyberpunk de Nyx: ventana layer-shell (esquina sup-der, click-through)
con el TEXTO de la respuesta. El indicador animado es el orbe (avatar.py); aquí solo
hablan las palabras. Fade-in/out con Gtk.Revealer, streaming (start/append/finalize)
y render de markdown al finalizar. Auto-oculta tras un TTL."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk, Gtk4LayerShell as LS  # noqa: E402

from . import markup, theme  # noqa: E402


class Bubble:
    def __init__(self, app):
        w = Gtk.ApplicationWindow(application=app)
        LS.init_for_window(w)
        LS.set_layer(w, LS.Layer.OVERLAY)
        LS.set_anchor(w, LS.Edge.TOP, True)
        LS.set_anchor(w, LS.Edge.RIGHT, True)
        LS.set_margin(w, LS.Edge.TOP, 140)  # justo bajo el orbe (avatar)
        LS.set_margin(w, LS.Edge.RIGHT, 18)
        LS.set_keyboard_mode(w, LS.KeyboardMode.NONE)
        LS.set_namespace(w, "nyx-bubble")
        w.set_decorated(False)

        theme.apply_css(theme.BUBBLE_CSS)

        self.text = Gtk.Label()
        self.text.add_css_class("nyx-text")
        self.text.set_wrap(True)
        self.text.set_xalign(0.0)
        self.text.set_max_width_chars(46)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        box.add_css_class("nyx-box")
        box.append(self.text)

        self.revealer = Gtk.Revealer()
        self.revealer.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
        self.revealer.set_transition_duration(180)
        self.revealer.set_child(box)
        w.set_child(self.revealer)
        w.connect("realize", self._clickthrough)

        self.win = w
        self._buf = ""
        self._fade_id: int | None = None
        w.set_visible(False)

    def _clickthrough(self, *_):
        try:
            import cairo

            surf = self.win.get_surface()
            if surf is not None:
                surf.set_input_region(cairo.Region())
        except Exception:
            pass

    # --- streaming ---
    def _show(self) -> None:
        self.win.set_visible(True)
        self.revealer.set_reveal_child(True)
        if self._fade_id is not None:
            GLib.source_remove(self._fade_id)
            self._fade_id = None

    def start_stream(self) -> bool:
        self._buf = ""
        self.text.set_text("")
        self._show()
        return False  # usable como callback de GLib.idle_add

    def append(self, chunk: str) -> None:
        self._buf += chunk
        self.text.set_text(self._buf)  # texto plano mientras streamea (markup parcial rompe)

    def finalize(self, ttl_ms: int = 15000) -> None:
        try:
            self.text.set_markup(markup.to_pango(self._buf))  # markdown bonito al cerrar
        except Exception:
            self.text.set_text(self._buf)
        if self._fade_id is not None:
            GLib.source_remove(self._fade_id)
        self._fade_id = GLib.timeout_add(ttl_ms, self._hide)

    def show_text(self, text: str, ttl_ms: int = 12000) -> bool:
        self.start_stream()
        self._buf = text
        self.finalize(ttl_ms)
        return False

    def _hide(self) -> bool:
        self.revealer.set_reveal_child(False)  # fade-out
        self._fade_id = None
        GLib.timeout_add(220, self._really_hide)
        return False

    def _really_hide(self) -> bool:
        if not self.revealer.get_reveal_child():  # no re-abierto entretanto
            self.win.set_visible(False)
        return False
