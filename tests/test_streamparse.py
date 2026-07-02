import pathlib

from nyx.streamparse import (
    AssistantMessage,
    Init,
    MoodSignal,
    RateLimit,
    Result,
    Status,
    StreamParser,
    TextDelta,
    ToolUse,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def test_init_captures_session():
    p = StreamParser()
    sigs = p.feed(
        {
            "type": "system",
            "subtype": "init",
            "session_id": "abc",
            "model": "claude-x",
            "cwd": "/x",
            "tools": ["Bash"],
            "permissionMode": "default",
        }
    )
    assert len(sigs) == 1 and isinstance(sigs[0], Init)
    assert sigs[0].session_id == "abc"
    assert sigs[0].model == "claude-x"
    assert p.session_id == "abc"


def test_text_deltas_accumulate():
    p = StreamParser()
    p.feed({"type": "stream_event", "event": {"type": "message_start"}})
    s1 = p.feed(
        {
            "type": "stream_event",
            "event": {"type": "content_block_delta", "index": 0,
                      "delta": {"type": "text_delta", "text": "Hola "}},
        }
    )
    s2 = p.feed(
        {
            "type": "stream_event",
            "event": {"type": "content_block_delta", "index": 0,
                      "delta": {"type": "text_delta", "text": "mundo"}},
        }
    )
    assert [type(x) for x in s1] == [TextDelta] and s1[0].text == "Hola "
    assert s2[0].text == "mundo"
    assert p.text == "Hola mundo"


def test_tool_use_detected():
    p = StreamParser()
    sigs = p.feed(
        {
            "type": "stream_event",
            "event": {"type": "content_block_start", "index": 0,
                      "content_block": {"type": "tool_use", "name": "Bash", "id": "t1"}},
        }
    )
    assert isinstance(sigs[0], ToolUse) and sigs[0].name == "Bash" and sigs[0].id == "t1"


def test_result_and_reset():
    p = StreamParser()
    p.text = "algo"
    sigs = p.feed(
        {
            "type": "result",
            "subtype": "success",
            "duration_ms": 2504,
            "result": "Hola mundo",
            "total_cost_usd": 0.1,
            "num_turns": 1,
            "session_id": "abc",
        }
    )
    r = sigs[0]
    assert isinstance(r, Result)
    assert r.text == "Hola mundo" and r.duration_ms == 2504 and r.cost_usd == 0.1
    assert p.text == ""  # reset para el siguiente turno


def test_rate_limit_and_status():
    p = StreamParser()
    st = p.feed({"type": "system", "subtype": "status", "status": "requesting"})
    assert isinstance(st[0], Status) and st[0].status == "requesting"
    rl = p.feed(
        {"type": "rate_limit_event",
         "rate_limit_info": {"status": "allowed", "rateLimitType": "five_hour"}}
    )
    assert isinstance(rl[0], RateLimit) and rl[0].info["rateLimitType"] == "five_hour"


def test_assistant_fallback_only_without_deltas():
    p = StreamParser()
    # sin deltas previos -> emite el mensaje completo como fallback
    sigs = p.feed(
        {"type": "assistant",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "hey"}]}}
    )
    assert isinstance(sigs[0], AssistantMessage) and sigs[0].text == "hey"
    # con deltas previos -> NO duplica
    p.text = "ya streameado"
    assert p.feed(
        {"type": "assistant",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "x"}]}}
    ) == []


def test_garbage_lines_ignored():
    p = StreamParser()
    assert p.feed_line("not json") == []
    assert p.feed_line("") == []
    assert p.feed_line("   ") == []


def test_fixture_full_turn():
    p = StreamParser()
    text = ""
    result = None
    got_init = False
    for line in (FIXTURES / "turn.jsonl").read_text().splitlines():
        for sig in p.feed_line(line):
            if isinstance(sig, Init):
                got_init = True
            elif isinstance(sig, TextDelta):
                text += sig.text
            elif isinstance(sig, Result):
                result = sig
    assert got_init
    assert text == "¡Hola! ¿En qué puedo ayudarte hoy?"
    assert result is not None and result.subtype == "success"
    assert result.text == "¡Hola! ¿En qué puedo ayudarte hoy?"
    assert result.duration_ms == 2504


# --- MoodSignal: detección de marcadores ⟨alert⟩ / ⟨heated⟩ ---

