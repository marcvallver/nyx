from nyx.voice import (
    TTS_CHUNK_CHARS,
    TtsSpeaker,
    VOICES_DIR,
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
    assert _strip_md("soy **Nyx**") == "soy Nyx"
    assert _strip_md("usa `ls -la`") == "usa ls -la"
    assert _strip_md("# Título") == "Título"
    assert _strip_md("_énfasis_ y *cursiva*") == "énfasis y cursiva"


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
