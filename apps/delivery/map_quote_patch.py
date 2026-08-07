from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from .geo import polyline_len_km
from .map_pricing import MapPricingResolver


def _map_local_quote(stops: list[dict]) -> int | None:
    if not stops:
        return None

    geoms = [(stop["lat"], stop["lon"]) for stop in stops]
    distance_km = Decimal(str(polyline_len_km(geoms))).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    resolver = MapPricingResolver(distance_km)
    prices: list[int] = []

    for stop in stops:
        try:
            lat = float(stop["lat"])
            lon = float(stop["lon"])
        except (KeyError, TypeError, ValueError):
            return None
        price = resolver.local_price(lat=lat, lon=lon)
        if price is None:
            return None
        prices.append(price)

    return max(prices) if prices else None


def enable_quote_map_pricing() -> None:
    # views.py уже содержит fallback на GlobalDeliveryConfig. Мы подменяем
    # только локальный resolver, поэтому поведение вне базаров не меняется.
    from . import views

    current = views._quote_fixed_bazar_fare
    if getattr(current, "_safa_map_pricing_enabled", False):
        return

    @wraps(current)
    def quote_with_map_tariffs(stops: list[dict]) -> int | None:
        return _map_local_quote(stops)

    quote_with_map_tariffs._safa_map_pricing_enabled = True
    views._quote_fixed_bazar_fare = quote_with_map_tariffs
