"""Avatar de Nyx: una VENTANITA cuadrada translúcida (tile HUD cyberpunk) con el
glifo sparkle dentro, y un EFECTO GLITCH sobre todo el conjunto.

Todo Cairo/CPU (sin GL). El panel (fondo midnight translúcido + borde teal + corner-
brackets + glifo) se dibuja a una superficie offscreen y se compone con:
  - aberración RGB sutil constante (franjas cian/magenta) — shimmer cyberpunk,
  - ráfagas de GLITCH ocasionales (bandas horizontales desplazadas + aberración fuerte),
  - scanlines tenues.
Estados idle/listening/thinking/talking: idle pequeño y calmado, crece y glitchea más
al interactuar. Respeta prefers-reduced-motion (congela, sin glitch). Ventana layer-shell,
click-through.
"""

from __future__ import annotations

import math
import random

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk, Pango, PangoCairo  # noqa: E402
from gi.repository import Gtk4LayerShell as LS  # noqa: E402

from . import sparkle, theme  # noqa: E402

TEAL    = (0.333, 0.918, 0.831)
RED     = (0.773, 0.0,   0.235)  # #c5003c — rojo de selección de la terminal Ghostty (mood alert)
AMBER   = (1.0,   0.620, 0.0)    # #ff9e00 — ámbar/amarillo de la terminal (mood heated)
CYAN    = (0.0, 0.9, 1.0)
MAGENTA = (1.0, 0.15, 0.6)
PANEL_BG = (0.05, 0.08, 0.15)
# Aberración RGB de la textura retro, POR ESTADO, con el color UNIFICADO del mood: reposo = cian+
# magenta (el azul de origen); alert = rojo; heated = ámbar.
_ABERRATION = {
    "alert":  (RED, RED),
    "heated": (AMBER, AMBER),
}

# scale=tamaño del panel · alpha=opacidad · glitch=prob. de ráfaga/frame
# glyph=alpha del glifo · color=tinte del borde/glow (teal normal, rojo alerta, naranja heated)
STATES = {
    "idle":      {"scale": 0.60, "alpha": 0.55, "glitch": 0.012, "glyph": 0.6,  "color": TEAL},
    "listening": {"scale": 0.78, "alpha": 0.85, "glitch": 0.035, "glyph": 0.85, "color": TEAL},
    "thinking":  {"scale": 0.90, "alpha": 0.95, "glitch": 0.060, "glyph": 0.95, "color": TEAL},
    "talking":   {"scale": 1.00, "alpha": 1.00, "glitch": 0.085, "glyph": 1.0,  "color": TEAL},
    "alert":     {"scale": 1.00, "alpha": 1.00, "glitch": 0.15,  "glyph": 1.0,  "color": RED},
    "heated":    {"scale": 0.95, "alpha": 1.00, "glitch": 0.095, "glyph": 1.0,  "color": AMBER},
}
IDLE_GLYPH = "✳"
BRACKET_PERIOD = 4.4  # ciclo lento del alargar/achicar de los corner-brackets


