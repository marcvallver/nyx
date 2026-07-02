"""Configuración unificada de Nyx (~/.config/nyx/config.json, schema v2 anidado).

Única fuente de verdad del config: DEFAULTS anidado por secciones, migración
automática del formato plano legacy (v1) con copia .bak, acceso por rutas
punteadas ("voice.tts_enabled") y escritura ATÓMICA (tmp + os.replace).

Toda la lógica (migrar, mergear, validar, diff) es PURA sobre dicts — testeable
en CI sin tocar disco; el I/O vive solo en load()/update()/_read_raw()/_write().
"""

from __future__ import annotations

import copy
import json
import os
import sys
from typing import Any

CONFIG_PATH = os.path.expanduser("~/.config/nyx/config.json")

DEFAULTS: dict[str, Any] = {
    "version": 2,
    "mood": "normal",
    "backend": {
        "model": "sonnet",  # rápido/barato para chat; opus para tareas pesadas
    },
    "ui": {
        # corner: esquina de reposo (tl/tr/bl/br); los márgenes son relativos a
        # ella (margin_top = eje vertical, margin_right = eje horizontal)
        "orb": {"margin_top": 16, "margin_right": 18, "corner": "tr"},
        "bubble": {"margin_top": 140, "margin_right": 18, "ttl_ms": 12000},
        "inputbar": {"margin_bottom": 220},
        "history": {"width": 320},
    },
    "voice": {
        "tts_enabled": False,
        "tts_backend": "edge",  # edge (gratis) · gemini (HD opt-in) · piper (local)
        "edge_voice": "es-ES-XimenaNeural",
        "tts_sink": "",  # node.name de PipeWire; vacío = default del sistema
        "stt_source": "",
        "stt_model": "",  # vacío = default del worker (small)
        "voice": "",  # .onnx de piper; vacío = DEFAULT_VOICE
        "tts_speaker": "",
        "gemini_tts_model": "gemini-2.5-flash-preview-tts",
        "gemini_voice": "Kore",
        "gemini_style": "",
    },
    "notifications": {
        "enabled": False,  # servidor D-Bus org.freedesktop.Notifications (opt-in)
        "takeover": False,  # reclamar el nombre aunque KDE lo posea
        "dnd": False,
        "max_per_minute": 6,
        "history_size": 500,
        "rules": {},  # {"<app>": "silence"} — se registran igual en el historial
    },
    "terminal_echo": {
        "enabled": True,  # "⌁ sesión <repo>" al terminar un turno de terminal (sin voz)
    },
    "watchers": {},  # proactividad: cada watcher es opt-in (ausente = off)
}

# claves del config plano legacy (v1) → ruta punteada en el schema v2
LEGACY_MAP: dict[str, str] = {
    "tts_enabled": "voice.tts_enabled",
    "tts_backend": "voice.tts_backend",
    "edge_voice": "voice.edge_voice",
    "tts_sink": "voice.tts_sink",
    "stt_source": "voice.stt_source",
    "stt_model": "voice.stt_model",
    "voice": "voice.voice",
    "tts_speaker": "voice.tts_speaker",
    "gemini_tts_model": "voice.gemini_tts_model",
    "gemini_voice": "voice.gemini_voice",
    "gemini_style": "voice.gemini_style",
    "dbus_notifications": "notifications.enabled",
    "dbus_notifications_takeover": "notifications.takeover",
}


# --- lógica pura (sin I/O) ---
def get_path(cfg: dict, path: str, default: Any = None) -> Any:
    """Lectura por ruta punteada: get_path(cfg, "voice.tts_enabled")."""
    node: Any = cfg
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def set_path(cfg: dict, path: str, value: Any) -> None:
    """Escritura por ruta punteada, creando dicts intermedios si faltan."""
    parts = path.split(".")
    node = cfg
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value


def deep_merge(base: dict, override: dict) -> dict:
    """Merge recursivo: `override` gana; las claves de `base` ausentes se conservan.
    Devuelve un dict nuevo (no muta los argumentos)."""
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def is_legacy(raw: dict) -> bool:
    """Un config sin `version` con alguna clave del formato plano es legacy (v1).
    En v1 los valores eran escalares: una clave con valor dict (p.ej. una sección
    `voice` de un v2 sin `version`) NO cuenta como legacy."""
    if not isinstance(raw, dict) or raw.get("version"):
        return False
    return any(k in raw and not isinstance(raw[k], dict) for k in LEGACY_MAP)


def migrate(raw: dict) -> dict:
    """Config plano v1 → schema v2. Las claves desconocidas se conservan tal cual
    (nunca se pierde nada del usuario). Puro: devuelve un dict nuevo."""
    out: dict[str, Any] = {"version": 2}
    for key, value in raw.items():
        if key in LEGACY_MAP and not isinstance(value, dict):
            set_path(out, LEGACY_MAP[key], copy.deepcopy(value))
        else:
            out[key] = copy.deepcopy(value)
    return out


