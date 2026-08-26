from __future__ import annotations

import json
from copy import deepcopy

import pytest
from django.urls import reverse

from apps.users.models import User

from apps.delivery.map_collaboration import MapEditConflict, merge_feature_collections
from apps.delivery.map_models import MarketMapRevision
from apps.delivery.models import Bazar, DeliveryDistrict


def _boundary() -> dict:
    return {
        "type": "Feature",
        "id": "bazar-1",
        "properties": {"kind": "bazar", "name": "Тестовый базар"},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [74.60, 42.95],
                [74.70, 42.95],
                [74.70, 42.85],
                [74.60, 42.85],
                [74.60, 42.95],
            ]],
        },
    }


def _district(feature_id: str, name: str, left: float) -> dict:
    right = left + 0.02
    return {
        "type": "Feature",
        "id": feature_id,
        "properties": {"kind": "district", "name": name},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [left, 42.93],
                [right, 42.93],
                [right, 42.90],
                [left, 42.90],
                [left, 42.93],
            ]],
        },
    }


def _collection(*features: dict) -> dict:
    return {"type": "FeatureCollection", "features": list(features)}


def test_three_way_merge_rejects_two_edits_to_same_feature():
    original = _district("district-a", "Район А", 74.61)
    base = _collection(_boundary(), original)
    submitted = deepcopy(base)
    current = deepcopy(base)
    submitted["features"][1]["properties"]["name"] = "Район клиента 1"
    current["features"][1]["properties"]["name"] = "Район клиента 2"

    with pytest.raises(MapEditConflict):
        merge_feature_collections(base=base, submitted=submitted, current=current)


@pytest.mark.django_db
def test_two_editors_keep_independent_districts_and_sync_catalog(client):
    staff = User.objects.create_user(
        phone_number="996700009901",
        password="password",
        first_name="Admin",
        is_staff=True,
    )
    client.force_login(staff)
    bazar = Bazar.objects.create(name="Тестовый базар")
    base = _collection(_boundary())
    MarketMapRevision.objects.create(bazar=bazar, version=1, geojson=base)
    url = reverse("admin_panel:map_save", args=(bazar.pk,))

    first = client.post(
        url,
        data=json.dumps({
            "base_geojson": base,
            "geojson": _collection(_boundary(), _district("district-a", "Район А", 74.61)),
        }),
        content_type="application/json",
    )
    second = client.post(
        url,
        data=json.dumps({
            "base_geojson": base,
            "geojson": _collection(_boundary(), _district("district-b", "Район Б", 74.66)),
        }),
        content_type="application/json",
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["merged"] is True
    saved_districts = {
        feature["properties"]["name"]
        for feature in second.json()["geojson"]["features"]
        if feature["properties"]["kind"] == "district"
    }
    assert saved_districts == {"Район А", "Район Б"}
    assert set(
        DeliveryDistrict.objects.filter(name__in=saved_districts).values_list("name", flat=True)
    ) == saved_districts
    assert all(
        feature["properties"].get("district_tariff_id")
        for feature in second.json()["geojson"]["features"]
        if feature["properties"]["kind"] == "district"
    )


@pytest.mark.django_db
def test_same_object_conflict_returns_409_without_overwrite(client):
    staff = User.objects.create_user(
        phone_number="996700009902",
        password="password",
        first_name="Admin",
        is_staff=True,
    )
    client.force_login(staff)
    bazar = Bazar.objects.create(name="Конфликтный базар")
    district = _district("district-a", "Исходный район", 74.61)
    base = _collection(_boundary(), district)
    revision = MarketMapRevision.objects.create(bazar=bazar, version=1, geojson=base)
    url = reverse("admin_panel:map_save", args=(bazar.pk,))

    first_map = deepcopy(base)
    first_map["features"][1]["properties"]["name"] = "Изменение первого"
    assert client.post(
        url,
        data=json.dumps({"base_geojson": base, "geojson": first_map}),
        content_type="application/json",
    ).status_code == 200

    second_map = deepcopy(base)
    second_map["features"][1]["properties"]["name"] = "Изменение второго"
    conflict = client.post(
        url,
        data=json.dumps({"base_geojson": base, "geojson": second_map}),
        content_type="application/json",
    )

    assert conflict.status_code == 409
    revision.refresh_from_db()
    assert revision.geojson["features"][1]["properties"]["name"] == "Изменение первого"
