"""Marco HUD cyberpunk ANIMADO (Cairo): borde teal + corner-brackets que se alargan
y se achican con easing suave + scanlines tenues. Dibujado por encima del contenido
con el centro transparente (no tapa el texto ni roba clics). Da a la barra de entrada
y al bocadillo la misma identidad que la ventanita del avatar.

Solo anima mientras la caja está MAPEADA (visible) → cero CPU cuando está oculta.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import theme  # noqa: E402

TEAL = (0.333, 0.918, 0.831)
RED = (0.773, 0.0, 0.235)    # #c5003c — rojo de selección de Ghostty (mood alert)
AMBER = (1.0, 0.620, 0.0)    # #ff9e00 — ámbar/amarillo de Ghostty (mood heated)
GLAD = (0.973, 0.929, 0.263)  # #f8ed43 — Lemon Yellow, Sanzo Wada #189 (mood glad)
DIM = (0.545, 0.514, 0.357)   # #8b835b — Dark Citrine, Sanzo Wada #41 (mood dim)
MOOD_RGB = {"normal": TEAL, "alert": RED, "heated": AMBER, "glad": GLAD, "dim": DIM}
FPS_MS = 33          # animación de los brackets (~30 fps; basta para un pulso lento)
PERIOD_S = 4.4       # ciclo del alargar/achicar (lento, tipo idle)


def _rrect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class HudTitlebar(Gtk.WindowHandle):
    """Barra de título HUD para las ventanas normales de Nyx (Control, Historial).

    Sustituye la headerbar CSD gris de GTK conservando lo que da KWin/GTK gratis:
    WindowHandle mantiene el drag y el doble-click, y la ventana sigue teniendo
    resize edges. Glifo + título mono con glow y botón × propio, todo teñible
    por el mood (regla: toda superficie se tiñe, salvo que dañe legibilidad).
    """

    def __init__(self, title: str, on_close: Callable[[], None]):
        super().__init__()
        theme.apply_css(theme.TITLEBAR_CSS)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.add_css_class("nyx-titlebar")
        glyph = Gtk.Label(label="✳")
        glyph.add_css_class("nyx-titlebar-glyph")
        lbl = Gtk.Label(label=title, xalign=0.0)
        lbl.add_css_class("nyx-titlebar-title")
        lbl.set_hexpand(True)
        mini = Gtk.Button(label="–")
        mini.connect("clicked", self._on_minimize)
        maxi = Gtk.Button(label="□")
        maxi.connect("clicked", self._on_maximize)
        close = Gtk.Button(label="×")
        close.connect("clicked", lambda *_: on_close())
        box.append(glyph)
        box.append(lbl)
        for btn in (mini, maxi, close):
            btn.add_css_class("nyx-close")
            box.append(btn)
        self.set_child(box)
        self._box = box
        self._fg = (glyph, lbl)
        self._btns = (mini, maxi, close)

    def _on_minimize(self, *_):
        win = self.get_root()
        if isinstance(win, Gtk.Window):
            win.minimize()

    def _on_maximize(self, *_):
        win = self.get_root()
        if isinstance(win, Gtk.Window):
            if win.is_maximized():
                win.unmaximize()
            else:
                win.maximize()

    def set_mood(self, mood: str) -> None:
        for m in theme.MOODS:
            if m == "normal":
                continue
            self._box.remove_css_class(f"nyx-titlebar-{m}")
            for b in self._btns:
                b.remove_css_class(f"nyx-close-{m}")
            for w in self._fg:
                w.remove_css_class(f"nyx-titlebar-fg-{m}")
        if mood != "normal" and mood in theme.MOODS:
            self._box.add_css_class(f"nyx-titlebar-{mood}")
            for b in self._btns:
                b.add_css_class(f"nyx-close-{mood}")
            for w in self._fg:
                w.add_css_class(f"nyx-titlebar-fg-{mood}")


class HudFrame(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_can_target(False)
        self.set_draw_func(self._draw)
        self.frame = 0
        self.color = TEAL  # color unificado del marco (borde + brackets); cambia con el mood
        self._timer: int | None = None
        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)

    def set_mood(self, mood: str) -> None:
        """Tiñe el marco (borde + brackets) con el color unificado del estado."""
        self.color = MOOD_RGB.get(mood, TEAL)
        self.queue_draw()

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
        # borde suave (color del mood)
        _rrect(cr, 1.0, 1.0, w - 2.0, h - 2.0, 9.0)
        cr.set_source_rgba(*self.color, 0.5)
        cr.set_line_width(1.3)
        cr.stroke()

        # corner-brackets: la longitud oscila con coseno (ease-in-out suave)
        t = self.frame * FPS_MS / 1000.0
        osc = 0.5 - 0.5 * math.cos(2 * math.pi * t / PERIOD_S)  # 0..1 suave
        nmax = max(8.0, min(22.0, w * 0.12, h * 0.45))
        n = nmax * 0.5 + nmax * 0.5 * osc  # entre ~50% y 100% de nmax
        cr.set_source_rgba(*self.color, 0.95)
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
