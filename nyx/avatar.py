"""Avatar de Nyx: glow Cairo + el glifo sparkle de Claude, sin anillos.

Un orbe suave (halo radial) con el glifo `· ✢ ✳ ✶ ✻ ✽` dibujado con PangoCairo
en el centro. Pequeño y discreto en idle; CRECE al pensar/hablar. Sin círculo de
carga. Estados idle/thinking/talking con transición suave (scale/alpha lerpeados).
Cairo/CPU (sin GLArea, por el bug NVIDIA #4835). Solo anima cuando hace falta:
en idle estable PARA el timer (cero consumo). Ventana layer-shell, click-through.
"""

from __future__ import annotations

import math

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk, Pango, PangoCairo, Gtk4LayerShell as LS  # noqa: E402

from . import sparkle, theme  # noqa: E402

TEAL = (0.333, 0.918, 0.831)  # #55EAD4
WHITE_TEAL = (0.85, 1.0, 0.97)

# objetivos por estado: scale (tamaño), glow (alpha halo), glyph (alpha glifo)
STATES = {
    "idle":     {"scale": 0.40, "glow": 0.16, "glyph": 0.6},
    "thinking": {"scale": 0.82, "glow": 0.34, "glyph": 0.95},
    "talking":  {"scale": 1.00, "glow": 0.42, "glyph": 1.0},
}
IDLE_GLYPH = "✳"


class Orb:
    SIZE = 96
    FPS_MS = 33  # ~30 fps mientras anima

    def __init__(self, app):
        w = Gtk.ApplicationWindow(application=app)
        LS.init_for_window(w)
        LS.set_layer(w, LS.Layer.OVERLAY)
        LS.set_anchor(w, LS.Edge.TOP, True)
        LS.set_anchor(w, LS.Edge.RIGHT, True)
        LS.set_margin(w, LS.Edge.TOP, 16)
        LS.set_margin(w, LS.Edge.RIGHT, 18)
        LS.set_keyboard_mode(w, LS.KeyboardMode.NONE)
        LS.set_namespace(w, "nyx-avatar")
        w.set_decorated(False)
        w.set_default_size(self.SIZE, self.SIZE)
        theme.apply_css("window { background: transparent; }")

        self.area = Gtk.DrawingArea()
        self.area.set_content_width(self.SIZE)
        self.area.set_content_height(self.SIZE)
        self.area.set_draw_func(self._draw)
        w.set_child(self.area)
        w.connect("realize", self._clickthrough)

        self.win = w
        self.state = "idle"
        self.frame = 0
        # valores animados (arrancan en idle)
        self.s_scale = STATES["idle"]["scale"]
        self.s_glow = STATES["idle"]["glow"]
        self.s_glyph = STATES["idle"]["glyph"]
        self._timer: int | None = None
        w.set_visible(True)  # presencia pequeña y permanente
        self._ensure_timer()  # un par de ticks para asentar y dibujar idle

    def _clickthrough(self, *_):
        try:
            surf = self.win.get_surface()
            if surf is not None:
                surf.set_input_region(cairo.Region())
        except Exception:
            pass

    def set_state(self, state: str) -> bool:
        if state in STATES and state != self.state:
            self.state = state
            self._ensure_timer()
        return False  # usable como callback de GLib.idle_add

    def _ensure_timer(self):
        if self._timer is None:
            self._timer = GLib.timeout_add(self.FPS_MS, self._tick)

    def _settled(self) -> bool:
        t = STATES[self.state]
        return (
            abs(self.s_scale - t["scale"]) < 0.005
            and abs(self.s_glow - t["glow"]) < 0.005
            and abs(self.s_glyph - t["glyph"]) < 0.01
        )

    def _tick(self) -> bool:
        self.frame += 1
        t = STATES[self.state]
        k = 0.18
        self.s_scale += (t["scale"] - self.s_scale) * k
        self.s_glow += (t["glow"] - self.s_glow) * k
        self.s_glyph += (t["glyph"] - self.s_glyph) * k
        self.area.queue_draw()
        # en idle, una vez asentado, parar -> orbe pequeño estático, cero consumo
        if self.state == "idle" and self._settled():
            self._timer = None
            return False
        return True

    def _glyph(self) -> str:
        if self.state == "thinking":
            idx = (self.frame * self.FPS_MS // sparkle.FRAME_MS) % len(sparkle.FRAMES)
            return sparkle.FRAMES[idx]
        if self.state == "talking":
            return sparkle.PEAK
        return IDLE_GLYPH

    def _draw(self, _area, cr, width, height):
        cx, cy = width / 2, height / 2
        max_r = min(width, height) / 2 - 3
        pulse = 0.5 + 0.5 * math.sin(self.frame * 0.08)
        glow = self.s_glow * (0.85 + 0.15 * pulse if self.state == "talking" else 1.0)
        radius = max_r * self.s_scale

        # halo radial (sin bordes duros)
        halo = cairo.RadialGradient(cx, cy, radius * 0.15, cx, cy, radius)
        halo.add_color_stop_rgba(0, *TEAL, glow)
        halo.add_color_stop_rgba(1, *TEAL, 0.0)
        cr.set_source(halo)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.fill()

        # glifo (PangoCairo, escalado con el orbe): bloom teal + nítido encima
        font_px = max(9.0, radius * 0.92)
        layout = PangoCairo.create_layout(cr)
        desc = Pango.FontDescription("MesloLGL Nerd Font Mono")
        desc.set_weight(Pango.Weight.BOLD)
        glyph = self._glyph()
        for size_mul, color, alpha in (
            (1.18, TEAL, self.s_glyph * 0.45),       # bloom
            (1.0, WHITE_TEAL, self.s_glyph),          # nítido
        ):
            desc.set_absolute_size(font_px * size_mul * Pango.SCALE)
            layout.set_font_description(desc)
            layout.set_text(glyph, -1)
            gw, gh = layout.get_pixel_size()
            cr.set_source_rgba(*color, alpha)
            cr.move_to(cx - gw / 2, cy - gh / 2)
            PangoCairo.show_layout(cr, layout)
