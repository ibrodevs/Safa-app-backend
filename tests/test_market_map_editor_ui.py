from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "apps/delivery/templates/admin/delivery/marketmaprevision/map_editor.html"
CSS = ROOT / "apps/delivery/static/delivery/admin/market_map_editor.css"
UI_JS = ROOT / "apps/delivery/static/delivery/admin/market_map_editor_ui.js"


def test_map_editor_uses_simple_three_step_workflow():
    content = TEMPLATE.read_text(encoding="utf-8")

    assert "Что хотите создать?" in content
    assert "Нарисуйте объект" in content
    assert "Данные объекта" in content
    assert "Объекты на карте" in content
    assert "<details class=\"market-map-objects-panel\">" in content


def test_map_editor_keeps_existing_javascript_contract_ids():
    content = TEMPLATE.read_text(encoding="utf-8")
    required_ids = (
        "market-map-canvas",
        "market-map-status",
        "market-map-save",
        "market-map-publish",
        "market-map-finish",
        "market-map-cancel",
        "market-feature-list",
        "market-feature-kind",
        "market-feature-name",
        "market-feature-number",
        "market-feature-passage",
        "market-feature-width-m",
        "market-feature-height-m",
        "market-feature-duplicate-direction",
        "market-feature-container",
        "market-feature-title",
        "market-feature-min-zoom",
        "market-feature-stroke-width",
        "market-feature-stroke",
        "market-feature-fill",
        "market-feature-apply",
        "market-feature-duplicate",
        "market-feature-delete",
    )

    for element_id in required_ids:
        assert f'id="{element_id}"' in content


def test_map_editor_errors_are_shown_in_modal_instead_of_red_status_bar():
    template = TEMPLATE.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    ui_js = UI_JS.read_text(encoding="utf-8")

    assert 'id="market-map-error-modal"' in template
    assert 'id="market-map-error-message"' in template
    assert "market_map_editor_ui.js" in template
    assert "#market-map-status.error { display: none; }" in css
    assert "new MutationObserver(syncStatus)" in ui_js
    assert "status.classList.contains('error')" in ui_js
    assert "showError(message)" in ui_js
