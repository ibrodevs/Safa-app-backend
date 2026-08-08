from pathlib import Path


def test_stop_payload_includes_district_field():
    source = Path('apps/delivery/serializer.py').read_text()
    block = source.split('class ShipmentStopReadSerializer', 1)[1].split('MAX_SHIPMENT_STOPS', 1)[0]
    assert 'district = serializers.SerializerMethodField()' in block
    assert '"district"' in block
