"""Paleta y CSS cyberpunk de Nyx. Las constantes son puras; `apply_css` importa
GTK de forma perezosa para que importar este módulo no requiera display."""

TEAL = "#55ead4"
GLOW_RGB = "85,234,212"
YELLOW = "#f3e600"
# Colores de mood — cada mood se aplica UNIFICADO a todas las superficies.
# alert/heated = de la terminal Ghostty (cyberpunk-2077): rojo de selección y ámbar.
# glad/dim = del diccionario de Sanzo Wada, partiendo de combos donde ya vive el teal:
#   glad = Lemon Yellow (combo #189: Lemon Yellow + Deep Slate Olive + Venice Green≈teal)
#   dim  = Dark Citrine (combo #41: Dark Citrine + Calamine Blue≈teal)
RED = "#c5003c"
RED_RGB = "197,0,60"
AMBER = "#ff9e00"
AMBER_RGB = "255,158,0"
GLAD = "#f8ed43"
GLAD_RGB = "248,237,67"
DIM = "#8b835b"
DIM_RGB = "139,131,91"
TEXT = "#d6fff7"
MIDNIGHT = "rgba(13,20,38,0.92)"
FONT = '"MesloLGL Nerd Font Mono", "DejaVu Sans Mono", monospace'

# la lista canónica de moods (el resto de módulos la importa de aquí)
MOODS = ("normal", "alert", "heated", "glad", "dim")

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
.nyx-box-glad {{
  background: rgba(30,38,28,0.93);  /* navy + Deep Slate Olive (compañero Wada del lemon) */
  box-shadow: 0 8px 28px rgba(0,0,0,0.45), 0 0 22px rgba({GLAD_RGB}, 0.45);
}}
.nyx-box-dim {{
  background: rgba(22,24,22,0.93);  /* apagado: casi sin tinte, glow mínimo */
  box-shadow: 0 8px 28px rgba(0,0,0,0.50), 0 0 10px rgba({DIM_RGB}, 0.25);
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
.nyx-close-glad {{ color: {GLAD}; opacity: 0.95; text-shadow: 0 0 9px rgba({GLAD_RGB}, 0.9); }}
.nyx-close-dim {{ color: {DIM}; opacity: 0.8; text-shadow: 0 0 6px rgba({DIM_RGB}, 0.6); }}
.nyx-close:hover {{ opacity: 1.0; }}
.nyx-notif-action {{
  background: rgba({GLOW_RGB}, 0.08);
  color: {TEAL};
  font-family: {FONT};
  font-size: 12px;
  border: 1px solid rgba({GLOW_RGB}, 0.45);
  border-radius: 6px;
  padding: 2px 10px;
  min-height: 0;
  box-shadow: none;
}}
.nyx-notif-action:hover {{ background: rgba({GLOW_RGB}, 0.20); }}
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
.nyx-input-box-glad {{
  box-shadow: 0 8px 28px rgba(0,0,0,0.45), 0 0 22px rgba({GLAD_RGB}, 0.45);
}}
.nyx-input-box-dim {{
  box-shadow: 0 8px 28px rgba(0,0,0,0.50), 0 0 10px rgba({DIM_RGB}, 0.25);
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


TITLEBAR_CSS = f"""
/* misma shape que Klassy (WindowCornerRadius=8 en klassyrc): la skin Nyx debe
   casar con las ventanas del sistema. Los brackets del HudFrame van con inset
   extra en el panel para que el clip redondeado no los corte. */
window.nyx-win, window.nyx-win decoration {{ border-radius: 8px; }}
/* el FONDO vive aquí (los paneles internos van transparent para no acumular
   alpha): 0.92 = la opacidad de kitty, el nivel de las ventanas del sistema.
   La titlebar queda opaca como Klassy (ActiveTitleBarOpacity=100). */
window.nyx-win {{ background: rgba(10,15,30,0.92); }}
.nyx-titlebar {{
  background: #090e1b;
  border-bottom: 1px solid rgba({GLOW_RGB}, 0.35);
  padding: 6px 12px;
}}
.nyx-titlebar-alert  {{ border-bottom-color: rgba({RED_RGB}, 0.65); }}
.nyx-titlebar-heated {{ border-bottom-color: rgba({AMBER_RGB}, 0.60); }}
.nyx-titlebar-glad   {{ border-bottom-color: rgba({GLAD_RGB}, 0.55); }}
.nyx-titlebar-dim    {{ border-bottom-color: rgba({DIM_RGB}, 0.45); }}
.nyx-titlebar-glyph {{
  color: {TEAL};
  font-size: 13px;
  text-shadow: 0 0 7px rgba({GLOW_RGB}, 0.8);
}}
.nyx-titlebar-title {{
  color: {TEAL};
  font-family: "Orbitron", {FONT};  /* Orbitron (OFL): el toque cyberpunk del título */
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 3px;
  padding: 2px 0;  /* aire vertical: sin esto el glow recorta el tope de las letras */
  text-shadow: 0 0 8px rgba({GLOW_RGB}, 0.6);
}}
.nyx-tb-btn {{ padding: 3px 7px; }}  /* área clicable generosa, como Klassy */
/* el mood tiñe glifo + título (mismas variantes legibles que .nyx-close) */
.nyx-titlebar-fg-alert  {{ color: #ff2e5f; text-shadow: 0 0 8px rgba({RED_RGB}, 0.9); }}
.nyx-titlebar-fg-heated {{ color: {AMBER}; text-shadow: 0 0 8px rgba({AMBER_RGB}, 0.85); }}
.nyx-titlebar-fg-glad   {{ color: {GLAD}; text-shadow: 0 0 8px rgba({GLAD_RGB}, 0.8); }}
.nyx-titlebar-fg-dim    {{ color: {DIM}; text-shadow: 0 0 6px rgba({DIM_RGB}, 0.5); }}
"""


def apply_css(css: str) -> None:
    """Registra `css` a nivel de display (idempotente para clases namespaced nyx-*)."""
    from gi.repository import Gdk, Gtk

    prov = Gtk.CssProvider()
    prov.load_from_string(css)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_USER
    )
