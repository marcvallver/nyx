import pathlib

from nyx.transcript import extract_last_assistant_text, last_assistant_text

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def test_picks_last_text_block():
    lines = [
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"uno"}]}}',
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash"}]}}',
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"dos"}]}}',
    ]
    assert extract_last_assistant_text(lines) == "dos"


def test_ignores_thinking_tool_and_user():
    assert (
        last_assistant_text(str(FIXTURES / "transcript.jsonl")) == "Respuesta final ✓"
    )


def test_joins_multiple_text_blocks():
    lines = [
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"a "},{"type":"text","text":"b"}]}}'
    ]
    assert extract_last_assistant_text(lines) == "a b"


def test_no_assistant_returns_none():
    lines = ['{"type":"user","message":{"role":"user","content":[{"type":"text","text":"hey"}]}}']
    assert extract_last_assistant_text(lines) is None


def test_garbage_and_empty_lines_skipped():
    lines = [
        "",
        "no soy json",
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"vale"}]}}',
        "   ",
    ]
    assert extract_last_assistant_text(lines) == "vale"


def test_missing_file_returns_none():
    assert last_assistant_text("/no/existe/transcript.jsonl") is None
