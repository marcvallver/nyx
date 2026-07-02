
from nyx import notifqueue
from nyx.notifqueue import SHOW, SILENCE, NotifQueue, classify


def _n(app="app", urgency=1, nid=0, summary="s"):
    return {"id": nid, "app": app, "summary": summary, "body": "", "urgency": urgency}


# --- classify ---
def test_classify_default_show():
    assert classify(_n()) == SHOW


def test_classify_dnd_silences_except_critical():
    assert classify(_n(urgency=1), dnd=True) == SILENCE
    assert classify(_n(urgency=0), dnd=True) == SILENCE
    assert classify(_n(urgency=2), dnd=True) == SHOW  # crítica salta el DND


def test_classify_rules_per_app():
    rules = {"Spotify": "silence"}
    assert classify(_n(app="Spotify"), rules) == SILENCE
    assert classify(_n(app="Firefox"), rules) == SHOW
    assert classify(_n(app="Spotify", urgency=2), rules) == SHOW  # crítica gana


# --- cola ---
def test_fifo_and_show_counting():
    q = NotifQueue(max_per_minute=10)
    q.push(_n(summary="a"), now=0)
    q.push(_n(summary="b"), now=1)
    assert q.next(now=2)["summary"] == "a"
    assert q.next(now=3)["summary"] == "b"
    assert q.next(now=4) is None


def test_critical_jumps_queue():
    q = NotifQueue()
    q.push(_n(summary="normal"), now=0)
    q.push(_n(summary="critica", urgency=2), now=1)
    assert q.next(now=2)["summary"] == "critica"


def test_replaces_id_updates_pending():
    q = NotifQueue()
    q.push(_n(nid=7, summary="v1"), now=0)
    assert q.push(_n(nid=7, summary="v2"), now=1) == "replaced"
    item = q.next(now=2)
    assert item["summary"] == "v2"
    assert q.next(now=3) is None  # no se duplicó


def test_rate_limit_collapses_into_summary():
    q = NotifQueue(max_per_minute=2)
    for i in range(2):  # dos shows agotan la ventana
        q.push(_n(summary=f"s{i}"), now=i)
        q.next(now=i)
    assert q.push(_n(app="Spam", summary="x"), now=3) == "collapsed"
    assert q.push(_n(app="Spam", summary="y"), now=4) == "collapsed"
    # pasada la ventana, sale el resumen sintético
    item = q.next(now=120)
    assert item["synthetic"] is True
    assert "+2 de Spam" in item["body"]
    assert q.next(now=121) is None


def test_rate_limit_critical_not_collapsed():
    q = NotifQueue(max_per_minute=1)
    q.push(_n(summary="a"), now=0)
    q.next(now=0)
    assert q.push(_n(urgency=2, summary="crit"), now=1) == "queued"
    assert q.next(now=2)["summary"] == "crit"


def test_window_expires():
    q = NotifQueue(max_per_minute=1)
    q.push(_n(summary="a"), now=0)
    q.next(now=0)
    assert q.push(_n(summary="b"), now=61) == "queued"  # ventana de 60 s pasada


def test_queue_cap_drops_lowest_urgency():
    q = NotifQueue(max_per_minute=100, max_queue=2)
    q.push(_n(summary="baja", urgency=0), now=0)
    q.push(_n(summary="media1"), now=1)
    q.push(_n(summary="media2"), now=2)  # cola llena → cae "baja"
    shown = [q.next(now=3)["summary"], q.next(now=4)["summary"]]
    assert shown == ["media1", "media2"]


def test_pending_count():
    q = NotifQueue(max_per_minute=1)
    q.push(_n(), now=0)
    q.next(now=0)
    q.push(_n(app="X"), now=1)  # collapsed
    q.push(_n(app="Y", urgency=2), now=2)  # queued (crítica)
    assert q.pending_count() == 2


# --- historial persistente ---
def test_log_and_load_roundtrip(tmp_path):
    p = str(tmp_path / "notifs.jsonl")
    notifqueue.log_notification(_n(app="A", summary="hola"), shown=True, ts=1.0, path=p)
    notifqueue.log_notification(_n(app="B", summary="shh"), shown=False, ts=2.0, path=p)
    recs = notifqueue.load_recent(path=p)
    assert len(recs) == 2
    assert recs[0]["app"] == "A" and recs[0]["shown"] is True
    assert recs[1]["shown"] is False


def test_load_recent_skips_corrupt(tmp_path):
    p = tmp_path / "notifs.jsonl"
    p.write_text('{"summary":"ok","app":"A"}\n{roto\n', encoding="utf-8")
    recs = notifqueue.load_recent(path=str(p))
    assert len(recs) == 1 and recs[0]["summary"] == "ok"


def test_log_never_raises():
    notifqueue.log_notification(_n(), shown=True, path="/proc/imposible/x.jsonl")