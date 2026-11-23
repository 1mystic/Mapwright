from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "src/mapwright/ui"


def test_system_view_is_wired_as_second_tab():
    js = (UI / "app.js").read_text()
    assert '{ id: "system", title: "System"' in js
    assert 'store.get("active", "overview")' in js  # Overview is the first tab; System second
    assert "systemView(v)" in js and 'sel.kind === "component"' in js


def test_system_view_styles_and_icons_exist():
    css = (UI / "app.css").read_text()
    assert ".sysnode" in css and ".sysmap" in css
    sprite = (UI / "icons.svg").read_text()
    js = (UI / "app.js").read_text()
    for ic in ("user", "eye", "route", "box", "function", "database", "radio", "bolt", "search", "plug", "globe", "cloud", "server", "rotate", "beaker", "graph"):
        assert f'id="{ic}"' in sprite, ic
        assert f'"{ic}"' in js, ic


def test_timelapse_and_savings_markers():
    js = (UI / "app.js").read_text()
    css = (UI / "app.css").read_text()
    for m in ("function timelapse(", "drawSystemMap(", "prefers-reduced-motion", "S.sysPlayer.toggle()", "savingsTip(", "tokens saved"):
        assert m in js, m
    assert ".sysnode.enter" in css and ".sysnode.pulse" in css and ".sysnode.gone" in css and "prefers-reduced-motion" in css


def test_no_native_selects_custom_dropdown_instead():
    js = (UI / "app.js").read_text()
    assert 'el("select"' not in js and "function selectBox(" in js
    assert ".select.dd" in (UI / "app.css").read_text()


def test_layout_rows_cannot_be_pushed_off_screen():
    css = (UI / "app.css").read_text()
    assert "grid-template-rows: 40px minmax(0, 1fr) auto 24px" in css  # a tall panel scrolls instead of growing the row
    assert "height: calc(100vh / var(--z, 1))" in css and '"--z"' in (UI / "app.js").read_text()  # still fits when zoomed
