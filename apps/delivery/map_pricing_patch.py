from __future__ import annotations

from functools import wraps

from .map_pricing import estimate_route_fare
from .models import Bazar, Shipment


def _effective_fixed_price(bazar: Bazar) -> int | None:
    """Legacy helper with the same priority as the new map pricing.

    Dynamic district prices need route distance and are therefore handled by
    MapPricingResolver, not by this compatibility property.
    """

    if bazar.fixed_price is not None:
        return int(bazar.fixed_price)
    tariff = bazar.district_tariff
    if tariff and tariff.is_active and tariff.fixed_price is not None:
        return int(tariff.fixed_price)
    if bazar.price_from is not None:
        return int(bazar.price_from)
    return None


def enable_map_pricing() -> None:
    current_estimate = Shipment.estimate
    if getattr(current_estimate, "_safa_map_pricing_enabled", False):
        return

    @wraps(current_estimate)
    def estimate_with_map_pricing(self: Shipment) -> int:
        self.distance_km = self.route_distance_km()
        stops = list(
            self.stops.select_related(
                "container__passage__bazar__district_tariff",
            ).all()
        )
        self.estimated_fare = estimate_route_fare(stops, self.distance_km)
        return self.estimated_fare

    estimate_with_map_pricing._safa_map_pricing_enabled = True
    Shipment.estimate = estimate_with_map_pricing

    # Старые места кода/админки, которые читают effective_fixed_price,
    # больше не должны ставить legacy price_from выше тарифа района.
    Bazar.effective_fixed_price = property(_effective_fixed_price)
