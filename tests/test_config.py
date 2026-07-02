import copy
import json

import nyx.config as config


# --- rutas punteadas ---
def test_get_path_nested_and_default():
    cfg = {"voice": {"tts_enabled": True}}
    assert config.get_path(cfg, "voice.tts_enabled") is True
    assert config.get_path(cfg, "voice.nope", "def") == "def"
    assert config.get_path(cfg, "no.existe") is None
    assert config.get_path(cfg, "voice.tts_enabled.mas") is None  # atravesar no-dict


def test_set_path_creates_intermediates():
    cfg = {}
    config.set_path(cfg, "a.b.c", 7)
    assert cfg == {"a": {"b": {"c": 7}}}
    config.set_path(cfg, "a.b.c", 8)  # sobrescribe
    assert cfg["a"]["b"]["c"] == 8
    config.set_path(cfg, "a.x", True)  # hermano sin perder lo demás
    assert cfg["a"]["b"]["c"] == 8 and cfg["a"]["x"] is True


# --- deep_merge ---
def test_deep_merge_override_wins_and_preserves():
    base = {"ui": {"orb": {"margin_top": 16}, "history": {"width": 320}}}
    over = {"ui": {"orb": {"margin_top": 99}}, "extra": 1}
    out = config.deep_merge(base, over)
    assert out["ui"]["orb"]["margin_top"] == 99
    assert out["ui"]["history"]["width"] == 320  # lo no tocado se conserva
    assert out["extra"] == 1
    assert base["ui"]["orb"]["margin_top"] == 16  # no muta los argumentos


# --- migración v1 (plano) → v2 ---
REAL_FLAT = {
    "tts_enabled": False,
    "tts_sink": "alsa_output.usb-Focusrite_Scarlett_Solo...",
    "tts_backend": "edge",
    "edge_voice": "es-ES-XimenaNeural",
    "gemini_tts_model": "gemini-2.5-flash-preview-tts",
    "gemini_voice": "Kore",
    "gemini_style": "Habla en español de España",
    "voice": "es_MX-claude-high",
    "stt_source": "",
    "stt_model": "small",
    "dbus_notifications": True,
    "dbus_notifications_takeover": False,
}


def test_is_legacy_detection():
    assert config.is_legacy(REAL_FLAT) is True
    assert config.is_legacy({"version": 2, "voice": {}}) is False
    assert config.is_legacy({}) is False  # vacío no es legacy (nada que migrar)
    assert config.is_legacy({"clave_rara": 1}) is False


def test_migrate_maps_and_preserves_unknown():
    flat = dict(REAL_FLAT, clave_desconocida={"x": 1})
    out = config.migrate(flat)
    assert out["version"] == 2
    assert out["voice"]["tts_enabled"] is False
    assert out["voice"]["tts_sink"].startswith("alsa_output")
    assert out["voice"]["voice"] == "es_MX-claude-high"
    assert out["notifications"]["enabled"] is True
    assert out["notifications"]["takeover"] is False
    assert out["clave_desconocida"] == {"x": 1}  # nunca se pierde nada
    assert "tts_enabled" not in out  # las claves planas ya no están arriba


def test_load_migrates_on_disk_with_bak(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(REAL_FLAT), encoding="utf-8")
    eff = config.load(str(p))
    # efectivo: migrado + defaults rellenos
    assert eff["voice"]["voice"] == "es_MX-claude-high"
    assert eff["backend"]["model"] == "sonnet"  # default relleno
    assert eff["ui"]["bubble"]["ttl_ms"] == 12000
    # en disco: v2 + copia .bak del original
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["version"] == 2 and "tts_enabled" not in on_disk
    bak = json.loads((tmp_path / "config.json.bak").read_text(encoding="utf-8"))
    assert bak == REAL_FLAT


