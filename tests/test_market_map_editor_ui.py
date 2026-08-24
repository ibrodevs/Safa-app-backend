from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "apps/delivery/templates/admin/delivery/marketmaprevision/map_editor.html"
CSS = ROOT / "apps/delivery/static/delivery/admin/market_map_editor.css"
COMPACT_CSS = ROOT / "apps/delivery/static/delivery/admin/market_map_editor_compact.css"
UI_JS = ROOT / "apps/delivery/static/delivery/admin/market_map_editor_ui.js"
EDITOR_JS = ROOT / "apps/delivery/static/delivery/admin/market_map_editor.js"


def test_map_editor_uses_compact_creation_controls():
    content = TEMPLATE.read_text(encoding="utf-8")

    assert "Создание карты" not in content
    assert "Что хотите создать?" not in content
    assert 'class="market-map-create-panel"' in content
    assert "Нарисовать границу" in content
    assert "Нарисовать район" in content
    assert "Нарисовать проход" in content
    assert "Добавить контейнер" in content
    assert "Свойства объекта" in content
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


def test_container_size_can_be_reduced_in_both_admin_editors():
    standard = TEMPLATE.read_text(encoding="utf-8")
    panel = (
        ROOT / "admin_panel/templates/admin_panel/map/editor.html"
    ).read_text(encoding="utf-8")
    javascript = EDITOR_JS.read_text(encoding="utf-8")

    for template in (standard, panel):
        assert 'data-container-size-step="width" data-delta="-0.5"' in template
        assert 'data-container-size-step="height" data-delta="-0.5"' in template
        assert 'min="0.2" max="100" step="0.1"' in template
        assert "market_map_editor.js' %}?v=20260824-6" in template

    assert "resizeSelectedContainer('width', 0)" in javascript
    assert "resizeSelectedContainer('height', 0)" in javascript
    assert "Math.max(0.2, Math.min(100" in javascript


def test_nested_features_remain_clickable_and_containers_have_visual_handles():
    javascript = EDITOR_JS.read_text(encoding="utf-8")

    assert "zIndex: featureZIndex(properties, selected)" in javascript
    assert "selected ? 1000" not in javascript
    assert "stopMapClickPropagation(event)" in javascript
    assert "function showContainerResizeHandles(item)" in javascript
    assert "Потяните, чтобы изменить размер контейнера" in javascript
    assert "handle.addListener('drag'" in javascript
    assert "syncContainerSizeFields(item.feature.geometry.coordinates)" in javascript


def test_map_editor_prioritizes_map_area_over_properties():
    template = TEMPLATE.read_text(encoding="utf-8")
    compact_css = COMPACT_CSS.read_text(encoding="utf-8")

    assert "market_map_editor_compact.css" in template
    assert "minmax(260px, 285px)" in compact_css
    assert "height: clamp(700px, calc(100vh - 240px), 900px);" in compact_css
    assert ".market-map-properties-card" in compact_css
    assert "min-height: 34px" in compact_css


def test_map_editor_controls_have_predictable_compact_layout():
    compact_css = COMPACT_CSS.read_text(encoding="utf-8")

    assert "repeat(auto-fit, minmax(210px, 1fr))" in compact_css
    assert "grid-template-columns: auto auto minmax(160px, 1fr)" in compact_css
    assert ".market-map-actions" in compact_css
    assert "flex-wrap: nowrap" in compact_css
    assert ".market-map-property-actions" in compact_css
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)" in compact_css
    assert ".market-map-property-actions .market-map-apply-button" in compact_css
    assert "grid-column: 1 / -1" in compact_css


def test_map_editor_compact_controls_remain_responsive():
    compact_css = COMPACT_CSS.read_text(encoding="utf-8")

    assert "@media (max-width: 960px)" in compact_css
    assert "@media (max-width: 680px)" in compact_css
    assert ".market-map-actions" in compact_css
    assert "grid-template-columns: 1fr 1fr" in compact_css
    assert ".market-map-property-actions" in compact_css
    assert "grid-template-columns: 1fr" in compact_css


def test_map_editor_errors_are_shown_in_modal_instead_of_red_status_bar():
    template = TEMPLATE.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    compact_css = COMPACT_CSS.read_text(encoding="utf-8")
    ui_js = UI_JS.read_text(encoding="utf-8")

    assert 'id="market-map-error-modal"' in template
    assert 'id="market-map-error-message"' in template
    assert "market_map_editor_ui.js" in template
    assert "#market-map-status.error { display: none; }" in css
    assert "#market-map-status.error" in compact_css
    assert "display: none !important" in compact_css
    assert "new MutationObserver(syncStatus)" in ui_js
    assert "status.classList.contains('error')" in ui_js
    assert "window.marketMapShowError = showError" in ui_js
    assert "showError(message)" in ui_js


def test_missing_container_passage_is_blocked_with_modal_warning():
    ui_js = UI_JS.read_text(encoding="utf-8")

    assert "#market-feature-apply, #market-map-save, #market-map-publish" in ui_js
    assert "featureKind?.value !== 'container'" in ui_js
    assert "Для контейнера обязательно выберите проход." in ui_js
    assert "event.stopImmediatePropagation()" in ui_js
    assert "showError('Для контейнера обязательно выберите проход.')" in ui_js
