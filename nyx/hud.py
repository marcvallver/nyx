"""Marco HUD cyberpunk ANIMADO (Cairo): borde teal + corner-brackets que se alargan
y se achican con easing suave + scanlines tenues. Dibujado por encima del contenido
con el centro transparente (no tapa el texto ni roba clics). Da a la barra de entrada
y al bocadillo la misma identidad que la ventanita del avatar.

Solo anima mientras la caja está MAPEADA (visible) → cero CPU cuando está oculta.
"""

from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

TEAL = (0.333, 0.918, 0.831)
FPS_MS = 33          # animación de los brackets (~30 fps; basta para un pulso lento)
PERIOD_S = 4.4       # ciclo del alargar/achicar (lento, tipo idle)


def _rrect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class HudFrame(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_can_target(False)
        self.set_draw_func(self._draw)
        self.frame = 0
        self._timer: int | None = None
        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)

    def _on_map(self, *_):
        if self._timer is None:
            self._timer = GLib.timeout_add(FPS_MS, self._tick)

    def _on_unmap(self, *_):
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def _tick(self) -> bool:
        self.frame += 1
        self.queue_draw()
        return True

    def _draw(self, _area, cr, w, h):
        if w < 8 or h < 8:
            return
        # borde teal suave
        _rrect(cr, 1.0, 1.0, w - 2.0, h - 2.0, 9.0)
        cr.set_source_rgba(*TEAL, 0.5)
        cr.set_line_width(1.3)
        cr.stroke()

        # corner-brackets: la longitud oscila con coseno (ease-in-out suave)
        t = self.frame * FPS_MS / 1000.0
        osc = 0.5 - 0.5 * math.cos(2 * math.pi * t / PERIOD_S)  # 0..1 suave
        nmax = max(8.0, min(22.0, w * 0.12, h * 0.45))
        n = nmax * 0.5 + nmax * 0.5 * osc  # entre ~50% y 100% de nmax
        cr.set_source_rgba(*TEAL, 0.95)
        cr.set_line_width(2.0)
        for cx, cy, sx, sy in ((2, 2, 1, 1), (w - 2, 2, -1, 1),
                               (2, h - 2, 1, -1), (w - 2, h - 2, -1, -1)):
            cr.move_to(cx, cy + sy * n)
            cr.line_to(cx, cy)
            cr.line_to(cx + sx * n, cy)
            cr.stroke()

        # scanlines tenues
        cr.set_source_rgba(0, 0, 0, 0.06)
        y = 4.0
        while y < h - 2:
            cr.rectangle(3, y, w - 6, 1)
            y += 3
        cr.fill()


def hud_panel(content: Gtk.Widget) -> Gtk.Overlay:
    """Devuelve un Overlay = content + marco HUD animado por encima (transparente al clic)."""
    overlay = Gtk.Overlay()
    overlay.set_child(content)
    frame = HudFrame()
    overlay.add_overlay(frame)
    overlay.set_measure_overlay(frame, False)
    return overlay
