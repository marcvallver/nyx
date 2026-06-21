import json

import nyx.voice as voice
from nyx.voice import (
    TTS_CHUNK_CHARS,
    VOICES_DIR,
    TtsSpeaker,
    _resolve_voice,
    _strip_md,
    group_chunks,
    split_sentences,
)


def test_split_complete_sentences():
    sents, rest = split_sentences("Hola Marc. ¿Qué tal? Bien")
    assert sents == ["Hola Marc.", "¿Qué tal?"]
    assert rest.strip() == "Bien"  # resto incompleto (sin terminador)


def test_split_keeps_incomplete():
    sents, rest = split_sentences("texto sin terminar")
    assert sents == []
    assert rest == "texto sin terminar"


def test_split_newline_ends_sentence():
    sents, rest = split_sentences("línea uno\nresto")
    assert sents == ["línea uno"]
    assert rest == "resto"


def test_split_ellipsis_and_exclaim():
    sents, rest = split_sentences("Espera… ¡Listo! y más")
    assert sents == ["Espera…", "¡Listo!"]
    assert rest.strip() == "y más"


def test_strip_markdown_for_speech():
    assert _strip_md("soy **fuerte**") == "soy fuerte"
    assert _strip_md("usa `ls -la`") == "usa ls -la"
    assert _strip_md("# Título") == "Título"
    assert _strip_md("_énfasis_ y *cursiva*") == "énfasis y cursiva"


def test_strip_emojis_and_symbols_for_speech():
    # los emojis/símbolos NO se leen, pero la puntuación normal SÍ se conserva
    assert _strip_md("Hecho 🌙 listo 🎉") == "Hecho listo"
    assert _strip_md("✅ vale ⭐") == "vale"
    assert _strip_md("flecha → y viñeta • fin") == "flecha y viñeta fin"
    assert _strip_md("¿Qué tal, Marc? ¡Genial!") == "¿Qué tal, Marc? ¡Genial!"  # puntuación intacta
    assert _strip_md("espera… y más") == "espera… y más"  # elipsis (terminador) intacto


def test_strip_links_and_lists_for_speech():
    assert _strip_md("mira [esto](http://x)") == "mira esto"
    assert _strip_md("- punto uno") == "punto uno"


def test_pronunciation_respelling_nyx():
    # la voz dice "Niks" (≈ /nɪks/); el bocadillo mantiene "Nyx" (esto es solo para TTS)
    assert _strip_md("Hola, soy **Nyx**.") == "Hola, soy Niks."
    assert _strip_md("nyx en minúsculas") == "Niks en minúsculas"
    assert _strip_md("Onyx no se toca") == "Onyx no se toca"  # \b evita falsos positivos


def test_group_chunks_short_response_waits_for_flush():
    # una respuesta breve NO se trocea en streaming: sale entera (1 sola síntesis = mejor prosodia)
    chunks, rest = group_chunks("Hola Marc. Ya tengo voz. Dime.")
    assert chunks == []
    assert rest == "Hola Marc. Ya tengo voz. Dime."


def test_group_chunks_emits_when_over_threshold():
    long = "Frase de relleno con bastante texto para sumar caracteres. " * 6
    chunks, rest = group_chunks(long)
    assert len(chunks) >= 1
    assert all(len(c) >= TTS_CHUNK_CHARS - 60 for c in chunks)  # tandas grandes


def test_group_chunks_respects_paragraphs():
    chunks, _ = group_chunks("Primer párrafo corto.\n\nSegundo.")
    assert "Primer párrafo corto." in chunks  # \n\n corta aunque sea corto


def test_pad_appends_silence():
    pcm = b"\x01\x02\x03\x04"
    out = TtsSpeaker._pad(pcm, 24000, ms=100)
    assert out.startswith(pcm)
    assert len(out) - len(pcm) == int(24000 * 100 / 1000) * 2  # 100ms s16 mono


def test_resolve_voice_forms():
    assert _resolve_voice("/abs/x.onnx") == "/abs/x.onnx"
    assert _resolve_voice("es_ES-davefx-medium") == f"{VOICES_DIR}/es_ES-davefx-medium.onnx"
    assert _resolve_voice("foo.onnx") == f"{VOICES_DIR}/foo.onnx"


# --- toggle de voz: persistencia (que la decisión de Marc sobreviva al reinicio) ---

def test_save_config_merges_and_preserves(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"voice": "x", "tts_sink": "scarlett"}', encoding="utf-8")
    monkeypatch.setattr(voice, "CONFIG_PATH", str(cfg))
    voice.save_config({"tts_enabled": True})
    out = json.loads(cfg.read_text(encoding="utf-8"))
    assert out["tts_enabled"] is True
    assert out["voice"] == "x" and out["tts_sink"] == "scarlett"  # no pierde otras claves


def test_save_config_creates_missing_file(tmp_path, monkeypatch):
    cfg = tmp_path / "sub" / "config.json"  # ni el dir existe
    monkeypatch.setattr(voice, "CONFIG_PATH", str(cfg))
    voice.save_config({"tts_enabled": False})
    assert json.loads(cfg.read_text(encoding="utf-8"))["tts_enabled"] is False


def test_toggle_flips_and_persists(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(voice, "CONFIG_PATH", str(cfg))
    sp = TtsSpeaker()
    assert sp.enabled is False           # sin config → silenciada por defecto
    assert sp.toggle() is True           # alterna…
    assert json.loads(cfg.read_text())["tts_enabled"] is True   # …y persiste a disco
    assert sp.toggle() is False
    assert json.loads(cfg.read_text())["tts_enabled"] is False


def test_set_enabled_persist_is_opt_in(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(voice, "CONFIG_PATH", str(cfg))
    sp = TtsSpeaker()
    sp.set_enabled(True)                 # persist=False por defecto → no toca disco
    assert not cfg.exists()
    sp.set_enabled(True, persist=True)
    assert json.loads(cfg.read_text())["tts_enabled"] is True
