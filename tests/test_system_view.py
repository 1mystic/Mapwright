from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "src/mapwright/ui"


def test_system_view_is_wired_as_default_tab():
    js = (UI / "app.js").read_text()
    assert '{ id: "system", title: "System"' in js
    assert 'store.get("active", "system")' in js
    assert "systemView(v)" in js and 'sel.kind === "component"' in js


def test_system_view_styles_and_icons_exist():
    css = (UI / "app.css").read_text()
    assert ".sysnode" in css and ".sysmap" in css
    sprite = (UI / "icons.svg").read_text()
    js = (UI / "app.js").read_text()
    for ic in ("user", "eye", "route", "box", "function", "database", "radio", "bolt", "search", "plug", "globe", "cloud", "server", "rotate", "beaker", "graph"):
        assert f'id="{ic}"' in sprite, ic
        assert f'"{ic}"' in js, ic
