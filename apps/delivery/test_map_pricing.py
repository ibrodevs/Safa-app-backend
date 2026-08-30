from decimal import Decimal, ROUND_HALF_UP

import pytest

from apps.delivery import views
from apps.delivery.district_per_km import per_km_tariff_price
from apps.delivery.geo import polyline_len_km
from apps.delivery.map_models import MarketMapRevision
from apps.delivery.map_pricing import MapPricingResolver, estimate_route_fare
from apps.delivery.models import Bazar, DeliveryDistrict, Shipment, ShipmentStop
from apps.delivery.specialists import point_inside_bazar
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
    def test_district_only_map_resolves_tariff_without_bazar_boundary(self):
        district = DeliveryDistrict.objects.create(
            name="Глобальная зона",
            per_km_price=Decimal("70"),
        )
        bazar = Bazar.objects.create(name="Служебная карта")
        MarketMapRevision.objects.create(
            bazar=bazar,
            version=1,
            status=MarketMapRevision.Status.PUBLISHED,
            geojson={
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "id": "district-global",
                    "properties": {
                        "kind": "district",
                        "name": district.name,
                        "district_tariff_id": district.id,
                    },
                    "geometry": _polygon(74.52, 42.82, 74.68, 42.95),
                }],
            },
        )

        resolver = MapPricingResolver(Decimal("2"))
        assert resolver.local_price(lat=42.88, lon=74.60) == 140

    def test_mixed_route_compares_district_and_global_fallback(self):
        district = DeliveryDistrict.objects.create(
            name="Дорогая зона",
            per_km_price=Decimal("100"),
        )
        bazar = Bazar.objects.create(name="Карта смешанного маршрута")
        MarketMapRevision.objects.create(
            bazar=bazar,
            version=1,
            status=MarketMapRevision.Status.PUBLISHED,
            geojson={
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "id": "district-mixed",
                    "properties": {"kind": "district", "name": district.name},
                    "geometry": _polygon(74.52, 42.82, 74.68, 42.95),
                }],
            },
        )

        assert estimate_route_fare(
            [{"lat": 42.88, "lon": 74.60}, {"lat": 43.20, "lon": 75.00}],
            Decimal("2"),
        ) == 200

    def test_different_drawn_districts_use_their_own_price_per_km(self):
        west = DeliveryDistrict.objects.create(
            name="Западный",
            per_km_price=Decimal("50"),
        )
        east = DeliveryDistrict.objects.create(
            name="Восточный",
            per_km_price=Decimal("80"),
        )
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
        assert resolver.local_price(lat=42.85, lon=74.65) == 240

    def test_bazar_own_price_still_overrides_district_price(self):
        district = DeliveryDistrict.objects.create(
            name="Центр",
            per_km_price=Decimal("75"),
        )
        bazar = Bazar.objects.create(name="Базар с override", fixed_price=190)
        _publish_map(bazar, [(district.name, (74.52, 42.82, 74.68, 42.95))])

        resolver = MapPricingResolver(Decimal("2"))
        assert resolver.local_price(lat=42.88, lon=74.60) == 190

    def test_district_tariff_uses_optional_minimum_and_ignores_other_legacy_fields(self):
        tariff = DeliveryDistrict.objects.create(
            name="Только километр",
            fixed_price=999,
            base_price=Decimal("100"),
            per_km_price=Decimal("10"),
            min_fare=Decimal("120"),
        )

        assert per_km_tariff_price(tariff, Decimal("1")) == 120
        assert per_km_tariff_price(tariff, Decimal("20")) == 200

    def test_published_boundary_is_used_even_without_legacy_rectangle(self):
        bazar = Bazar.objects.create(name="Только карта")
        _publish_map(bazar, [])

        assert bazar.top_left_lat is None
        assert point_inside_bazar(42.90, 74.60) is True
        assert point_inside_bazar(43.10, 74.60) is False

    def test_shipment_estimate_uses_map_district_price_per_km(self):
        district = DeliveryDistrict.objects.create(
            name="Район заказа",
            per_km_price=Decimal("40"),
        )
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

        expected = per_km_tariff_price(district, shipment.route_distance_km())
        assert expected is not None
        assert shipment.estimate() == expected
        assert shipment.estimated_fare == expected

    def test_quote_and_created_shipment_use_same_per_km_tariff(self):
        district = DeliveryDistrict.objects.create(
            name="Единая цена",
            per_km_price=Decimal("55"),
        )
        bazar = Bazar.objects.create(name="Единый базар")
        _publish_map(bazar, [(district.name, (74.52, 42.82, 74.68, 42.95))])
        stops = [
            {"lat": 42.86, "lon": 74.56},
            {"lat": 42.90, "lon": 74.64},
        ]

        quote_distance = Decimal(
            str(polyline_len_km([(stop["lat"], stop["lon"]) for stop in stops]))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        expected_quote = per_km_tariff_price(district, quote_distance)
        assert views._quote_fixed_bazar_fare(stops) == expected_quote

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

        expected_shipment = per_km_tariff_price(district, shipment.route_distance_km())
        assert expected_shipment is not None
        assert shipment.estimate() == expected_shipment
        assert views._quote_fixed_bazar_fare(stops) == expected_shipment

    def test_zero_distance_per_km_tariff_stays_payable(self):
        tariff = DeliveryDistrict.objects.create(
            name="Нулевая дистанция",
            per_km_price=Decimal("50"),
        )

        assert per_km_tariff_price(tariff, Decimal("0")) == 1

    def test_effective_fixed_price_does_not_use_old_district_fixed_price(self):
        district = DeliveryDistrict.objects.create(
            name="Новый тариф",
            fixed_price=160,
            per_km_price=Decimal("70"),
        )
        bazar = Bazar.objects.create(
            name="Legacy bazar",
            district_tariff=district,
        )

        assert bazar.effective_fixed_price is None
