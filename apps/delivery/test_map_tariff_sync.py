import pytest

from apps.delivery.map_tariff_sync import attach_district_tariff_ids
from apps.delivery.models import DeliveryDistrict


@pytest.mark.django_db
def test_attach_district_tariff_id_by_selected_district_name():
    tariff = DeliveryDistrict.objects.create(name="Северный", fixed_price=180)
    collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "district-1",
                "properties": {"kind": "district", "name": "Северный"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [74.50, 42.90],
                        [74.60, 42.90],
                        [74.60, 42.80],
                        [74.50, 42.80],
                        [74.50, 42.90],
                    ]],
                },
            }
        ],
    }

    result = attach_district_tariff_ids(collection)

    assert result["features"][0]["properties"]["district_tariff_id"] == tariff.id
