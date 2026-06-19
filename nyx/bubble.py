"""Bocadillo cyberpunk de Nyx: ventana layer-shell (esquina sup-der, click-through)
con un sparkle animado + el texto, auto-oculta tras un TTL."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk, Gtk4LayerShell as LS  # noqa: E402

from . import sparkle, theme  # noqa: E402


class Bubble:
    def __init__(self, app):
        w = Gtk.ApplicationWindow(application=app)
        LS.init_for_window(w)
        LS.set_layer(w, LS.Layer.OVERLAY)
        LS.set_anchor(w, LS.Edge.TOP, True)
        LS.set_anchor(w, LS.Edge.RIGHT, True)
        LS.set_margin(w, LS.Edge.TOP, 112)  # justo bajo el sparkle de claude-thinking
        LS.set_margin(w, LS.Edge.RIGHT, 18)
        LS.set_keyboard_mode(w, LS.KeyboardMode.NONE)
        LS.set_namespace(w, "nyx-bubble")
        w.set_decorated(False)

        theme.apply_css(theme.BUBBLE_CSS)

        self.spark = Gtk.Label(label=sparkle.FRAMES[0])
        self.spark.add_css_class("nyx-spark")
        # Caja de tamaño FIJO + glifo centrado: los frames del sparkle (· ✢ ✳ ✶ ✻ ✽)
        # tienen anchos/altos distintos; sin reservar tamaño constante, el bocadillo
        # se redimensiona en cada frame (tiembla). Con size_request fijo, la huella
        # del sparkle no cambia y el bocadillo queda estable.
        self.spark.set_size_request(30, 30)
        self.spark.set_xalign(0.5)
        self.spark.set_yalign(0.0)
        self.spark.set_valign(Gtk.Align.START)
        self.text = Gtk.Label()
        self.text.add_css_class("nyx-text")
        self.text.set_wrap(True)
        self.text.set_xalign(0.0)
        self.text.set_max_width_chars(42)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class("nyx-box")
        row.append(self.spark)
        row.append(self.text)
        w.set_child(row)
        w.connect("realize", self._clickthrough)

        self.win = w
        self.i = 0
        self._tick_id: int | None = None
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

    def show_text(self, text: str, ttl_ms: int = 12000) -> None:
        self.text.set_text(text)
        self.win.set_visible(True)
        if self._tick_id is None:
            self._tick_id = GLib.timeout_add(sparkle.FRAME_MS, self._tick)
        if self._fade_id is not None:
            GLib.source_remove(self._fade_id)
        self._fade_id = GLib.timeout_add(ttl_ms, self._hide)

    def _tick(self) -> bool:
        self.i = (self.i + 1) % len(sparkle.FRAMES)
        self.spark.set_text(sparkle.FRAMES[self.i])
        return True

    def _hide(self) -> bool:
        self.win.set_visible(False)
        if self._tick_id is not None:
            GLib.source_remove(self._tick_id)
            self._tick_id = None
        self._fade_id = None
        return False
