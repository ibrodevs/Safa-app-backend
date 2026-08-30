from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

from .map_models import MarketMapRevision
from .map_validation import point_in_geometry
from .models import Bazar, DeliveryDistrict, GlobalDeliveryConfig


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rounded_money(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _distance_price(
    *,
    distance_km: Decimal,
    base_price: Decimal,
    per_km_price: Decimal,
    min_fare: Decimal,
) -> int:
    cost = Decimal(base_price) + Decimal(per_km_price) * Decimal(distance_km)
    cost = cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if cost < Decimal(min_fare):
        cost = Decimal(min_fare)
    return _rounded_money(cost)


def global_route_price(distance_km: Decimal) -> int:
    config = GlobalDeliveryConfig.get_config()
    return _distance_price(
        distance_km=distance_km,
        base_price=Decimal(config.base_price),
        per_km_price=Decimal(config.per_km_price),
        min_fare=Decimal(config.min_fare),
    )


def tariff_price(tariff: DeliveryDistrict, distance_km: Decimal) -> int | None:
    """Возвращает цену активного тарифа района для всего маршрута.

    Приоритет внутри тарифа:
    1. fixed_price;
    2. base_price/per_km_price/min_fare. Незаполненные части динамического
       тарифа наследуются из глобальных настроек.
    """

    if not tariff.is_active:
        return None
    if tariff.fixed_price is not None:
        return int(tariff.fixed_price)

    has_dynamic_settings = any(
        value is not None
        for value in (tariff.base_price, tariff.per_km_price, tariff.min_fare)
    )
    if not has_dynamic_settings:
        return None

    global_config = GlobalDeliveryConfig.get_config()
    return _distance_price(
        distance_km=distance_km,
        base_price=Decimal(
            tariff.base_price
            if tariff.base_price is not None
            else global_config.base_price
        ),
        per_km_price=Decimal(
            tariff.per_km_price
            if tariff.per_km_price is not None
            else global_config.per_km_price
        ),
        min_fare=Decimal(
            tariff.min_fare
            if tariff.min_fare is not None
            else global_config.min_fare
        ),
    )


class MapPricingResolver:
    """Один источник истины для зон карты и тарифов доставки."""

    def __init__(self, distance_km: Decimal | int | float | str = Decimal("0")):
        self.distance_km = Decimal(str(distance_km or 0))
        self.bazars = list(
            Bazar.objects.select_related("district_tariff").all()
        )
        self.bazars_by_id = {bazar.id: bazar for bazar in self.bazars}
        self.tariffs = list(DeliveryDistrict.objects.filter(is_active=True))
        self.tariffs_by_id = {tariff.id: tariff for tariff in self.tariffs}
        self.tariffs_by_name = {
            tariff.name.strip().casefold(): tariff
            for tariff in self.tariffs
            if tariff.name.strip()
        }

        self.revisions = list(
            MarketMapRevision.objects.filter(
                status=MarketMapRevision.Status.PUBLISHED,
            )
            .select_related("bazar")
            .order_by("bazar_id", "-version")
        )
        self.revisions_by_bazar_id: dict[int, MarketMapRevision] = {}
        for revision in self.revisions:
            self.revisions_by_bazar_id.setdefault(revision.bazar_id, revision)

    @staticmethod
    def _contains(feature: dict[str, Any], lat: float, lon: float) -> bool:
        geometry = feature.get("geometry") or {}
        try:
            return point_in_geometry([lon, lat], geometry)
        except (TypeError, ValueError, IndexError):
            return False

    @staticmethod
    def _features(revision: MarketMapRevision | None) -> list[dict[str, Any]]:
        if revision is None or not isinstance(revision.geojson, dict):
            return []
        raw = revision.geojson.get("features") or []
        return [feature for feature in raw if isinstance(feature, dict)]

    def _published_bazar_contains(
        self,
        revision: MarketMapRevision,
        lat: float,
        lon: float,
    ) -> bool:
        for feature in self._features(revision):
            props = feature.get("properties") or {}
            if props.get("kind") == "bazar" and self._contains(feature, lat, lon):
                return True
        return False

    @staticmethod
    def _legacy_bazar_contains(bazar: Bazar, lat: float, lon: float) -> bool:
        values = (
            bazar.top_left_lat,
            bazar.top_left_lon,
            bazar.bottom_right_lat,
            bazar.bottom_right_lon,
        )
        if any(value is None for value in values):
            return False
        return (
            float(bazar.bottom_right_lat) <= lat <= float(bazar.top_left_lat)
            and float(bazar.top_left_lon) <= lon <= float(bazar.bottom_right_lon)
        )

    def find_bazar(
        self,
        lat: float,
        lon: float,
        *,
        preferred_bazar: Bazar | None = None,
    ) -> Bazar | None:
        # Для остановки, привязанной к контейнеру, FK контейнера является
        # более надёжным источником базара, чем геометрическое распознавание.
        if preferred_bazar is not None:
            return self.bazars_by_id.get(preferred_bazar.id, preferred_bazar)

        for revision in self.revisions_by_bazar_id.values():
            if self._published_bazar_contains(revision, lat, lon):
                return self.bazars_by_id.get(revision.bazar_id, revision.bazar)

        # Обратная совместимость со старыми базарами, у которых ещё нет
        # опубликованной GeoJSON-карты.
        for bazar in self.bazars:
            if self._legacy_bazar_contains(bazar, lat, lon):
                return bazar
        return None

    def _district_tariff_for_point(
        self,
        bazar: Bazar,
        lat: float,
        lon: float,
    ) -> DeliveryDistrict | None:
        revision = self.revisions_by_bazar_id.get(bazar.id)
        for feature in self._features(revision):
            props = feature.get("properties") or {}
            if props.get("kind") != "district" or not self._contains(feature, lat, lon):
                continue

            raw_tariff_id = props.get("district_tariff_id")
            try:
                tariff_id = int(raw_tariff_id) if raw_tariff_id not in (None, "") else None
            except (TypeError, ValueError):
                tariff_id = None
            if tariff_id is not None:
                tariff = self.tariffs_by_id.get(tariff_id)
                if tariff is not None:
                    return tariff

            # Уже опубликованные карты до внедрения district_tariff_id не
            # ломаются: район можно сопоставить по точному имени тарифа.
            name = str(props.get("name") or "").strip().casefold()
            if name:
                tariff = self.tariffs_by_name.get(name)
                if tariff is not None:
                    return tariff
        return None

    def district_tariff_for_point(
        self,
        lat: float,
        lon: float,
    ) -> DeliveryDistrict | None:
        """Find an active tariff directly from published district polygons.

        Districts are global delivery zones now, so a legacy bazar boundary is
        not required for price resolution.
        """

        for revision in self.revisions_by_bazar_id.values():
            for feature in self._features(revision):
                props = feature.get("properties") or {}
                if props.get("kind") != "district" or not self._contains(feature, lat, lon):
                    continue
                raw_tariff_id = props.get("district_tariff_id")
                try:
                    tariff_id = int(raw_tariff_id) if raw_tariff_id not in (None, "") else None
                except (TypeError, ValueError):
                    tariff_id = None
                if tariff_id is not None and tariff_id in self.tariffs_by_id:
                    return self.tariffs_by_id[tariff_id]
                name = str(props.get("name") or "").strip().casefold()
                if name and name in self.tariffs_by_name:
                    return self.tariffs_by_name[name]
        return None

    def local_price(
        self,
        *,
        lat: float,
        lon: float,
        preferred_bazar: Bazar | None = None,
    ) -> int | None:
        bazar = self.find_bazar(lat, lon, preferred_bazar=preferred_bazar)
        # Legacy fixed prices remain compatible for already-published market
        # maps, but they are no longer configurable in the custom panel.
        if bazar is not None and bazar.fixed_price is not None:
            return int(bazar.fixed_price)

        district_tariff = self.district_tariff_for_point(lat, lon)
        if district_tariff is not None:
            price = tariff_price(district_tariff, self.distance_km)
            if price is not None:
                return price

        if bazar is None:
            return None

        district_tariff = self._district_tariff_for_point(bazar, lat, lon)
        if district_tariff is not None:
            price = tariff_price(district_tariff, self.distance_km)
            if price is not None:
                return price

        # Fallback для базаров, у которых тариф района выбран в обычной
        # Django-форме, но район ещё не нарисован/не привязан на карте.
        if bazar.district_tariff_id:
            tariff = self.tariffs_by_id.get(bazar.district_tariff_id)
            if tariff is not None:
                price = tariff_price(tariff, self.distance_km)
                if price is not None:
                    return price

        # Самый старый источник цены оставляем последним fallback.
        if bazar.price_from is not None:
            return int(bazar.price_from)
        return None

    def point_inside_any_bazar(self, lat: Any, lon: Any) -> bool:
        lat_value = _as_float(lat)
        lon_value = _as_float(lon)
        if lat_value is None or lon_value is None:
            return False
        return self.find_bazar(lat_value, lon_value) is not None


def _stop_values(stop: Any) -> tuple[float | None, float | None, Bazar | None]:
    if isinstance(stop, dict):
        return _as_float(stop.get("lat")), _as_float(stop.get("lon")), None

    lat = _as_float(getattr(stop, "lat", None))
    lon = _as_float(getattr(stop, "lon", None))
    preferred_bazar = None
    container = getattr(stop, "container", None)
    if container is not None:
        try:
            preferred_bazar = container.passage.bazar
        except (AttributeError, Bazar.DoesNotExist):
            preferred_bazar = None
    return lat, lon, preferred_bazar


def estimate_route_fare(stops: Iterable[Any], distance_km: Any) -> int:
    """Единый расчёт quote и реальной Shipment.estimated_fare."""

    distance = Decimal(str(distance_km or 0))
    resolver = MapPricingResolver(distance)
    prices: list[int] = []
    has_stops = False
    fallback_price = global_route_price(distance)

    for stop in stops:
        has_stops = True
        lat, lon, preferred_bazar = _stop_values(stop)
        if lat is None or lon is None:
            prices.append(fallback_price)
            continue
        price = resolver.local_price(
            lat=lat,
            lon=lon,
            preferred_bazar=preferred_bazar,
        )
        prices.append(price if price is not None else fallback_price)

    if has_stops and prices:
        # Для маршрута через несколько районов или через район и внешнюю
        # территорию применяется самый высокий из подходящих тарифов.
        return max(prices)
    return fallback_price


def point_inside_published_or_legacy_bazar(lat: Any, lon: Any) -> bool:
    return MapPricingResolver().point_inside_any_bazar(lat, lon)
