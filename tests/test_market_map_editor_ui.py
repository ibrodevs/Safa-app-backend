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
        assert "market_map_editor.js' %}?v=20260825-3" in template

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


def test_containers_can_be_rotated_from_both_admin_editors():
    standard = TEMPLATE.read_text(encoding="utf-8")
    panel = (
        ROOT / "admin_panel/templates/admin_panel/map/editor.html"
    ).read_text(encoding="utf-8")
    javascript = EDITOR_JS.read_text(encoding="utf-8")

    for template in (standard, panel):
        assert 'id="market-feature-rotation-deg"' in template
        assert 'data-container-rotate-step="-15"' in template
        assert 'data-container-rotate-step="15"' in template
        for angle in ("0", "90", "180", "270"):
            assert f'data-container-rotate-set="{angle}"' in template

    assert "function containerAxes(rotation)" in javascript
    assert "function ringFromContainerRect(rect)" in javascript
    assert "function containerRectFromRing(ring)" in javascript
    assert "function showContainerRotationHandle(item)" in javascript
    assert "function rotateSelectedContainer(" in javascript
    assert "Потяните, чтобы повернуть контейнер" in javascript
    assert "data-container-rotate-step" in javascript
    assert "data-container-rotate-set" in javascript


def test_rotation_survives_resize_duplicate_and_save():
    javascript = EDITOR_JS.read_text(encoding="utf-8")

    # Прежний редактор сводил контейнер к описанной рамке и терял поворот.
    assert "rectangleFromBounds" not in javascript
    assert "[rectangleFromRing(feature.geometry.coordinates[0])]" not in javascript

    assert "rotation: rect.rotation" in javascript
    assert "feature.properties.rotation = Math.round(normalizeRotation(rect.rotation) * 100) / 100" in javascript
    assert "resizeContainerCoordinates(coordinates, widthM, heightM, rotationDeg = null)" in javascript


def test_rotation_is_built_into_editor_without_patch_layer():
    panel = (
        ROOT / "admin_panel/templates/admin_panel/map/editor.html"
    ).read_text(encoding="utf-8")

    assert "market_map_rotation.js" not in panel
    assert not (ROOT / "apps/delivery/static/delivery/admin/market_map_rotation.js").exists()


def test_duplicate_button_sits_on_top_of_the_inspector():
    """Дублирование — частое действие: кнопка держится наверху и не прыгает."""
    standard = TEMPLATE.read_text(encoding="utf-8")
    panel = (
        ROOT / "admin_panel/templates/admin_panel/map/editor.html"
    ).read_text(encoding="utf-8")
    javascript = EDITOR_JS.read_text(encoding="utf-8")

    for template in (standard, panel):
        header = template.index("market-map-properties-header")
        quick = template.index('class="market-map-quick-actions"')
        actions = template.index("market-map-property-actions")
        duplicate = template.index('id="market-feature-duplicate"')

        # Кнопка стоит в верхнем блоке действий, а не в нижнем.
        assert header < quick < actions
        assert quick < duplicate < actions
        assert template.count('id="market-feature-duplicate"') == 1
        assert template.count('id="market-feature-duplicate-direction"') == 1

    assert "focus({ preventScroll: true })" in javascript
    assert "scroller.scrollTop = scrollTop" in javascript
    assert "duplicateSelectedFeature();" in javascript


def test_group_and_container_color_controls_exist_in_both_editors():
    """Группировка и общий цвет контейнеров доступны в обеих админках."""
    standard = TEMPLATE.read_text(encoding="utf-8")
    panel = (
        ROOT / "admin_panel/templates/admin_panel/map/editor.html"
    ).read_text(encoding="utf-8")
    javascript = EDITOR_JS.read_text(encoding="utf-8")

    for template in (standard, panel):
        for element_id in (
            "market-group-create",
            "market-group-duplicate",
            "market-group-ungroup",
            "market-group-direction",
            "market-group-counter",
            "market-feature-color-all",
        ):
            assert f'id="{element_id}"' in template

    assert "function groupSelectedFeatures()" in javascript
    assert "function duplicateGroupSelection()" in javascript
    assert "function applyContainerColorToAll()" in javascript
    # Ctrl+клик набирает группу, а копия группы сдвигается на её же габариты.
    assert "domEvent.ctrlKey || domEvent.metaKey || domEvent.shiftKey" in javascript
    assert "shiftCoordinates(copy.geometry.coordinates, deltaLon, deltaLat)" in javascript


