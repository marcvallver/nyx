from nyx.moodstate import resolve_orb_state


def test_talking_with_turn_mood_wins():
    assert resolve_orb_state("talking", "alert", False, False, "normal") == "alert"
    assert resolve_orb_state("talking", "glad", True, True, "dim") == "glad"


def test_talking_normal():
    assert resolve_orb_state("talking", "normal", False, False, "normal") == "talking"
    # el mood persistente NO pisa un turno hablando en normal
    assert resolve_orb_state("talking", "normal", False, False, "alert") == "talking"


def test_thinking_and_terminal():
    assert resolve_orb_state("thinking", "normal", False, False, "normal") == "thinking"
    # actividad de terminal cuenta como thinking aunque Nyx esté idle
    assert resolve_orb_state("idle", "normal", True, False, "glad") == "thinking"


def test_listening():
    assert resolve_orb_state("idle", "normal", False, True, "normal") == "listening"
    # escuchar tiene prioridad sobre el mood persistente
    assert resolve_orb_state("idle", "normal", False, True, "dim") == "listening"


def test_persistent_mood_at_rest():
    for mood in ("alert", "heated", "glad", "dim"):
        assert resolve_orb_state("idle", "normal", False, False, mood) == mood


def test_idle_default():
    assert resolve_orb_state("idle", "normal", False, False, "normal") == "idle"
