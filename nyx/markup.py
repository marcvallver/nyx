"""Markdown ligero → Pango markup (bocadillo) y → texto plano (voz).

Puro (solo stdlib) → testeable en CI.
- `to_pango`: pinta **negrita**, *cursiva*/_cursiva_, `código`, ~~tachado~~, `# encabezados`,
  `- listas`, `1. listas`, `> citas`, ```bloques``` y [enlaces](url) como **Pango bien formado**
  (escapa &<> antes; los marcadores sin cerrar quedan como texto literal; nunca da markup roto).
- `to_plain`: lo mismo pero devuelve texto LEGIBLE (sin marcas ni estructura) para el TTS.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree
from xml.sax.saxutils import escape

_PLACEHOLDER = re.compile("\x00(\\d+)\x00")

# inline
_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_STRIKE = re.compile(r"~~([^~]+)~~")
_ITALIC_STAR = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_ITALIC_US = re.compile(r"(?<!\w)_([^_\n]+)_(?!\w)")

# bloque (por línea)
_FENCE = re.compile(r"^\s*```")
_H = re.compile(r"^\s{0,3}(#{1,6})\s+(.*\S)\s*$")
_UL = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_OL = re.compile(r"^(\s*)(\d+)\.\s+(.*)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_HR = re.compile(r"^\s*([-*_])\1{2,}\s*$")


def _inline_pango(seg: str) -> str:
    """Inline markdown → Pango sobre un segmento (escapa &<> primero). Los spans de código y
    enlaces se ENMASCARAN con placeholders para que negrita/cursiva no los crucen
    → anidado válido."""
    s = escape(seg)
    stash: list[str] = []

    def _mask(render):
        def _f(m: re.Match) -> str:
            stash.append(render(m))
            return f"\x00{len(stash) - 1}\x00"
        return _f

    s = _CODE.sub(_mask(lambda m: f"<tt>{m.group(1)}</tt>"), s)
    s = _LINK.sub(_mask(lambda m: m.group(1)), s)  # [texto](url) → texto (ya escapado)
    s = _BOLD.sub(r"<b>\1</b>", s)
    s = _STRIKE.sub(r"<s>\1</s>", s)
    s = _ITALIC_STAR.sub(r"<i>\1</i>", s)
    s = _ITALIC_US.sub(r"<i>\1</i>", s)
    return _PLACEHOLDER.sub(lambda m: stash[int(m.group(1))], s)


def to_pango(text: str) -> str:
    """Markdown → Pango markup para el bocadillo. GARANTÍA: nunca devuelve markup mal formado
    (si una entrada patológica entrelazara tags, degrada a texto escapado sin formato)."""
    rendered = _render(text)
    try:
        ElementTree.fromstring(f"<r>{rendered}</r>")  # validación dura (tags balanceados)
    except ElementTree.ParseError:
        return escape(text)
    return rendered


def _render(text: str) -> str:
    out: list[str] = []
    in_code = False
    code: list[str] = []
    for line in text.split("\n"):
        if _FENCE.match(line):
            if in_code:
                out.append("<tt>" + escape("\n".join(code)) + "</tt>")
                code = []
            in_code = not in_code
            continue
        if in_code:
            code.append(line)
            continue
        m = _H.match(line)
        if m:
            inner = _inline_pango(m.group(2))
            out.append(f"<big><b>{inner}</b></big>" if len(m.group(1)) <= 2 else f"<b>{inner}</b>")
            continue
        m = _UL.match(line)
        if m:
            out.append(f"{m.group(1)}• {_inline_pango(m.group(2))}")
            continue
        m = _OL.match(line)
        if m:
            out.append(f"{m.group(1)}{m.group(2)}. {_inline_pango(m.group(3))}")
            continue
        if _HR.match(line):
            out.append("──────────")
            continue
        m = _QUOTE.match(line)
        if m:
            out.append(f"<i>{_inline_pango(m.group(1))}</i>")
            continue
        out.append(_inline_pango(line))
    if in_code:  # bloque de código sin cerrar
        out.append("<tt>" + escape("\n".join(code)) + "</tt>")
    return "\n".join(out)


def to_plain(text: str) -> str:
    """Markdown → texto legible (sin marcas ni estructura), para el TTS."""
    out: list[str] = []
    in_code = False
    for line in text.split("\n"):
        if _FENCE.match(line):
            in_code = not in_code
            continue
        if in_code:
            continue  # no se leen bloques de código en voz
        m = _H.match(line)
        if m:
            out.append(m.group(2))
            continue
        m = _UL.match(line)
        if m:
            out.append(m.group(2))
            continue
        m = _OL.match(line)
        if m:
            out.append(m.group(3))
            continue
        if _HR.match(line):
            continue
        m = _QUOTE.match(line)
        if m:
            out.append(m.group(1))
            continue
        out.append(line)
    s = "\n".join(out)
    s = _LINK.sub(r"\1", s)
    s = _CODE.sub(r"\1", s)
    s = _BOLD.sub(r"\1", s)
    s = _STRIKE.sub(r"\1", s)
    s = _ITALIC_STAR.sub(r"\1", s)
    s = _ITALIC_US.sub(r"\1", s)
    return s
