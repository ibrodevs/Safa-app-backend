from pathlib import Path


def test_map_editor_keeps_district_creation_separate_from_tariff_setup():
    template = Path(
        "apps/delivery/templates/admin/delivery/marketmaprevision/map_editor.html"
    ).read_text(encoding="utf-8")
    ui = Path(
        "apps/delivery/static/delivery/admin/market_map_editor_ui.js"
    ).read_text(encoding="utf-8")
    collaboration = Path("apps/delivery/map_collaboration.py").read_text(encoding="utf-8")

    assert 'id="market-feature-district-tariff"' not in template
    assert 'data-kind-scope="district"' in template
    assert "После сохранения карты этот район появится" in template
    assert "цену в сомах" in template
    assert "selectedDistrictTariffName" not in ui
    # После создания тарифа backend всё ещё может автоматически прикрепить его
    # к GeoJSON по точному имени района при следующем сохранении карты.
    assert "attach_district_tariff_ids" in collaboration
