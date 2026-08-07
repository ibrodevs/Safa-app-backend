from pathlib import Path


def test_map_editor_exposes_district_tariff_selector():
    template = Path(
        "apps/delivery/templates/admin/delivery/marketmaprevision/map_editor.html"
    ).read_text(encoding="utf-8")
    ui = Path(
        "apps/delivery/static/delivery/admin/market_map_editor_ui.js"
    ).read_text(encoding="utf-8")
    admin = Path("apps/delivery/map_admin.py").read_text(encoding="utf-8")

    assert 'id="market-feature-district-tariff"' in template
    assert 'data-kind-scope="district"' in template
    assert '"district_tariffs": district_tariffs' in admin
    assert "selectedDistrictTariffName" in ui
    assert "featureKind?.value === 'district'" in ui
