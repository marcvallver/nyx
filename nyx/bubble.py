"""Bocadillo cyberpunk de Nyx: ventana layer-shell (esquina sup-der, click-through)
con el TEXTO de la respuesta. El indicador animado es el orbe (avatar.py).

El texto se revela con efecto MÁQUINA DE ESCRIBIR: los deltas llegan en trozos
grandes, pero aquí se acumulan en `_buf` y se muestran carácter a carácter a ritmo
suave (con catch-up si hay backlog), así la caja crece poco a poco en vez de pegar
saltos. Al terminar (y una vez revelado todo) se aplica el markdown y arranca el TTL.
Fade-in/out con Gtk.Revealer."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk, Gtk4LayerShell as LS  # noqa: E402

from . import hud, markup, theme  # noqa: E402


class Bubble:
    TYPE_MS = 18  # cadencia del tecleo

    def __init__(self, app):
        w = Gtk.ApplicationWindow(application=app)
        LS.init_for_window(w)
        LS.set_layer(w, LS.Layer.OVERLAY)
        LS.set_anchor(w, LS.Edge.TOP, True)
        LS.set_anchor(w, LS.Edge.RIGHT, True)
        LS.set_margin(w, LS.Edge.TOP, 140)
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
        self.revealer.set_child(hud.hud_panel(box))
        w.set_child(self.revealer)
        w.connect("realize", self._clickthrough)

        self.win = w
        self._buf = ""        # texto recibido (objetivo)
        self._shown = 0       # caracteres ya revelados
        self._finalizing = False
        self._ttl = 15000
        self._type_id: int | None = None
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

    def _show(self) -> None:
        self.win.set_visible(True)
        self.revealer.set_reveal_child(True)
        if self._fade_id is not None:
            GLib.source_remove(self._fade_id)
            self._fade_id = None

    # --- streaming con tecleo ---
    def start_stream(self) -> bool:
        self._buf = ""
        self._shown = 0
        self._finalizing = False
        self.text.set_text("")
        self._stop_type()
        return False  # usable como callback de GLib.idle_add

    def append(self, chunk: str) -> None:
        self._buf += chunk
        if self._buf.strip() and not self.win.get_visible():
            self._show()  # primer texto -> aparece la caja
        self._ensure_type()

    def finalize(self, ttl_ms: int = 15000) -> None:
        if not self._buf.strip():
            return  # nada que renderizar -> no dibujamos caja vacía
        if not self.win.get_visible():
            self._show()
        self._ttl = ttl_ms
        self._finalizing = True
        self._ensure_type()  # teclea lo que falte y, al alcanzar el final, aplica markdown + TTL

    def show_text(self, text: str, ttl_ms: int = 12000) -> bool:
        self.start_stream()
        self._buf = text
        self.finalize(ttl_ms)
        return False

    def _ensure_type(self) -> None:
        if self._type_id is None:
            self._type_id = GLib.timeout_add(self.TYPE_MS, self._type)

    def _stop_type(self) -> None:
        if self._type_id is not None:
            GLib.source_remove(self._type_id)
            self._type_id = None

    def _type(self) -> bool:
        if self._shown < len(self._buf):
            remaining = len(self._buf) - self._shown
            self._shown += max(1, min(4, remaining // 12))  # catch-up suave si hay backlog
            self.text.set_text(self._buf[: self._shown])
            return True
        # alcanzado todo lo recibido
        if self._finalizing:
            try:
                self.text.set_markup(markup.to_pango(self._buf))  # markdown bonito al cerrar
            except Exception:
                self.text.set_text(self._buf)
            if self._fade_id is not None:
                GLib.source_remove(self._fade_id)
            self._fade_id = GLib.timeout_add(self._ttl, self._hide)
            self._finalizing = False
        self._type_id = None
        return False  # se reanuda solo al llegar más texto (append)

    def _hide(self) -> bool:
        self.revealer.set_reveal_child(False)  # fade-out
        self._fade_id = None
        GLib.timeout_add(220, self._really_hide)
        return False

    def _really_hide(self) -> bool:
        if not self.revealer.get_reveal_child():  # no re-abierto entretanto
            self.win.set_visible(False)
        return False