def test_load_v2_untouched_and_filled(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"version": 2, "voice": {"tts_enabled": true}}', encoding="utf-8")
    before = p.read_text(encoding="utf-8")
    eff = config.load(str(p))
    assert eff["voice"]["tts_enabled"] is True
    assert eff["voice"]["edge_voice"] == "es-ES-XimenaNeural"  # default relleno
    assert p.read_text(encoding="utf-8") == before  # un v2 no se reescribe
    assert not (tmp_path / "config.json.bak").exists()


def test_load_missing_or_broken_gives_defaults(tmp_path):
    eff = config.load(str(tmp_path / "no-existe.json"))
    assert eff["backend"]["model"] == "sonnet"
    broken = tmp_path / "roto.json"
    broken.write_text("{ni json", encoding="utf-8")
    eff = config.load(str(broken))
    assert eff["notifications"]["enabled"] is False


# --- update (escritura por rutas punteadas) ---
def test_update_creates_and_sets(tmp_path):
    p = tmp_path / "sub" / "config.json"  # ni el dir existe
    eff = config.update({"ui.bubble.margin_top": 200}, str(p))
    assert eff["ui"]["bubble"]["margin_top"] == 200
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk == {"version": 2, "ui": {"bubble": {"margin_top": 200}}}


def test_update_migrates_legacy_first(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(REAL_FLAT), encoding="utf-8")
    config.update({"backend.model": "opus"}, str(p))
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["version"] == 2
    assert on_disk["backend"]["model"] == "opus"
    assert on_disk["voice"]["tts_sink"].startswith("alsa_output")  # migrado, no perdido


def test_update_preserves_other_keys(tmp_path):
    p = tmp_path / "config.json"
    config.update({"voice.tts_enabled": True}, str(p))
    config.update({"notifications.dnd": True}, str(p))
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["voice"]["tts_enabled"] is True
    assert on_disk["notifications"]["dnd"] is True


# --- validate ---
def test_validate_resets_bad_types_never_raises():
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg["voice"]["tts_enabled"] = "yes"  # string donde va bool
    cfg["ui"]["history"]["width"] = "ancho"  # string donde va int
    cfg["backend"] = "sonnet"  # escalar donde va objeto
    warnings = config.validate(cfg)
    assert cfg["voice"]["tts_enabled"] is False
    assert cfg["ui"]["history"]["width"] == 320
    assert cfg["backend"] == {"model": "sonnet"}
    assert len(warnings) == 3


def test_validate_bool_is_not_int():
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg["notifications"]["max_per_minute"] = True  # bool ⊂ int → también inválido
    warnings = config.validate(cfg)
    assert cfg["notifications"]["max_per_minute"] == 6
    assert warnings


def test_validate_clean_config_no_warnings():
    cfg = copy.deepcopy(config.DEFAULTS)
    assert config.validate(cfg) == []


# --- diff_paths (base del op reload) ---
def test_diff_paths_detects_nested_changes():
    old = config.deep_merge(config.DEFAULTS, {})
    new = config.deep_merge(config.DEFAULTS, {})
    config.set_path(new, "ui.bubble.margin_top", 200)
    config.set_path(new, "backend.model", "opus")
    assert config.diff_paths(old, new) == ["backend.model", "ui.bubble.margin_top"]


def test_diff_paths_added_and_removed_keys():
    # una sección entera añadida/quitada se reporta por su raíz (en la práctica el
    # diff corre entre dos configs EFECTIVOS con defaults rellenos → hojas punteadas)
    assert config.diff_paths({}, {"a": {"b": 1}}) == ["a"]
    assert config.diff_paths({"a": {"b": 1}}, {}) == ["a"]
    assert config.diff_paths({"a": {}}, {"a": {"b": 1}}) == ["a.b"]
    assert config.diff_paths({"x": 1}, {"x": 1}) == []


# --- flatten (nyx-ctl config list) ---
def test_flatten_dotted_paths():
    flat = config.flatten({"a": {"b": {"c": 1}}, "d": 2, "vacio": {}})
    assert flat == {"a.b.c": 1, "d": 2, "vacio": {}}
