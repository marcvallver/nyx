"""Bocadillo cyberpunk de Nyx: ventana layer-shell (esquina sup-der) con el TEXTO
de la respuesta. El indicador animado es el orbe (avatar.py).

El texto se revela con efecto MÁQUINA DE ESCRIBIR: los deltas llegan en trozos
grandes, pero aquí se acumulan en `_buf` y se muestran carácter a carácter a ritmo
suave (con catch-up si hay backlog), así la caja crece poco a poco en vez de pegar
saltos. Al terminar (y una vez revelado todo) se aplica el markdown y arranca el TTL.
Fade-in/out con Gtk.Revealer.

Interacción: el bocadillo es click-through SALVO el botón × (solo su rectángulo recibe
clics; el resto pasa a la app de debajo). El mood cambia el color del borde vía CSS."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LS  # noqa: E402

from . import hud, markup, theme  # noqa: E402

_VALID_MOODS = theme.MOODS


class Bubble:
    TYPE_MS = 18  # cadencia del tecleo

    def __init__(self, app, margin_top: int = 140, margin_right: int = 18,
                 ttl_ms: int = 12000):
        self.default_ttl = int(ttl_ms)  # TTL por defecto de say/notify (config ui.bubble)
        self.base_mood = "normal"  # mood de reposo (el persistente del daemon)
        self.on_hidden = None  # callback(dismissed: bool) al ocultarse (cola de notifs)
        self._dismissed = False  # True si el ocultado vino del botón × (no del TTL)
        w = Gtk.ApplicationWindow(application=app)
        LS.init_for_window(w)
        LS.set_layer(w, LS.Layer.OVERLAY)
        LS.set_anchor(w, LS.Edge.TOP, True)
        LS.set_anchor(w, LS.Edge.RIGHT, True)
        LS.set_margin(w, LS.Edge.TOP, int(margin_top))
        LS.set_margin(w, LS.Edge.RIGHT, int(margin_right))
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

        self._icon = Gtk.Image()  # icono de app (notificaciones)
        self._icon.set_pixel_size(18)
        self._icon.set_visible(False)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.append(self._icon)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)
        header.append(close_btn)

        self._actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._actions_box.set_visible(False)
        self._actions_box.set_margin_top(6)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        vbox.add_css_class("nyx-box")
        vbox.append(header)
        vbox.append(self.text)
        vbox.append(self._actions_box)
        self._box = vbox
        self._interactive: list[Gtk.Widget] = [close_btn]  # widgets que SÍ reciben clics

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
        w.connect("realize", self._on_realize)

        self.win = w
        self._buf = ""        # texto recibido (objetivo)
        self._shown = 0       # caracteres ya revelados
        self._finalizing = False
        self._ttl = 15000
        self._type_id: int | None = None
        self._fade_id: int | None = None
        self._region_pending = False  # coalescing del recálculo de la región de input
        w.set_visible(False)

    def set_margins(self, margin_top: int, margin_right: int) -> None:
        """Reposiciona el bocadillo en vivo (op `reload` tras cambiar ui.bubble.*)."""
        LS.set_margin(self.win, LS.Edge.TOP, int(margin_top))
        LS.set_margin(self.win, LS.Edge.RIGHT, int(margin_right))

    def set_mood(self, mood: str) -> None:
        """Tiñe todo el bocadillo con el color del mood: glow + borde/brackets HUD + botón ×."""
        for m in _VALID_MOODS:
            if m != "normal":
                self._box.remove_css_class(f"nyx-box-{m}")
                self._close_btn.remove_css_class(f"nyx-close-{m}")
        if mood != "normal" and mood in _VALID_MOODS:
            self._box.add_css_class(f"nyx-box-{mood}")
            self._close_btn.add_css_class(f"nyx-close-{mood}")
        self._hud.set_mood(mood)

    def _show(self) -> None:
        self.win.set_visible(True)
        self.revealer.set_reveal_child(True)
        if self._fade_id is not None:
            GLib.source_remove(self._fade_id)
            self._fade_id = None
        self._schedule_region()

    # --- notificaciones: icono de app + botones de acción ---
    def _set_icon(self, icon: str) -> None:
        icon = (icon or "").strip().removeprefix("file://")
        if icon and os.path.isabs(icon) and os.path.exists(icon):
            self._icon.set_from_file(icon)
            self._icon.set_visible(True)
        elif icon:
            self._icon.set_from_icon_name(icon)  # icon-name temático (spec)
            self._icon.set_visible(True)
        else:
            self._icon.set_visible(False)

    def _set_actions(self, pairs, on_action) -> None:
        while (child := self._actions_box.get_first_child()) is not None:
            self._actions_box.remove(child)
        self._interactive = [self._close_btn]
        for key, label in pairs:
            btn = Gtk.Button(label=label)
            btn.add_css_class("nyx-notif-action")
            if on_action is not None:
                btn.connect("clicked", lambda _w, k=key: on_action(k))
            self._actions_box.append(btn)
            self._interactive.append(btn)
        self._actions_box.set_visible(bool(pairs))
        self._schedule_region()

    def show_notification(self, text: str, ttl_ms: int, mood: str = "normal",
                          icon: str = "", actions=(), on_action=None) -> bool:
        """Notificación con icono y botones de acción (máx 3). Los botones y el ×
        reciben clics; el resto del bocadillo sigue siendo click-through."""
        self.start_stream(mood)
        self._set_icon(icon)
        self._set_actions(actions, on_action)
        self._buf = text
        self.finalize(ttl_ms)
        return False

    def dismiss(self) -> None:
        """Cierre programático equivalente al × (cuenta como dismissed)."""
        self._cancel_and_hide()

    # --- click-through: solo los widgets interactivos (× + botones de acción) reciben
    # clics; el resto pasa de largo ---
    def _on_realize(self, *_) -> None:
        surf = self.win.get_surface()
        if surf is not None:
            try:  # recalcular la región cuando la superficie cambie de tamaño (el texto crece)
                surf.connect("layout", lambda *_a: self._schedule_region())
            except Exception:
                pass
        self._schedule_region()

    def _schedule_region(self) -> None:
        if not self._region_pending:
            self._region_pending = True
            GLib.idle_add(self._update_input_region)

    def _update_input_region(self) -> bool:
        self._region_pending = False
        import cairo

        surf = self.win.get_surface()
        if surf is None:
            return False
        region = cairo.Region()  # vacía = todo click-through (fallback seguro)
        try:
            if self.win.get_visible():
                for widget in self._interactive:  # unión: × + botones de acción visibles
                    if not widget.get_visible():
                        continue
                    ok, r = widget.compute_bounds(self.win)
                    if not ok:
                        continue
                    pad = 4  # margen para que el botón sea fácil de pulsar
                    region.union(cairo.RectangleInt(
                        max(0, int(r.origin.x) - pad), max(0, int(r.origin.y) - pad),
                        int(r.size.width) + 2 * pad, int(r.size.height) + 2 * pad,
                    ))
        except Exception:
            region = cairo.Region()
        try:
            surf.set_input_region(region)
        except Exception:
            pass
        return False

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
        self._set_icon("")  # el chat no hereda el chrome de una notificación previa
        self._set_actions((), None)
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
            self._schedule_region()  # la caja se ensancha al crecer → reubicar la región del ×
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
        self._dismissed = True
        self._hide()

    def _hide(self) -> bool:
        self.revealer.set_reveal_child(False)  # fade-out
        self._fade_id = None
        GLib.timeout_add(220, self._really_hide)
        return False

    def _really_hide(self) -> bool:
        if not self.revealer.get_reveal_child():  # no re-abierto entretanto
            self.win.set_visible(False)
            self.set_mood(self.base_mood)  # reset visual al ocultar (reposo = mood persistente)
            dismissed, self._dismissed = self._dismissed, False
            if self.on_hidden is not None:
                try:  # la cola de notifs decide si hay siguiente que mostrar
                    self.on_hidden(dismissed)
                except Exception:
                    pass
        return False
