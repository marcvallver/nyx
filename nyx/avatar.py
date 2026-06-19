"""Avatar de Nyx: un orbe cyberpunk dibujado con Cairo.

CPU (sin GLArea, por el bug de transparencia NVIDIA #4835). Estados
idle/thinking/talking. Ventana layer-shell propia (esquina sup-der, click-through).
Solo anima cuando está activo: al volver a idle se desvanece y PARA el timer
(cero consumo en reposo). Frame-based (sin reloj).
"""

from __future__ import annotations

import math

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk, Gtk4LayerShell as LS  # noqa: E402

from . import theme  # noqa: E402

TEAL = (0.333, 0.918, 0.831)  # #55EAD4
CORE = (0.85, 1.0, 0.97)      # blanco-teal del núcleo


class Orb:
    SIZE = 120
    FPS_MS = 33  # ~30 fps mientras está activo

    def __init__(self, app):
        w = Gtk.ApplicationWindow(application=app)
        LS.init_for_window(w)
        LS.set_layer(w, LS.Layer.OVERLAY)
        LS.set_anchor(w, LS.Edge.TOP, True)
        LS.set_anchor(w, LS.Edge.RIGHT, True)
        LS.set_margin(w, LS.Edge.TOP, 14)
        LS.set_margin(w, LS.Edge.RIGHT, 16)
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
        self.alpha = 0.0  # fade global 0..1
        self._timer: int | None = None
        w.set_visible(False)

    def _clickthrough(self, *_):
        try:
            surf = self.win.get_surface()
            if surf is not None:
                surf.set_input_region(cairo.Region())
        except Exception:
            pass

    def set_state(self, state: str) -> bool:
        if state != self.state:
            self.state = state
            if state != "idle":
                self.win.set_visible(True)
            self._ensure_timer()
        return False  # usable como callback de GLib.idle_add

    def _ensure_timer(self):
        if self._timer is None:
            self._timer = GLib.timeout_add(self.FPS_MS, self._tick)

    def _tick(self) -> bool:
        self.frame += 1
        target = 0.0 if self.state == "idle" else 1.0
        self.alpha += (target - self.alpha) * 0.18
        self.area.queue_draw()
        if self.state == "idle" and self.alpha < 0.02:
            self.alpha = 0.0
            self.win.set_visible(False)
            self._timer = None
            return False  # para el timer en reposo -> cero consumo
        return True

    def _draw(self, _area, cr, width, height):
        if self.alpha <= 0.0:
            return
        cx, cy = width / 2, height / 2
        radius = min(width, height) / 2 - 6
        a = self.alpha
        f = self.frame
        pulse = 0.5 + 0.5 * math.sin(f * 0.08)

        if self.state == "talking":
            core_r = radius * (0.40 + 0.12 * pulse)
            ring_a, glow_a = 0.70, 0.40
        elif self.state == "thinking":
            core_r = radius * (0.34 + 0.05 * pulse)
            ring_a, glow_a = 0.55, 0.30
        else:  # idle (desvaneciéndose)
            core_r = radius * 0.34
            ring_a, glow_a = 0.40, 0.22

        # halo radial
        halo = cairo.RadialGradient(cx, cy, core_r * 0.5, cx, cy, radius)
        halo.add_color_stop_rgba(0, *TEAL, glow_a * a)
        halo.add_color_stop_rgba(1, *TEAL, 0.0)
        cr.set_source(halo)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.fill()

        # núcleo (blanco-teal -> teal -> transparente)
        core = cairo.RadialGradient(cx, cy, 0, cx, cy, core_r)
        core.add_color_stop_rgba(0, *CORE, 0.95 * a)
        core.add_color_stop_rgba(0.5, *TEAL, 0.8 * a)
        core.add_color_stop_rgba(1, *TEAL, 0.0)
        cr.set_source(core)
        cr.arc(cx, cy, core_r, 0, 2 * math.pi)
        cr.fill()

        # anillo base
        cr.set_source_rgba(*TEAL, ring_a * a)
        cr.set_line_width(1.6)
        cr.arc(cx, cy, radius * 0.72, 0, 2 * math.pi)
        cr.stroke()

        if self.state == "thinking":
            # arco rotatorio (procesando)
            ang = f * 0.13
            cr.set_source_rgba(0.85, 1.0, 0.97, 0.9 * a)
            cr.set_line_width(3)
            cr.arc(cx, cy, radius * 0.72, ang, ang + math.pi * 0.5)
            cr.stroke()
        elif self.state == "talking":
            # ripples expansivos (hablando)
            for k in range(2):
                rp = (f * 0.04 + k * 0.5) % 1.0
                cr.set_source_rgba(*TEAL, (1.0 - rp) * 0.5 * a)
                cr.set_line_width(2)
                cr.arc(cx, cy, radius * 0.5 + rp * radius * 0.45, 0, 2 * math.pi)
                cr.stroke()
