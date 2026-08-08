from __future__ import annotations

from django.db.models.signals import pre_save

from .map_point_resolver import resolve_market_point
from .models import ShipmentStop


def _resolve_stop_container(sender, instance: ShipmentStop, **kwargs) -> None:
    if instance.container_id or instance.lat is None or instance.lon is None:
        return

    match = resolve_market_point(float(instance.lat), float(instance.lon))
    if match is None:
        return

    container = match.container
    instance.container = container
    instance.lat = container.lat
    instance.lon = container.lon
    if not (instance.title or "").strip():
        instance.title = match.address


def enable_map_stop_resolution() -> None:
    pre_save.connect(
        _resolve_stop_container,
        sender=ShipmentStop,
        dispatch_uid="delivery.resolve_coordinate_stop_to_map_container",
        weak=False,
    )
