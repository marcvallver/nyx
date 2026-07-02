import json

from nyx import chatlog


def test_append_and_load_roundtrip(tmp_path):
    p = str(tmp_path / "chat.jsonl")
    chatlog.append_turn("operativo", "hola", ts=1.0, path=p)
    chatlog.append_turn("Nyx", "hola Marc", mood="glad", ts=2.0, path=p)
    recs = chatlog.load_recent(path=p)
    assert [r["role"] for r in recs] == ["operativo", "Nyx"]
    assert recs[1]["mood"] == "glad" and recs[1]["ts"] == 2.0


def test_load_recent_limits_and_skips_corrupt(tmp_path):
    p = tmp_path / "chat.jsonl"
    lines = [json.dumps({"role": "Nyx", "text": f"t{i}"}) for i in range(10)]
    lines.insert(5, "{esto no es json")
    lines.insert(7, json.dumps({"sin": "role"}))  # válido pero incompleto → se salta
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    recs = chatlog.load_recent(n=4, path=str(p))
    assert len(recs) == 4
    assert recs[-1]["text"] == "t9"


def test_load_recent_missing_file(tmp_path):
    assert chatlog.load_recent(path=str(tmp_path / "no.jsonl")) == []


def test_rotate_trims_only_when_over(tmp_path):
    p = tmp_path / "chat.jsonl"
    p.write_text("\n".join(json.dumps({"role": "Nyx", "text": str(i)})
                           for i in range(30)) + "\n", encoding="utf-8")
    assert chatlog.rotate(path=str(p), max_lines=50, keep=10) is False  # no supera
    assert chatlog.rotate(path=str(p), max_lines=20, keep=10) is True
    recs = chatlog.load_recent(n=100, path=str(p))
    assert len(recs) == 10 and recs[-1]["text"] == "29"  # conserva la cola


def test_archive_moves_thread(tmp_path):
    p = str(tmp_path / "chat.jsonl")
    chatlog.append_turn("Nyx", "hilo viejo", path=p)
    dst = chatlog.archive(path=p)
    assert dst == p + ".old"
    assert chatlog.load_recent(path=p) == []
    assert chatlog.load_recent(path=dst)[0]["text"] == "hilo viejo"
    assert chatlog.archive(path=p) is None  # sin hilo no hay nada que archivar


def test_append_never_raises_on_bad_dir():
    chatlog.append_turn("Nyx", "x", path="/proc/imposible/chat.jsonl")  # no lanza