"""Paleta y CSS cyberpunk de Nyx. Las constantes son puras; `apply_css` importa
GTK de forma perezosa para que importar este módulo no requiera display."""

TEAL = "#55ead4"
GLOW_RGB = "85,234,212"
YELLOW = "#f3e600"
# Colores de mood = de la terminal Ghostty (cyberpunk-2077): rojo de selección (alert),
# ámbar/amarillo (heated). Cada mood se aplica UNIFICADO a todas las superficies.
RED = "#c5003c"
RED_RGB = "197,0,60"
AMBER = "#ff9e00"
AMBER_RGB = "255,158,0"
TEXT = "#d6fff7"
MIDNIGHT = "rgba(13,20,38,0.92)"
FONT = '"MesloLGL Nerd Font Mono", "DejaVu Sans Mono", monospace'

BUBBLE_CSS = f"""
window {{ background: transparent; }}
.nyx-box {{
  background: {MIDNIGHT};
  border-radius: 9px;
  padding: 13px 17px;
  box-shadow: 0 8px 28px rgba(0,0,0,0.40), 0 0 14px rgba({GLOW_RGB}, 0.16);
}}
.nyx-box-alert {{
  background: rgba(34,13,28,0.93);  /* navy + ~12% crimson: tinte sutil, sigue oscuro y legible */
  box-shadow: 0 8px 28px rgba(0,0,0,0.50), 0 0 24px rgba({RED_RGB}, 0.62);
}}
.nyx-box-heated {{
  background: rgba(36,28,14,0.93);  /* navy + ~12% ámbar */
  box-shadow: 0 8px 28px rgba(0,0,0,0.50), 0 0 24px rgba({AMBER_RGB}, 0.58);
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
.nyx-close {{
  color: {TEAL};
  opacity: 0.6;
  font-size: 15px;
  min-width: 0;
  min-height: 0;
  padding: 0 2px 2px 6px;
  background: transparent;
  border: none;
  box-shadow: none;
  text-shadow: 0 0 7px rgba({GLOW_RGB}, 0.8);  /* glow en reposo (teal) */
}}
/* rojo más brillante para visibilidad (variante legible del mood, regla de Marc) + glow rojo */
.nyx-close-alert {{ color: #ff2e5f; opacity: 0.95; text-shadow: 0 0 9px rgba({RED_RGB}, 1.0); }}
.nyx-close-heated {{ color: {AMBER}; opacity: 0.95; text-shadow: 0 0 9px rgba({AMBER_RGB}, 0.95); }}
.nyx-close:hover {{ opacity: 1.0; }}
"""


INPUT_CSS = f"""
window {{ background: transparent; }}
.nyx-input-box {{
  background: {MIDNIGHT};
  border-radius: 9px;
  padding: 10px 16px;
  box-shadow: 0 8px 28px rgba(0,0,0,0.40), 0 0 14px rgba({GLOW_RGB}, 0.16);
}}
.nyx-input-box-alert {{
  box-shadow: 0 8px 28px rgba(0,0,0,0.50), 0 0 24px rgba({RED_RGB}, 0.62);
}}
.nyx-input-box-heated {{
  box-shadow: 0 8px 28px rgba(0,0,0,0.50), 0 0 24px rgba({AMBER_RGB}, 0.58);
}}
.nyx-input-glyph {{ font-size: 20px; }}
.nyx-input-entry, .nyx-input-entry > text {{
  background: transparent;
  color: {TEXT};
  font-family: {FONT};
  font-size: 16px;
  border: none;
  box-shadow: none;
  outline: none;
  caret-color: {TEAL};
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