def _text_delta(text: str) -> dict:
    return {
        "type": "stream_event",
        "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}},
    }


def _start_msg() -> dict:
    return {"type": "stream_event", "event": {"type": "message_start"}}


def test_mood_alert_emitted_before_text():
    p = StreamParser()
    p.feed(_start_msg())
    sigs = p.feed(_text_delta("⟨alert⟩ Sistema comprometido"))
    assert len(sigs) == 2
    assert isinstance(sigs[0], MoodSignal) and sigs[0].mood == "alert"
    assert isinstance(sigs[1], TextDelta) and sigs[1].text == "Sistema comprometido"


def test_mood_heated_emitted_before_text():
    p = StreamParser()
    p.feed(_start_msg())
    sigs = p.feed(_text_delta("⟨heated⟩Muy bien, si insistes."))
    assert isinstance(sigs[0], MoodSignal) and sigs[0].mood == "heated"
    assert isinstance(sigs[1], TextDelta) and "insistes" in sigs[1].text


def test_no_mood_marker_passes_through():
    p = StreamParser()
    p.feed(_start_msg())
    sigs = p.feed(_text_delta("Todo en orden."))
    assert len(sigs) == 1 and isinstance(sigs[0], TextDelta)
    assert sigs[0].text == "Todo en orden."


def test_mood_marker_split_across_chunks():
    """El marcador puede llegar partido en varios deltas."""
    p = StreamParser()
    p.feed(_start_msg())
    sigs = []
    for chunk in ["⟨", "ale", "rt⟩ ", "texto"]:
        sigs += p.feed(_text_delta(chunk))
    moods = [s for s in sigs if isinstance(s, MoodSignal)]
    texts = [s for s in sigs if isinstance(s, TextDelta)]
    assert len(moods) == 1 and moods[0].mood == "alert"
    assert "texto" in "".join(t.text for t in texts)


def test_mood_marker_consumed_not_shown():
    """El marcador no aparece en el texto resultante."""
    p = StreamParser()
    p.feed(_start_msg())
    sigs = p.feed(_text_delta("⟨alert⟩ Operativo, atención."))
    combined = "".join(s.text for s in sigs if isinstance(s, TextDelta))
    assert "⟨alert⟩" not in combined
    assert "Operativo" in combined


def test_mood_glad_emitted_before_text():
    p = StreamParser()
    p.feed(_start_msg())
    sigs = p.feed(_text_delta("⟨glad⟩ Tests verdes, Marc."))
    assert isinstance(sigs[0], MoodSignal) and sigs[0].mood == "glad"
    assert isinstance(sigs[1], TextDelta) and "verdes" in sigs[1].text


def test_mood_dim_emitted_before_text():
    p = StreamParser()
    p.feed(_start_msg())
    sigs = p.feed(_text_delta("⟨dim⟩El build falló. Sin drama."))
    assert isinstance(sigs[0], MoodSignal) and sigs[0].mood == "dim"
    assert isinstance(sigs[1], TextDelta) and "build" in sigs[1].text


def test_mood_dim_split_across_chunks():
    """⟨dim⟩ es prefijo corto: no debe confundirse llegando partido."""
    p = StreamParser()
    p.feed(_start_msg())
    sigs = []
    for chunk in ["⟨d", "im⟩ ", "apagada"]:
        sigs += p.feed(_text_delta(chunk))
    moods = [s for s in sigs if isinstance(s, MoodSignal)]
    assert len(moods) == 1 and moods[0].mood == "dim"


def test_unknown_angle_bracket_not_consumed():
    """⟨foo⟩ que no es marcador conocido pasa como texto normal."""
    p = StreamParser()
    p.feed(_start_msg())
    sigs = p.feed(_text_delta("⟨foo⟩ hola"))
    assert all(isinstance(s, TextDelta) for s in sigs)
    combined = "".join(s.text for s in sigs)
    assert "⟨foo⟩" in combined


def test_mood_resets_between_turns():
    """Nuevo turno (message_start) resetea la detección de mood."""
    p = StreamParser()
    p.feed(_start_msg())
    p.feed(_text_delta("⟨alert⟩ primera"))
    p.feed(_start_msg())  # nuevo turno
    sigs = p.feed(_text_delta("normal"))
    assert all(isinstance(s, TextDelta) for s in sigs)
