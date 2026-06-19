"""Markdown ligero → Pango markup, para pintar el bocadillo bonito.

Puro (solo stdlib) → testeable en CI. Soporta **negrita**, *cursiva*/_cursiva_ y
`código`. Escapa &<> antes de inyectar tags, así que el resultado siempre es markup
Pango bien formado (los marcadores sin cerrar quedan como texto literal).
"""

from __future__ import annotations

import re
from xml.sax.saxutils import escape

_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_STAR = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_ITALIC_US = re.compile(r"(?<!\w)_([^_\n]+)_(?!\w)")


def to_pango(text: str) -> str:
    s = escape(text)
    s = _CODE.sub(r"<tt>\1</tt>", s)
    s = _BOLD.sub(r"<b>\1</b>", s)
    s = _ITALIC_STAR.sub(r"<i>\1</i>", s)
    s = _ITALIC_US.sub(r"<i>\1</i>", s)
    return s
