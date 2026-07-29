import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.delivery.map_models import MarketMapRevision
from apps.delivery.map_validation import validate_feature_collection
from apps.delivery.models import Bazar, Container, Passage
from apps.users.models import User


def polygon_feature(bazar_id: int):
    return {
        "type": "Feature",
        "id": f"bazar-{bazar_id}",
        "properties": {
            "kind": "bazar",
            "name": "Дордой",
            "min_zoom": 10,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [74.60, 42.95],
                [74.65, 42.95],
                [74.65, 42.90],
                [74.60, 42.90],
                [74.60, 42.95],
            ]],
        },
    }


def container_feature(bazar_id: int, passage_id: int, container_id: int):
    return {
        "type": "Feature",
        "id": f"container-{container_id}",
        "properties": {
            "kind": "container",
            "name": "Контейнер 101",
            "number": "101",
            "bazar_id": bazar_id,
            "passage_id": passage_id,
            "container_id": container_id,
            "min_zoom": 17,
        },
        "geometry": {
            "type": "Point",
            "coordinates": [74.623, 42.941],
        },
    }


def line_feature(kind: str, name: str):
    return {
        "type": "Feature",
        "id": f"{kind}-1",
        "properties": {"kind": kind, "name": name},
        "geometry": {
            "type": "LineString",
            "coordinates": [[74.61, 42.93], [74.62, 42.94]],
        },
    }


def zone_feature(kind: str, name: str):
    feature = polygon_feature(1)
    feature["id"] = f"{kind}-1"
    feature["properties"] = {"kind": kind, "name": name}
    return feature


def test_map_kinds_receive_unique_default_styles():
    collection = validate_feature_collection(
        {
            "type": "FeatureCollection",
            "features": [
                polygon_feature(1),
                zone_feature("district", "Район A"),
                zone_feature("sector", "Сектор 1"),
                line_feature("row", "Ряд 7"),
                line_feature("passage", "Проход 4"),
                {
                    **container_feature(1, 1, 1),
                    "properties": {
                        "kind": "container",
                        "name": "Контейнер 101",
                        "number": "101",
                    },
                },
            ],
        }
    )

    by_kind = {feature["properties"]["kind"]: feature["properties"] for feature in collection["features"]}

    assert by_kind["bazar"]["stroke_color"] == "#ff6b35"
    assert by_kind["district"]["stroke_color"] == "#2563eb"
    assert by_kind["sector"]["stroke_color"] == "#16a34a"
    assert by_kind["row"]["line_pattern"] == "dashed"
    assert by_kind["passage"]["stroke_width"] == 5
    assert by_kind["container"]["fill_color"] == "#ef4444"


@pytest.mark.django_db
def test_publish_syncs_container_and_returns_only_published_map():
    user = User.objects.create_user(
        phone_number="996700777001",
        password="pass12345",
        first_name="Admin",
        is_verify=True,
        is_staff=True,
    )
    bazar = Bazar.objects.create(name="Дордой")
    passage = Passage.objects.create(bazar=bazar, number="1")
    container = Container.objects.create(
        passage=passage,
        number="101",
        title="Текстиль",
        lat="42.930000",
        lon="74.610000",
    )
    draft = MarketMapRevision.objects.create(
        bazar=bazar,
        version=1,
        created_by=user,
        geojson={
            "type": "FeatureCollection",
            "features": [
                polygon_feature(bazar.id),
                container_feature(bazar.id, passage.id, container.id),
            ],
        },
    )

    draft.publish(user=user)
    container.refresh_from_db()
    assert float(container.lat) == pytest.approx(42.941)
    assert float(container.lon) == pytest.approx(74.623)

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get("/api/delivery/map/features/?bazar_id=%s&zoom=16" % bazar.id)
    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["features"][0]["properties"]["kind"] == "bazar"

    response = client.get("/api/delivery/map/features/?bazar_id=%s&zoom=17" % bazar.id)
    assert response.status_code == 200
    assert {feature["properties"]["kind"] for feature in response.data["features"]} == {
        "bazar",
        "container",
    }


@pytest.mark.django_db
def test_new_container_can_be_created_from_published_feature():
    user = User.objects.create_user(
        phone_number="996700777002",
        password="pass12345",
        first_name="Admin",
        is_verify=True,
        is_staff=True,
    )
    bazar = Bazar.objects.create(name="Алкан")
    passage = Passage.objects.create(bazar=bazar, number="7")
    feature = container_feature(bazar.id, passage.id, 999999)
    feature["id"] = "container-new"
    feature["properties"].pop("container_id")
    feature["properties"]["number"] = "705"
    feature["properties"]["name"] = "Контейнер 705"

    revision = MarketMapRevision.objects.create(
        bazar=bazar,
        version=1,
        geojson={"type": "FeatureCollection", "features": [polygon_feature(bazar.id), feature]},
        created_by=user,
    )
    revision.publish(user=user)

    created = Container.objects.get(passage=passage, number="705")
    assert float(created.lat) == pytest.approx(42.941)
    assert float(created.lon) == pytest.approx(74.623)


@pytest.mark.django_db
def test_container_outside_bazar_is_rejected():
    bazar = Bazar.objects.create(name="Тестовый базар")
    passage = Passage.objects.create(bazar=bazar, number="1")
    feature = container_feature(bazar.id, passage.id, 1)
    feature["geometry"]["coordinates"] = [75.0, 43.0]

    with pytest.raises(ValidationError):
        validate_feature_collection(
            {"type": "FeatureCollection", "features": [polygon_feature(bazar.id), feature]}
        )


def test_self_intersecting_polygon_is_rejected():
    invalid = polygon_feature(1)
    invalid["geometry"]["coordinates"] = [[
        [74.60, 42.90],
        [74.65, 42.95],
        [74.60, 42.95],
        [74.65, 42.90],
        [74.60, 42.90],
    ]]
    with pytest.raises(ValidationError):
        validate_feature_collection({"type": "FeatureCollection", "features": [invalid]})
