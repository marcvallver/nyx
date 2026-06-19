"""Marco HUD cyberpunk reutilizable (Cairo): borde teal + corner-brackets + scanlines
tenues, dibujado POR ENCIMA del contenido con el centro transparente (no tapa el texto
ni roba clics). Da a la barra de entrada y al bocadillo la misma identidad que la
ventanita del avatar."""

from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

TEAL = (0.333, 0.918, 0.831)


def _rrect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _draw_frame(_area, cr, w, h):
    if w < 8 or h < 8:
        return
    # borde teal suave
    _rrect(cr, 1.0, 1.0, w - 2.0, h - 2.0, 9.0)
    cr.set_source_rgba(*TEAL, 0.5)
    cr.set_line_width(1.3)
    cr.stroke()
    # corner-brackets (las L de las esquinas)
    n = max(8.0, min(18.0, w * 0.10, h * 0.42))
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
    """Devuelve un Overlay = content + marco HUD por encima (transparente al clic)."""
    overlay = Gtk.Overlay()
    overlay.set_child(content)
    frame = Gtk.DrawingArea()
    frame.set_can_target(False)
    frame.set_draw_func(_draw_frame)
    overlay.add_overlay(frame)
    overlay.set_measure_overlay(frame, False)
    return overlay