class Orb:
    SIZE = 108
    MAXP = 80  # lado máximo del panel (deja margen para glitch/glow)
    FPS_MS = 16  # ~60 fps

    def __init__(self, app, margin_top: int = 16, margin_right: int = 18):
        w = Gtk.ApplicationWindow(application=app)
        LS.init_for_window(w)
        LS.set_layer(w, LS.Layer.OVERLAY)
        LS.set_anchor(w, LS.Edge.TOP, True)
        LS.set_anchor(w, LS.Edge.RIGHT, True)
        LS.set_margin(w, LS.Edge.TOP, int(margin_top))
        LS.set_margin(w, LS.Edge.RIGHT, int(margin_right))
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
        self.s_scale = STATES["idle"]["scale"]
        self.s_alpha = STATES["idle"]["alpha"]
        self.s_glyph = STATES["idle"]["glyph"]
        self.s_color: tuple = STATES["idle"]["color"]
        self._glitch_frames = 0
        self._timer: int | None = None
        w.set_visible(True)
        self._ensure_timer()

    def _clickthrough(self, *_):
        try:
            surf = self.win.get_surface()
            if surf is not None:
                surf.set_input_region(cairo.Region())
        except Exception:
            pass

    def set_margins(self, margin_top: int, margin_right: int) -> None:
        """Reposiciona el orbe en vivo (op `reload` tras cambiar ui.orb.*)."""
        LS.set_margin(self.win, LS.Edge.TOP, int(margin_top))
        LS.set_margin(self.win, LS.Edge.RIGHT, int(margin_right))

    def _reduced_motion(self) -> bool:
        try:
            return not Gtk.Settings.get_default().get_property("gtk-enable-animations")
        except Exception:
            return False

    def set_state(self, state: str) -> bool:
        if state in STATES and state != self.state:
            self.state = state
            self._ensure_timer()
        return False

    def _ensure_timer(self):
        if self._timer is None:
            self._timer = GLib.timeout_add(self.FPS_MS, self._tick)

    def _settled(self) -> bool:
        t = STATES[self.state]
        tc = t["color"]
        return (abs(self.s_scale - t["scale"]) < 0.004
                and abs(self.s_alpha - t["alpha"]) < 0.004
                and abs(self.s_glyph - t["glyph"]) < 0.01
                and all(abs(self.s_color[i] - tc[i]) < 0.01 for i in range(3)))

    def _tick(self) -> bool:
        self.frame += 1
        t = STATES[self.state]
        k = 0.18
        self.s_scale += (t["scale"] - self.s_scale) * k
        self.s_alpha += (t["alpha"] - self.s_alpha) * k
        self.s_glyph += (t["glyph"] - self.s_glyph) * k
        tc = t["color"]
        kc = 0.10  # transición de color más lenta (más dramática)
        self.s_color = (
            self.s_color[0] + (tc[0] - self.s_color[0]) * kc,
            self.s_color[1] + (tc[1] - self.s_color[1]) * kc,
            self.s_color[2] + (tc[2] - self.s_color[2]) * kc,
        )
        rm = self._reduced_motion()
        if not rm:
            if self._glitch_frames > 0:
                self._glitch_frames -= 1
            elif random.random() < t["glitch"]:
                self._glitch_frames = random.randint(2, 5)
        self.area.queue_draw()
        if rm and self._settled():  # reduced-motion: congelar y parar (cero consumo)
            self._timer = None
            return False
        return True

    def _glyph(self) -> str:
        # sparkle SIEMPRE animado (cadencia real 120 ms), en todos los estados
        idx = (self.frame * self.FPS_MS // sparkle.FRAME_MS) % len(sparkle.FRAMES)
        return sparkle.FRAMES[idx]

    # --- composición ---
    def _draw(self, _area, cr, width, height):
        rm = self._reduced_motion()
        # superficie offscreen con el panel + glifo
        surf = cairo.ImageSurface(cairo.Format.ARGB32, width, height)
        pcr = cairo.Context(surf)
        self._panel(pcr, width, height)
        surf.flush()

        self._glow(cr, width, height)
        glitch = (not rm) and self._glitch_frames > 0
        if glitch:
            self._slice_paint(cr, surf, width, height)
            dx = random.uniform(2.5, 5.5)
            jitter = random.uniform(-1.5, 1.5)
        else:
            cr.set_source_surface(surf, 0, 0)
            cr.paint()
            dx = 0.0 if rm else 0.8
            jitter = 0.0
        if dx > 0:  # franjas de aberración RGB
            cr.save()
            cr.set_operator(cairo.Operator.ADD)
            ab_a, ab_b = _ABERRATION.get(self.state, (CYAN, MAGENTA))
            cr.set_source_rgba(*ab_a, 0.45)
            cr.mask_surface(surf, dx, jitter)
            cr.set_source_rgba(*ab_b, 0.45)
            cr.mask_surface(surf, -dx, -jitter)
            cr.restore()
        self._scanlines(cr, width, height)

    def _panel(self, pcr, w, h):
        ps = self.MAXP * self.s_scale
        a = self.s_alpha
        x = (w - ps) / 2
        y = (h - ps) / 2
        rad = 7 * self.s_scale
        self._rrect(pcr, x, y, ps, ps, rad)
        # relleno del tile teñido sutilmente por el mood (toda la ventanita se entera)
        fill = tuple(PANEL_BG[i] * 0.8 + self.s_color[i] * 0.2 for i in range(3))
        pcr.set_source_rgba(*fill, 0.6 * a)
        pcr.fill()
        self._rrect(pcr, x, y, ps, ps, rad)
        pcr.set_source_rgba(*self.s_color, 0.6 * a)
        pcr.set_line_width(1.2)
        pcr.stroke()
        self._brackets(pcr, x, y, ps, a)
        self._glyph_draw(pcr, w / 2, h / 2, ps, a)

    def _rrect(self, cr, x, y, ww, hh, r):
        cr.new_sub_path()
        cr.arc(x + ww - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + ww - r, y + hh - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + hh - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def _brackets(self, cr, x, y, ps, a):
        # longitud animada: se alarga/achica con coseno (ease-in-out suave), igual que las cajas
        t = self.frame * self.FPS_MS / 1000.0
        osc = 0.5 - 0.5 * math.cos(2 * math.pi * t / BRACKET_PERIOD)
        n = ps * (0.16 + 0.12 * osc)
        cr.set_source_rgba(*self.s_color, 0.95 * a)  # brackets en el color UNIFICADO del mood
        cr.set_line_width(2.0)
        for cx, cy, sx, sy in ((x, y, 1, 1), (x + ps, y, -1, 1),
                               (x, y + ps, 1, -1), (x + ps, y + ps, -1, -1)):
            cr.move_to(cx, cy + sy * n)
            cr.line_to(cx, cy)
            cr.line_to(cx + sx * n, cy)
            cr.stroke()

    def _glyph_draw(self, cr, cx, cy, ps, a):
        font_px = max(8.0, ps * 0.46)
        layout = PangoCairo.create_layout(cr)
        desc = Pango.FontDescription("MesloLGL Nerd Font Mono")
        desc.set_weight(Pango.Weight.BOLD)
        glyph = self._glyph()
        # núcleo brillante teñido por el mood (aclarado hacia blanco) → el sparkle se pone rojo
        core = tuple(self.s_color[i] + (1.0 - self.s_color[i]) * 0.55 for i in range(3))
        for size_mul, color, alpha in ((1.18, self.s_color, self.s_glyph * 0.5 * a),
                                       (1.0, core, self.s_glyph * a)):
            desc.set_absolute_size(font_px * size_mul * Pango.SCALE)
            layout.set_font_description(desc)
            layout.set_text(glyph, -1)
            gw, gh = layout.get_pixel_size()
            cr.set_source_rgba(*color, alpha)
            cr.move_to(cx - gw / 2, cy - gh / 2)
            PangoCairo.show_layout(cr, layout)

    def _glow(self, cr, w, h):
        # glow CONTENIDO dentro del panel (clip a la caja) — sin halo circular por fuera
        ps = self.MAXP * self.s_scale
        x, y = (w - ps) / 2, (h - ps) / 2
        cr.save()
        self._rrect(cr, x, y, ps, ps, 7 * self.s_scale)
        cr.clip()
        cx, cy = w / 2, h / 2
        r = ps * 0.62
        g = cairo.RadialGradient(cx, cy, r * 0.2, cx, cy, r)
        g.add_color_stop_rgba(0, *self.s_color, 0.16 * self.s_alpha)
        g.add_color_stop_rgba(1, *self.s_color, 0.0)
        cr.set_source(g)
        cr.paint()
        cr.restore()

    def _slice_paint(self, cr, surf, w, h):
        n = random.randint(2, 4)
        pop = list(range(10, h - 10))
        bounds = sorted(random.sample(pop, min(n, len(pop)))) if pop else []
        prev = 0
        for yb in bounds + [h]:
            off = random.randint(-6, 6)
            cr.save()
            cr.rectangle(0, prev, w, yb - prev)
            cr.clip()
            cr.set_source_surface(surf, off, 0)
            cr.paint()
            cr.restore()
            prev = yb

    def _scanlines(self, cr, w, h):
        # scanlines SOLO dentro del tile (clip al panel) → mismo tamaño que la ventana de Nyx,
        # sin el cuadrado de rayado que antes sobresalía por el área transparente
        ps = self.MAXP * self.s_scale
        px, py = (w - ps) / 2, (h - ps) / 2
        cr.save()
        self._rrect(cr, px, py, ps, ps, 7 * self.s_scale)
        cr.clip()
        cr.set_source_rgba(0, 0, 0, 0.10)
        yy = py
        while yy < py + ps:
            cr.rectangle(px, yy, ps, 1)
            yy += 3
        cr.fill()
        cr.restore()
