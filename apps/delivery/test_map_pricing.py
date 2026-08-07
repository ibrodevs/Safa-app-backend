from decimal import Decimal

import pytest

from apps.delivery.map_models import MarketMapRevision
from apps.delivery.map_pricing import MapPricingResolver, tariff_price
from apps.delivery.models import (
    Bazar,
    DeliveryDistrict,
    GlobalDeliveryConfig,
    Shipment,
    ShipmentStop,
)
from apps.delivery.specialists import point_inside_bazar
from apps.delivery import views
from apps.users.models import User


def _polygon(left, bottom, right, top):
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


def _publish_map(bazar, districts):
    features = [
        {
            "type": "Feature",
            "id": "bazar-boundary",
            "properties": {"kind": "bazar", "name": bazar.name},
            "geometry": _polygon(74.50, 42.80, 74.70, 43.00),
        }
    ]
    for index, (name, bounds) in enumerate(districts, start=1):
        features.append(
            {
                "type": "Feature",
                "id": f"district-{index}",
                "properties": {"kind": "district", "name": name},
                "geometry": _polygon(*bounds),
            }
        )
    return MarketMapRevision.objects.create(
        bazar=bazar,
        version=1,
        status=MarketMapRevision.Status.PUBLISHED,
        geojson={"type": "FeatureCollection", "features": features},
    )


@pytest.mark.django_db
class TestPublishedMapPricing:
    def test_different_drawn_districts_produce_different_real_prices(self):
        west = DeliveryDistrict.objects.create(name="Западный", fixed_price=150)
        east = DeliveryDistrict.objects.create(name="Восточный", fixed_price=230)
        bazar = Bazar.objects.create(name="Тестовый базар")
        _publish_map(
            bazar,
            [
                (west.name, (74.52, 42.82, 74.59, 42.90)),
                (east.name, (74.61, 42.82, 74.68, 42.90)),
            ],
        )

        resolver = MapPricingResolver(Decimal("3.00"))
        assert resolver.local_price(lat=42.85, lon=74.55) == 150
        assert resolver.local_price(lat=42.85, lon=74.65) == 230

    def test_bazar_own_price_overrides_district_price(self):
        district = DeliveryDistrict.objects.create(name="Центр", fixed_price=150)
        bazar = Bazar.objects.create(name="Базар с override", fixed_price=190)
        _publish_map(bazar, [(district.name, (74.52, 42.82, 74.68, 42.95))])

        resolver = MapPricingResolver(Decimal("2"))
        assert resolver.local_price(lat=42.88, lon=74.60) == 190

    def test_dynamic_district_tariff_uses_route_distance_and_minimum(self):
        GlobalDeliveryConfig.get_config()
        tariff = DeliveryDistrict.objects.create(
            name="По километру",
            base_price=Decimal("100"),
            per_km_price=Decimal("10"),
            min_fare=Decimal("120"),
        )

        assert tariff_price(tariff, Decimal("1")) == 120
        assert tariff_price(tariff, Decimal("5")) == 150

    def test_published_boundary_is_used_even_without_legacy_rectangle(self):
        bazar = Bazar.objects.create(name="Только карта")
        _publish_map(bazar, [])

        assert bazar.top_left_lat is None
        assert point_inside_bazar(42.90, 74.60) is True
        assert point_inside_bazar(43.10, 74.60) is False

    def test_shipment_estimate_uses_same_drawn_district_tariff(self):
        district = DeliveryDistrict.objects.create(name="Район заказа", fixed_price=175)
        bazar = Bazar.objects.create(name="Базар заказа")
        _publish_map(bazar, [(district.name, (74.52, 42.82, 74.68, 42.95))])
        user = User.objects.create(phone_number="996555000901", first_name="Client")
        shipment = Shipment.objects.create(client=user, title="Map tariff order")
        ShipmentStop.objects.create(
            shipment=shipment,
            position=0,
            lat=Decimal("42.860000"),
            lon=Decimal("74.560000"),
            title="Откуда",
        )
        ShipmentStop.objects.create(
            shipment=shipment,
            position=1,
            lat=Decimal("42.900000"),
            lon=Decimal("74.640000"),
            title="Куда",
        )

        assert shipment.estimate() == 175
        assert shipment.estimated_fare == 175

    def test_quote_and_created_shipment_use_same_tariff(self):
        district = DeliveryDistrict.objects.create(name="Единая цена", fixed_price=205)
        bazar = Bazar.objects.create(name="Единый базар")
        _publish_map(bazar, [(district.name, (74.52, 42.82, 74.68, 42.95))])
        stops = [
            {"lat": 42.86, "lon": 74.56},
            {"lat": 42.90, "lon": 74.64},
        ]

        # apps.ready подменяет legacy helper тем же map resolver, который
        # используется Shipment.estimate().
        assert views._quote_fixed_bazar_fare(stops) == 205

        user = User.objects.create(phone_number="996555000902", first_name="Client")
        shipment = Shipment.objects.create(client=user, title="Quote parity")
        for position, stop in enumerate(stops):
            ShipmentStop.objects.create(
                shipment=shipment,
                position=position,
                lat=Decimal(str(stop["lat"])),
                lon=Decimal(str(stop["lon"])),
                title=str(position),
            )
        assert shipment.estimate() == 205

    def test_legacy_price_from_no_longer_overrides_selected_district(self):
        district = DeliveryDistrict.objects.create(name="Новый тариф", fixed_price=160)
        bazar = Bazar.objects.create(
            name="Legacy bazar",
            district_tariff=district,
            price_from=90,
        )

        assert bazar.effective_fixed_price == 160
