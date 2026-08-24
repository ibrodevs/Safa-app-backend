from decimal import Decimal

import pytest

from apps.delivery.map_models import MarketMapRevision
from apps.delivery.map_point_resolver import resolve_market_point
from apps.delivery.serializer import ShipmentDetailSerializer, ShipmentNearbySerializer
from apps.delivery.models import Bazar, Container, Passage, Shipment, ShipmentStop
from apps.users.models import User


def _polygon(left: float, bottom: float, right: float, top: float):
    return {
        "type": "Polygon",
        "coordinates": [[
            [left, top],
            [right, top],
            [right, bottom],
            [left, bottom],
            [left, top],
        ]],
    }


def _published_map(*, bazar: Bazar, container: Container):
    MarketMapRevision.objects.create(
        bazar=bazar,
        version=1,
        status=MarketMapRevision.Status.PUBLISHED,
        geojson={
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": f"bazar-{bazar.id}",
                    "properties": {"kind": "bazar", "name": bazar.name},
                    "geometry": _polygon(74.50, 42.80, 74.70, 43.00),
                },
                {
                    "type": "Feature",
                    "id": "district-center",
                    "properties": {"kind": "district", "name": "Центральный"},
                    "geometry": _polygon(74.54, 42.84, 74.66, 42.96),
                },
                {
                    "type": "Feature",
                    "id": f"container-{container.id}",
                    "properties": {
                        "kind": "container",
                        "name": container.number,
                        "number": container.number,
                        "container_id": container.id,
                        "passage_id": container.passage_id,
                        "is_active": True,
                    },
                    "geometry": _polygon(74.59997, 42.89997, 74.60003, 42.90003),
                },
            ],
        },
    )


@pytest.fixture
def mapped_container(db):
    bazar = Bazar.objects.create(name="Дордой")
    passage = Passage.objects.create(bazar=bazar, number="8")
    container = Container.objects.create(
        passage=passage,
        number="125",
        lat=Decimal("42.900000"),
        lon=Decimal("74.600000"),
        is_active=True,
    )
    _published_map(bazar=bazar, container=container)
    return container


@pytest.mark.django_db
def test_resolver_returns_full_safa_hierarchy(mapped_container):
    match = resolve_market_point(42.9, 74.6)

    assert match is not None
    assert match.container.id == mapped_container.id
    assert match.bazar_name == "Дордой"
    assert match.district_name == "Центральный"
    assert match.passage_number == "8"
    assert match.container_number == "125"
    assert match.address == (
        "Базар: Дордой · Район: Центральный · Проход: 8 · Контейнер: 125"
    )


@pytest.mark.django_db
def test_reverse_geocode_prefers_safa_container_over_external_address(
    client, settings, mapped_container
):
    settings.YANDEX_API_KEY = ""

    response = client.get(
        "/api/delivery/geo/reverse/",
        {"lat": "42.9", "lon": "74.6"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "safa_map"
    assert payload["bazar"] == "Дордой"
    assert payload["district"] == "Центральный"
    assert payload["passage"] == "8"
    assert payload["container"] == "125"
    assert payload["container_id"] == mapped_container.id


@pytest.mark.django_db
def test_reverse_geocode_falls_back_to_coordinates_without_api_key(client, settings):
    settings.YANDEX_API_KEY = ""

    response = client.get(
        "/api/delivery/geo/reverse/",
        {"lat": "42.8441392", "lon": "74.6001756"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "address": "42.844139, 74.600176",
        "source": "coordinates",
    }


@pytest.mark.django_db
def test_coordinate_stop_is_automatically_linked_to_mapped_container(
    mapped_container,
):
    user = User.objects.create(phone_number="996555001234", first_name="Client")
    shipment = Shipment.objects.create(client=user, title="Тест")

    stop = ShipmentStop.objects.create(
        shipment=shipment,
        position=0,
        title="Выбрано пином на карте",
        lat=Decimal("42.900000"),
        lon=Decimal("74.600000"),
    )

    stop.refresh_from_db()
    assert stop.container_id == mapped_container.id
    assert stop.lat == mapped_container.lat
    assert stop.lon == mapped_container.lon


@pytest.mark.django_db
def test_shipment_serializers_share_compact_map_hierarchy_and_fare(mapped_container):
    user = User.objects.create(phone_number="996555009876", first_name="Client")
    shipment = Shipment.objects.create(
        client=user,
        title="Реальный заказ",
        service_type=Shipment.ServiceType.DELIVERY,
        estimated_fare=275,
        final_fare=0,
    )
    ShipmentStop.objects.create(
        shipment=shipment,
        position=0,
        container=mapped_container,
    )

    detail = ShipmentDetailSerializer(shipment).data
    nearby = ShipmentNearbySerializer(
        shipment,
        context={"user_lat": 42.9, "user_lon": 74.6},
    ).data

    expected = {
        "bazar": "Дордой",
        "district": "Центральный",
        "passage": "8",
        "container": "125",
        "label": "Базар: Дордой · Район: Центральный · Проход: 8 · Контейнер: 125",
    }
    for key, value in expected.items():
        assert detail["stops"][0][key] == value
        assert nearby["stops"][0][key] == value

    assert detail["estimated_fare"] == nearby["estimated_fare"] == 275
    assert nearby["service_type"] == Shipment.ServiceType.DELIVERY
    assert nearby["stops_count"] == 1
    assert nearby["commission"] == shipment.commission_amount
    assert nearby["courier_income"] == shipment.courier_income
