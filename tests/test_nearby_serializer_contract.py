from pathlib import Path


def test_nearby_serializer_contains_unified_display_fields():
    source = Path('apps/delivery/serializer.py').read_text()
    block = source.split('class ShipmentNearbySerializer', 1)[1]
    for field in (
        '"service_type"',
        '"description"',
        '"estimated_fare"',
        '"final_fare"',
        '"commission"',
        '"courier_income"',
        '"stops_count"',
        '"stops"',
    ):
        assert field in block
