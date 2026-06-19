from nyx.voice import _strip_md, split_sentences


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
