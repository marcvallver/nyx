from nyx.actions import allowed_subprocess
from nyx.watchers.base import Action, Nudge, NudgeGate, in_quiet_hours


# --- quiet hours ---
def test_quiet_hours_simple_range():
    assert in_quiet_hours("14:00", "13:00", "15:00") is True
    assert in_quiet_hours("12:59", "13:00", "15:00") is False
    assert in_quiet_hours("15:00", "13:00", "15:00") is False  # fin exclusivo


def test_quiet_hours_crossing_midnight():
    assert in_quiet_hours("23:45", "23:30", "08:30") is True
    assert in_quiet_hours("03:00", "23:30", "08:30") is True
    assert in_quiet_hours("08:30", "23:30", "08:30") is False
    assert in_quiet_hours("12:00", "23:30", "08:30") is False


def test_quiet_hours_disabled():
    assert in_quiet_hours("03:00", "", "") is False
    assert in_quiet_hours("03:00", "08:00", "08:00") is False  # start==end → off


# --- NudgeGate ---
def test_gate_once_per_state_key():
    g = NudgeGate()
    assert g.check("kernel:6.19", "normal", now_ts=0, hhmm="12:00") is True
    assert g.check("kernel:6.19", "normal", now_ts=100, hhmm="12:00") is False  # cooldown
    assert g.check("kernel:6.20", "normal", now_ts=100, hhmm="12:00") is True  # estado nuevo


def test_gate_cooldown_expires():
    g = NudgeGate()
    assert g.check("k", "normal", now_ts=0, hhmm="12:00", cooldown_s=60) is True
    assert g.check("k", "normal", now_ts=59, hhmm="12:00", cooldown_s=60) is False
    assert g.check("k", "normal", now_ts=61, hhmm="12:00", cooldown_s=60) is True


def test_gate_quiet_hours_drop_normals_pass_alerts():
    g = NudgeGate(quiet=("23:30", "08:30"))
    assert g.check("a", "normal", now_ts=0, hhmm="02:00") is False
    assert g.check("a", "glad", now_ts=0, hhmm="02:00") is False  # glad también calla
    assert g.check("a", "alert", now_ts=0, hhmm="02:00") is True  # alert pasa
    # el descarte por quiet NO registró la clave: de día vuelve a poder salir
    g2 = NudgeGate(quiet=("23:30", "08:30"))
    g2.check("b", "normal", now_ts=0, hhmm="02:00")
    assert g2.check("b", "normal", now_ts=10, hhmm="12:00") is True


def test_gate_state_roundtrip_and_prune():
    g = NudgeGate()
    g.check("x", "normal", now_ts=1000.0, hhmm="12:00")
    g2 = NudgeGate(state=g.state())
    assert g2.check("x", "normal", now_ts=1001.0, hhmm="12:00") is False  # persistió
    g2.prune(now_ts=1000.0 + 8 * 86400)
    assert g2.state() == {}


# --- allowed_subprocess (doble defensa) ---
def _fake_classify(verdict):
    return lambda cmd: (verdict, "test")


def test_subprocess_deny_always_wins():
    assert allowed_subprocess("faillock --reset", classify=_fake_classify("deny")) is False


def test_subprocess_policy_allow_passes():
    assert allowed_subprocess("git status", classify=_fake_classify("allow")) is True


def test_subprocess_gray_needs_allowlist():
    assert allowed_subprocess("faillock --user marc --reset",
                              classify=_fake_classify("gray")) is True
    assert allowed_subprocess("curl http://x", classify=_fake_classify("gray")) is False
    assert allowed_subprocess("/usr/bin/faillock --reset",
                              classify=_fake_classify("gray")) is True  # ruta absoluta


def test_subprocess_empty_command():
    assert allowed_subprocess("", classify=_fake_classify("allow")) is False


def test_subprocess_real_policy_sanity():
    # con el policy real: sudo es deny duro aunque esté en una allowlist
    assert allowed_subprocess("sudo faillock --reset") is False
    assert allowed_subprocess("faillock --user marc --reset") is True


# --- dataclasses ---
def test_nudge_defaults():
    n = Nudge(key="k", text="t")
    assert n.mood == "normal" and n.action is None and n.cooldown_s is None
    a = Action(label="l", kind="terminal", command="c")
    assert a.cwd == ""