from pathlib import Path


def test_runtime_pricing_patches_remain_enabled():
    source = Path('apps/delivery/apps.py').read_text()
    assert 'enable_map_pricing()' in source
    assert 'enable_quote_map_pricing()' in source
    assert 'enable_district_per_km_pricing()' in source


def test_nearby_serializer_exposes_both_estimated_and_final_price():
    source = Path('apps/delivery/serializer.py').read_text()
    block = source.split('class ShipmentNearbySerializer', 1)[1]
    assert '"estimated_fare"' in block
    assert '"final_fare"' in block
    assert '"commission"' in block
    assert '"courier_income"' in block
