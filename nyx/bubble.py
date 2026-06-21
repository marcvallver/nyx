"""Bocadillo cyberpunk de Nyx: ventana layer-shell (esquina sup-der) con el TEXTO
de la respuesta. El indicador animado es el orbe (avatar.py).

El texto se revela con efecto MÁQUINA DE ESCRIBIR: los deltas llegan en trozos
grandes, pero aquí se acumulan en `_buf` y se muestran carácter a carácter a ritmo
suave (con catch-up si hay backlog), así la caja crece poco a poco en vez de pegar
saltos. Al terminar (y una vez revelado todo) se aplica el markdown y arranca el TTL.
Fade-in/out con Gtk.Revealer.

Interacción: el bocadillo NO es click-through — el botón × permite cerrarlo
manualmente. El estado emocional (mood) cambia el color del borde vía CSS."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LS  # noqa: E402

from . import hud, markup, theme  # noqa: E402

_VALID_MOODS = ("normal", "alert", "heated")


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

        close_btn = Gtk.Button(label="×")
        close_btn.add_css_class("nyx-close")
        close_btn.set_halign(Gtk.Align.END)
        close_btn.connect("clicked", lambda _: self._cancel_and_hide())
        self._close_btn = close_btn

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)
        header.append(close_btn)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        vbox.add_css_class("nyx-box")
        vbox.append(header)
        vbox.append(self.text)
        self._box = vbox

        self._hud = hud.HudFrame()  # marco animado; recoloreable por mood
        panel = Gtk.Overlay()
        panel.set_child(vbox)
        panel.add_overlay(self._hud)
        panel.set_measure_overlay(self._hud, False)

        self.revealer = Gtk.Revealer()
        self.revealer.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
        self.revealer.set_transition_duration(180)
        self.revealer.set_child(panel)
        w.set_child(self.revealer)

        self.win = w
        self._buf = ""        # texto recibido (objetivo)
        self._shown = 0       # caracteres ya revelados
        self._finalizing = False
        self._ttl = 15000
        self._type_id: int | None = None
        self._fade_id: int | None = None
        w.set_visible(False)

    def set_mood(self, mood: str) -> None:
        """Tiñe todo el bocadillo con el color del mood: glow + borde/brackets HUD + botón ×."""
        for cls in ("nyx-box-alert", "nyx-box-heated"):
            self._box.remove_css_class(cls)
        for cls in ("nyx-close-alert", "nyx-close-heated"):
            self._close_btn.remove_css_class(cls)
        if mood in ("alert", "heated"):
            self._box.add_css_class(f"nyx-box-{mood}")
            self._close_btn.add_css_class(f"nyx-close-{mood}")
        self._hud.set_mood(mood)

    def _show(self) -> None:
        self.win.set_visible(True)
        self.revealer.set_reveal_child(True)
        if self._fade_id is not None:
            GLib.source_remove(self._fade_id)
            self._fade_id = None

    # --- streaming con tecleo ---
    def start_stream(self, mood: str = "normal") -> bool:
        if self._fade_id is not None:  # cancela un TTL pendiente (p.ej. de un cierre manual)
            GLib.source_remove(self._fade_id)
            self._fade_id = None
        self._buf = ""
        self._shown = 0
        self._finalizing = False
        self.text.set_text("")
        self._stop_type()
        self.set_mood(mood)
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

    def show_text(self, text: str, ttl_ms: int = 12000, mood: str = "normal") -> bool:
        self.start_stream(mood)
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

    def _cancel_and_hide(self) -> None:
        """Cierre manual (×): cancela el TTL pendiente —si no, la fuente GLib quedaría
        huérfana y podría ocultar un bocadillo posterior— y oculta ya."""
        if self._fade_id is not None:
            GLib.source_remove(self._fade_id)
            self._fade_id = None
        self._stop_type()
        self._hide()

    def _hide(self) -> bool:
        self.revealer.set_reveal_child(False)  # fade-out
        self._fade_id = None
        GLib.timeout_add(220, self._really_hide)
        return False

    def _really_hide(self) -> bool:
        if not self.revealer.get_reveal_child():  # no re-abierto entretanto
            self.win.set_visible(False)
            self.set_mood("normal")  # reset visual al ocultar
        return False
