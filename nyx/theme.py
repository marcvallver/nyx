"""Paleta y CSS cyberpunk de Nyx. Las constantes son puras; `apply_css` importa
GTK de forma perezosa para que importar este módulo no requiera display."""

TEAL = "#55ead4"
GLOW_RGB = "85,234,212"
YELLOW = "#f3e600"
TEXT = "#d6fff7"
MIDNIGHT = "rgba(13,20,38,0.92)"
FONT = '"MesloLGL Nerd Font Mono", "DejaVu Sans Mono", monospace'

BUBBLE_CSS = f"""
window {{ background: transparent; }}
.nyx-box {{
  background: {MIDNIGHT};
  border: 1px solid {TEAL};
  border-radius: 12px;
  padding: 12px 14px;
}}
.nyx-spark {{
  color: {TEAL};
  font-size: 22px;
  font-weight: bold;
  text-shadow: 0 0 6px rgba({GLOW_RGB}, 0.85), 0 0 14px rgba({GLOW_RGB}, 0.4);
}}
.nyx-text {{
  color: {TEXT};
  font-family: {FONT};
  font-size: 14px;
}}
"""


def apply_css(css: str) -> None:
    """Registra `css` a nivel de display (idempotente para clases namespaced nyx-*)."""
    from gi.repository import Gdk, Gtk

    prov = Gtk.CssProvider()
    prov.load_from_string(css)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_USER
    )