def validate(cfg: dict, defaults: dict | None = None, _prefix: str = "") -> list[str]:
    """Normaliza IN PLACE los tipos de las claves conocidas contra DEFAULTS: un tipo
    incompatible se resetea a su default. Devuelve los avisos; nunca lanza."""
    defaults = DEFAULTS if defaults is None else defaults
    warnings: list[str] = []
    for key, dval in defaults.items():
        if key not in cfg:
            continue
        path = f"{_prefix}{key}"
        cval = cfg[key]
        if isinstance(dval, dict):
            if isinstance(cval, dict):
                warnings += validate(cval, dval, f"{path}.")
            else:
                cfg[key] = copy.deepcopy(dval)
                warnings.append(f"{path}: se esperaba objeto, reseteado a default")
        elif isinstance(dval, bool):
            if not isinstance(cval, bool):
                cfg[key] = dval
                warnings.append(f"{path}: se esperaba bool, reseteado a {dval}")
        elif isinstance(dval, int):
            if isinstance(cval, bool) or not isinstance(cval, int):
                cfg[key] = dval
                warnings.append(f"{path}: se esperaba entero, reseteado a {dval}")
        elif isinstance(dval, str):
            if not isinstance(cval, str):
                cfg[key] = dval
                warnings.append(f"{path}: se esperaba texto, reseteado a {dval!r}")
    return warnings


def diff_paths(old: dict, new: dict, _prefix: str = "") -> list[str]:
    """Rutas punteadas cuyo valor difiere entre dos configs (recursivo, unión de
    claves). Base del op `reload`: decidir qué se aplica en vivo y qué no."""
    changed: list[str] = []
    for key in sorted(set(old) | set(new)):
        path = f"{_prefix}{key}"
        a, b = old.get(key), new.get(key)
        if isinstance(a, dict) and isinstance(b, dict):
            changed += diff_paths(a, b, f"{path}.")
        elif a != b:
            changed.append(path)
    return changed


def flatten(cfg: dict, _prefix: str = "") -> dict[str, Any]:
    """Config anidado → {ruta punteada: valor} (para `nyx-ctl config list`)."""
    out: dict[str, Any] = {}
    for key, value in cfg.items():
        path = f"{_prefix}{key}"
        if isinstance(value, dict) and value:
            out.update(flatten(value, f"{path}."))
        else:
            out[path] = value
    return out


# --- I/O (fino, separado de la lógica) ---
def _read_raw(path: str | None = None) -> dict:
    p = path or CONFIG_PATH
    try:
        with open(p, encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        print(f"nyx: config.json no usable, usando defaults: {e}", file=sys.stderr)
        return {}


def _write(cfg: dict, path: str | None = None) -> None:
    """Escritura atómica (tmp + os.replace): nunca deja el config a medias."""
    p = path or CONFIG_PATH
    tmp = p + ".tmp"
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, p)
    except OSError as e:
        print(f"nyx: no pude guardar config.json: {e}", file=sys.stderr)


def _migrate_on_disk(raw: dict, path: str) -> dict:
    """Migra un config legacy YA LEÍDO: guarda el original como .bak y escribe el v2."""
    try:
        with open(path, encoding="utf-8") as f:
            original = f.read()
        with open(path + ".bak", "w", encoding="utf-8") as f:
            f.write(original)
    except OSError:
        pass  # sin .bak no se aborta la migración: el formato viejo sigue en git/backups
    migrated = migrate(raw)
    _write(migrated, path)
    print("nyx: config.json migrado al schema v2 (copia en config.json.bak)", file=sys.stderr)
    return migrated


def load(path: str | None = None) -> dict:
    """Config EFECTIVO: fichero (migrado a v2 si era plano) sobre DEFAULTS.
    Siempre devuelve un dict completo y con tipos saneados; nunca lanza."""
    p = path or CONFIG_PATH
    raw = _read_raw(p)
    if is_legacy(raw):
        raw = _migrate_on_disk(raw, p)
    effective = deep_merge(DEFAULTS, raw)
    for w in validate(effective):
        print(f"nyx: config: {w}", file=sys.stderr)
    return effective


def update(updates: dict[str, Any], path: str | None = None) -> dict:
    """Aplica {ruta punteada: valor} sobre el FICHERO (no sobre el efectivo) y lo
    reescribe atómicamente. Devuelve el config efectivo resultante."""
    p = path or CONFIG_PATH
    raw = _read_raw(p)
    if is_legacy(raw):
        raw = migrate(raw)
    raw.setdefault("version", 2)
    for key, value in updates.items():
        set_path(raw, key, value)
    _write(raw, p)
    return deep_merge(DEFAULTS, raw)