def test_passage_label_follows_the_line_angle():
    """Вертикальный проход — вертикальная подпись, горизонтальный — горизонтальная."""
    javascript = EDITOR_JS.read_text(encoding="utf-8")

    assert "function passageLabelIcon(" in javascript
    # Метка Google Maps не поворачивается, поэтому текст рисуется SVG-иконкой.
    assert 'transform="rotate(${textAngle.toFixed(1)}' in javascript
    assert "passageLabelIcon(text, passageAngleDegrees(item.feature) ?? 0, color)" in javascript
    # Наклон больше 90° разворачивается, чтобы текст не читался вверх ногами.
    assert "const textAngle = angle > 90 ? angle - 180 : angle;" in javascript


def test_group_selection_and_move_logic():
    """Клик по контейнеру не должен теряться, а группа — двигаться целиком."""
    javascript = EDITOR_JS.read_text(encoding="utf-8")

    # Объект под курсором ищем сами: заливка района не должна перехватывать клик.
    assert "function featureAtLatLng(" in javascript
    assert "const target = featureAtLatLng(event?.latLng) || id;" in javascript
    # Режим выбора: обычный клик набирает группу, Shift держать не нужно.
    assert "if (state.pickMode || (domEvent && (domEvent.ctrlKey" in javascript
    assert "function setPickMode(" in javascript

    # Перетаскивание одного объекта группы двигает всю группу.
    assert javascript.count("beginGroupDrag(feature.id)") == 3
    assert javascript.count("finishGroupDrag(feature.id)") == 3

    # Свойства применяются ко всем участникам группы.
    assert "function applyGroupSharedProperties(" in javascript
    assert "const shared = applyGroupSharedProperties(item);" in javascript


def test_editor_picks_up_ids_assigned_by_the_server():
    """Иначе переименование прохода заводило бы второй проход вместо правки."""
    javascript = EDITOR_JS.read_text(encoding="utf-8")

    assert "function mergeServerIdentity(" in javascript
    assert "mergeServerIdentity(data.geojson);" in javascript
    assert "'passage_id', 'container_id'" in javascript

    for view in ("admin_panel/views/map.py", "apps/delivery/map_admin.py"):
        source = (ROOT / view).read_text(encoding="utf-8")
        assert source.count('"geojson":') >= 2


def test_group_has_a_main_object_that_drives_the_rest():
    """Первый выбранный — главный: от него идут свойства и нумерация."""
    javascript = EDITOR_JS.read_text(encoding="utf-8")
    panel = (
        ROOT / "admin_panel/templates/admin_panel/map/editor.html"
    ).read_text(encoding="utf-8")
    standard = TEMPLATE.read_text(encoding="utf-8")

    for template in (standard, panel):
        assert 'id="market-group-pick"' in template

    assert "function isGroupMain(" in javascript
    assert "function groupMembersOrdered(" in javascript
    assert "function mainSelectionItem(" in javascript
    # Свойства расходятся только от главного объекта группы.
    assert "if (!groupId || !isGroupMain(sourceItem.feature)) return 0;" in javascript
    # Номера контейнеров идут подряд от номера главного.
    assert "function renumberGroupMembers(" in javascript
    assert "group_index: index" in javascript
    # Разгруппировка снимает только принадлежность, данные остаются.
    assert "delete properties.group_index;" in javascript


def test_passage_label_color_can_be_changed():
    javascript = EDITOR_JS.read_text(encoding="utf-8")
    panel = (
        ROOT / "admin_panel/templates/admin_panel/map/editor.html"
    ).read_text(encoding="utf-8")
    standard = TEMPLATE.read_text(encoding="utf-8")

    for template in (standard, panel):
        assert 'id="market-feature-label-color"' in template
        # Поле показывается только для прохода.
        index = template.index('id="market-feature-label-color"')
        assert 'data-kind-scope="passage"' in template[max(0, index - 400):index]

    assert "function labelColorFor(" in javascript
    assert "properties.label_color = labelColorField.value;" in javascript
    # Подпись красится своим цветом, а не цветом линии.
    assert "const color = labelColorFor(item.feature.properties);" in javascript
