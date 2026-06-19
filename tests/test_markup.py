from nyx.markup import to_pango


def test_bold():
    assert to_pango("soy **Nyx**") == "soy <b>Nyx</b>"


def test_italic_and_code():
    assert to_pango("usa *esto* y `ls -la`") == "usa <i>esto</i> y <tt>ls -la</tt>"
    assert to_pango("_eso_ también") == "<i>eso</i> también"


def test_escapes_html_first():
    assert to_pango("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_bold_not_eaten_by_italic():
    assert to_pango("**fuerte**") == "<b>fuerte</b>"


def test_unbalanced_stays_literal():
    # un marcador sin cerrar no debe romper el markup
    out = to_pango("incompleto **a y *b")
    assert "<b>" not in out and "<i>" not in out
    assert "**a" in out and "*b" in out


def test_underscore_inside_word_not_italic():
    assert to_pango("nombre_de_variable") == "nombre_de_variable"
