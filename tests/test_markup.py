from xml.etree import ElementTree

from nyx.markup import to_pango, to_plain


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


def test_headers_become_bold():
    assert to_pango("# Título") == "<big><b>Título</b></big>"
    assert to_pango("### Sub") == "<b>Sub</b>"
    assert to_pango("#sinespacio") == "#sinespacio"  # sin espacio NO es encabezado


def test_bullets_and_numbered():
    assert to_pango("- uno") == "• uno"
    assert to_pango("* dos") == "• dos"
    assert to_pango("1. tres") == "1. tres"


def test_links_drop_url():
    assert to_pango("ver [docs](https://x.dev/y)") == "ver docs"


def test_strikethrough_and_quote():
    assert to_pango("~~no~~") == "<s>no</s>"
    assert to_pango("> cita") == "<i>cita</i>"


def test_code_fence_block():
    assert to_pango("```\nls -la\n```") == "<tt>ls -la</tt>"


def test_to_pango_always_valid_xml():
    # propiedad: pase lo que pase, el markup resultante es XML/Pango bien formado
    # (no rompe el Label)
    casos = [
        "**a *b _c `d ~~e [f](g # h > - i",
        "<script> & 'quotes' \"x\"",
        "# **Título `con` [link](u)** y 🌙 emoji",
        "- item **bold**\n- otro *it*\n> cita `c`",
        "```\n<b>no es tag</b> & <\n```",
        "texto normal con → flechas y • viñetas",
    ]
    for c in casos:
        ElementTree.fromstring("<r>" + to_pango(c) + "</r>")  # lanza si está mal formado


def test_to_plain_strips_structure():
    assert to_plain("# Título") == "Título"
    assert to_plain("- uno\n- dos") == "uno\ndos"
    assert to_plain("ver [docs](http://x)") == "ver docs"
    assert to_plain("**fuerte** y `code` y ~~tach~~") == "fuerte y code y tach"
    assert to_plain("> cita") == "cita"
    assert to_plain("```\ncodigo\n```").strip() == ""  # los bloques de código no se leen
