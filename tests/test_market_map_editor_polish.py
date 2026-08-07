from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "apps/delivery/static/delivery/admin/market_map_editor_compact.css"
UI_JS = ROOT / "apps/delivery/static/delivery/admin/market_map_editor_ui.js"


def test_map_editor_creation_cards_do_not_show_stray_markers():
    css = CSS.read_text(encoding="utf-8")

    assert ".market-map-create-panel .market-kind-section::before" in css
    assert "content: none !important;" in css
    assert "list-style: none !important;" in css


def test_advanced_settings_are_forced_open():
    css = CSS.read_text(encoding="utf-8")
    ui_js = UI_JS.read_text(encoding="utf-8")

    assert "details.market-map-advanced-fields" in ui_js
    assert "details.open = true" in ui_js
    assert "if (!details.open)" in ui_js
    assert "pointer-events: none;" in css
    assert "summary::-webkit-details-marker" in css
    assert "summary::marker" in css
