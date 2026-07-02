"""Tests de los helpers PUROS de nyx/notifyd.py (sin gi → corren en CI).

Cubren la normalización de los argumentos de `Notify` (org.freedesktop.Notifications)
a un dict estable y la extracción de urgencia desde los hints."""

from nyx.notifyd import (
    capabilities,
    parse_notify,
    server_information,
    urgency_from_hints,
)


def test_parse_notify_normalizes():
    d = parse_notify("Spotify", 0, "icon", "Now playing", "Song — Artist", [], {"urgency": 1}, -1)
    assert d["app"] == "Spotify"
    assert d["summary"] == "Now playing"
    assert d["body"] == "Song — Artist"
    assert d["urgency"] == 1
    assert d["replaces_id"] == 0
    assert d["expire_timeout"] == -1
    assert d["actions"] == []


def test_parse_notify_strips_and_defaults():
    d = parse_notify("  ", 0, "", "  hola  ", "", None, None, None)
    assert d["app"] == ""
    assert d["summary"] == "hola"
    assert d["body"] == ""
    assert d["actions"] == []
    assert d["expire_timeout"] == -1
    assert d["urgency"] == 1  # sin hints → normal


def test_replaces_id_and_timeout_preserved():
    d = parse_notify("app", 7, "", "s", "b", ["default", "Abrir"], {}, 5000)
    assert d["replaces_id"] == 7
    assert d["expire_timeout"] == 5000
    assert d["actions"] == ["default", "Abrir"]


def test_urgency_critical():
    assert urgency_from_hints({"urgency": 2}) == 2


def test_urgency_low():
    assert urgency_from_hints({"urgency": 0}) == 0


def test_urgency_defaults_when_missing_or_invalid():
    assert urgency_from_hints({}) == 1
    assert urgency_from_hints({"urgency": 99}) == 1
    assert urgency_from_hints({"urgency": True}) == 1  # bool no cuenta como urgencia
    assert urgency_from_hints(None) == 1  # robusto ante hints no-dict


def test_capabilities_honest():
    caps = capabilities()
    # anunciamos solo lo que cumplimos: botones de acción en el bocadillo, cuerpo
    # de texto, y persistencia (cola + historial JSONL). HTML markup sigue fuera.
    assert "actions" in caps and "body" in caps and "persistence" in caps
    assert "body-markup" not in caps
    assert caps is not capabilities()  # devuelve copia (no expone la constante)


def test_server_information():
    name, vendor, version, spec = server_information()
    assert name == "Nyx"
    assert vendor == "marc"
    assert spec == "1.2"
