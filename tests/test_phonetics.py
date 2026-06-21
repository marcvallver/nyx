"""Tests del respelling de pronunciación inglesa para la voz (nyx/phonetics.py).

Verifican el MECANISMO (sustitución por palabra completa, case-insensitive) y la
SEGURIDAD (no tocar subcadenas ni homógrafos español/inglés), no la calidad fonética
exacta (esa se ajusta de oído)."""

from nyx.phonetics import RESPELL, respell


def test_known_terms_respelled():
    assert respell("el node cayó") == "el nóud cayó"
    assert respell("hardcoded en el stack") == "járdcóudid en el esták"
    assert respell("revisa el daemon y el kernel") == "revisa el díimon y el kérnel"


def test_case_insensitive():
    assert respell("NODE") == "nóud"
    assert respell("Node") == "nóud"
    assert respell("Deploy ahora") == "diplói ahora"


def test_word_boundary_no_substring_match():
    # el término dentro de otra palabra NO se toca (\b…\b)
    assert respell("ghost") == "ghost"          # contiene 'host'
    assert respell("debugging") == "debugging"  # contiene 'debug' y 'bug'
    assert respell("anode") == "anode"          # contiene 'node'


def test_homographs_preserved():
    # palabras que también son español NO deben respellearse
    for s in ("la red está caída", "son las tres", "un set de tenis",
              "el fin del turno", "ten cuidado"):
        assert respell(s) == s


def test_plural_and_singular_distinct():
    assert respell("dos nodes") == "dos nóuds"
    assert respell("un node") == "un nóud"


def test_plain_spanish_untouched():
    assert respell("") == ""
    assert respell("todo en orden, operativo") == "todo en orden, operativo"


def test_no_homograph_in_dictionary():
    # guardarraíl: ningún término del diccionario es una palabra española común
    espanol_comun = {"red", "son", "set", "fin", "van", "ten", "char", "mas", "tan", "pin"}
    assert espanol_comun.isdisjoint(RESPELL.keys())
