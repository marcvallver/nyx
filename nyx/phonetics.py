"""Respelling de pronunciación inglesa para la VOZ de Nyx.

Reescribe términos técnicos en inglés con grafía española aproximada para que edge-tts
(voz es-ES "Ximena") los pronuncie decentes — `node` → `nóud`, `stack` → `esták`. Mismo
mecanismo que ya usa `voice._PRONUN` para `Nyx → Niks`.

Por qué respelling y no IPA/SSML: edge-tts NO acepta SSML ni `<phoneme>` (Microsoft lo
bloquea y la librería XML-escapa el texto), así que con esta voz gratis el respelling
grafémico es la única vía. La tilde fija la sílaba tónica (determinista en español).

SOLO afecta a la VOZ: el bocadillo/UI muestra el texto original (ruta `markup.to_pango`,
independiente de `voice._strip_md`). Puro/stdlib → testeable en CI.

REGLA DE ORO: nunca incluir términos que también sean palabras españolas (`red`, `son`,
`set`, `fin`, `van`, `ten`, `char`…) — leería mal el español normal. Solo términos
inequívocamente ingleses. Los respellings son una primera pasada, AJUSTABLES de oído.
"""

from __future__ import annotations

import re

# término inglés (en minúscula) → grafía es-ES aproximada (solo voz). Tilde = sílaba tónica.
RESPELL: dict[str, str] = {
    "node": "nóud",
    "nodes": "nóuds",
    "stack": "esták",
    "hardcoded": "járdcóudid",
    "hardcode": "járdcoud",
    "daemon": "díimon",
    "backend": "bácend",
    "frontend": "fróntend",
    "deploy": "diplói",
    "deployment": "diplóiment",
    "layout": "léiaut",
    "bug": "bag",
    "debug": "díbag",
    "script": "escrípt",
    "host": "jóust",
    "kernel": "kérnel",
    "token": "tóuken",
    "timeout": "táimaut",
    "queue": "kiú",
    "cyberpunk": "saiberpánk",
    "commit": "comít",
    "cache": "caché",
    # --- git / flujo de trabajo ---
    "commits": "comíts",
    "branch": "bránch",
    "rebase": "ribéis",
    "merge": "merch",
    "pull": "pul",
    "request": "ricuést",
    "review": "riviú",
    "reviews": "riviús",
    "release": "rilís",
    "workflow": "guórkflou",
    "workflows": "guórkflous",
    "worktree": "guórktri",
    "worktrees": "guórktris",
    "hook": "juk",
    "hooks": "juks",
    "feature": "fícher",
    "features": "fíchers",
    "backup": "bácap",
    "backups": "bácaps",
    "offsite": "ófsait",
    "gitleaks": "guítliks",
    "github": "guítjab",
    "dotfiles": "dótfails",
    # --- el mundo de Nyx ---
    "mood": "múd",
    "moods": "múds",
    "nudge": "nach",
    "nudges": "náchs",
    "watcher": "guócher",
    "watchers": "guóchers",
    "claude": "clód",
    "anthropic": "anzrópik",
    "sonnet": "sónet",
    "whisper": "guísper",
    "piper": "páiper",
    "pipewire": "páipuáier",
    "gemini": "yémini",
    # --- proyectos y entorno de Marc ---
    # ("pace" NO: es forma de pacer — la app Pace se pronunciará a la española)
    "gymbros": "yímbros",
    "symbyosis": "simbiósis",
    "notebooklm": "nóutbuk éle éme",
    "obsidian": "obsídian",
    "ghostty": "góusti",
    "kitty": "kíti",
    "wayland": "güéiland",
    "klassy": "klási",
    "tailscale": "téilskeil",
    "tailwind": "téilguind",
    "systemd": "sístem dí",
    "wallpaper": "guólpeiper",
    "widget": "guídyet",
    "widgets": "guídyets",
}

# (regex palabra-completa, case-insensitive) → reemplazo. `\b…\b` evita tocar subcadenas
# ("host" dentro de "ghost", "bug" dentro de "debugging" → intactos).
_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE), rep) for term, rep in RESPELL.items()
]


def respell(text: str) -> str:
    """Aplica el respelling de términos ingleses. SOLO para la voz (no para la UI)."""
    for pat, rep in _RULES:
        text = pat.sub(rep, text)
    return text
