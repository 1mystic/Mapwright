"""The Markdown -> HTML converter behind web/docs.html and web/setup.html."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mdsite", ROOT / "scripts" / "mdsite.py")
mdsite = importlib.util.module_from_spec(spec)
sys.modules["mdsite"] = mdsite
spec.loader.exec_module(mdsite)


def conv(md, **kw):
    return mdsite.convert(md, **kw)[0]


def test_headings_get_slug_ids_and_unique():
    html, heads = mdsite.convert("# A b\n\n## Stopping Mapwright\n\n## Stopping Mapwright\n\n## 1. Install (now)\n")
    assert '<h1 id="a-b">' in html
    assert 'id="stopping-mapwright"' in html and 'id="stopping-mapwright-1"' in html
    assert 'id="1-install-now"' in html
    assert [t for _, t, _ in heads] == ["Stopping Mapwright", "Stopping Mapwright", "1. Install (now)"]


def test_code_block_is_escaped():
    html = conv("```bash\necho '<b>&</b>' | cat\n```\n")
    assert html == '<pre class="code"><code>echo &#x27;&lt;b&gt;&amp;&lt;/b&gt;&#x27; | cat</code></pre>'


def test_inline_escaping_and_formatting():
    html = conv("Use `a|b <x>` and **bold** and *it* <script>alert(1)</script>\n")
    assert "<code>a|b &lt;x&gt;</code>" in html and "<b>bold</b>" in html and "<i>it</i>" in html
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_table_with_escaped_pipes():
    html = conv("| Command | Does |\n|---|---|\n| `a [--x \\| --y]` | one \\| two |\n| b | |\n")
    assert '<div class="tbl"><table>' in html
    assert "<th>Command</th><th>Does</th>" in html
    assert "<td><code>a [--x | --y]</code></td><td>one | two</td>" in html
    assert "<td>b</td><td></td>" in html


def test_lists_and_quote():
    html = conv("1. one\n   more\n2. two\n\n- a\n- b\n\n> note *here*\n")
    assert "<ol><li>one more</li><li>two</li></ol>" in html
    assert "<ul><li>a</li><li>b</li></ul>" in html
    assert '<div class="note">note <i>here</i></div>' in html


def test_link_rewriting():
    f = mdsite.rewrite_href
    assert f("COMMANDS.md#stopping-mapwright") == "docs.html#stopping-mapwright"
    assert f("SETUP.md") == "setup.html"
    assert f("RELEASING.md") == "setup.html"
    assert f("ARCHITECTURE.md") == mdsite.GITHUB + "docs/ARCHITECTURE.md"
    assert f("../README.md") == mdsite.GITHUB + "README.md"
    assert f("https://example.com/x") == "https://example.com/x"
    assert f("#local") == "#local"
    assert 'href="docs.html#x"' in conv("[c](COMMANDS.md#x)")


def test_images_use_site_img_folder():
    assert 'src="img/overview.png"' in conv("![shot](img/overview.png)")


def test_generated_pages_are_current_and_complete(tmp_path):
    (tmp_path / "img").mkdir()
    mdsite.build(tmp_path)
    docs = (tmp_path / "docs.html").read_text()
    setup = (tmp_path / "setup.html").read_text()
    for needle in ("init --local", "web_origins", "Stopping Mapwright", "--apply-ignore", "respect_gitignore", "open [--print]"):
        assert needle in docs
    assert 'id="stopping-mapwright"' in docs and 'class="toc"' in docs
    assert "mapwright-agent" in setup and 'id="deploy"' in setup
    assert 'href="docs.html#stopping-mapwright"' in setup
    # the committed copies match what the Markdown produces
    assert docs == (ROOT / "web" / "docs.html").read_text()
    assert setup == (ROOT / "web" / "setup.html").read_text()
