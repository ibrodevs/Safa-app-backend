from __future__ import annotations

from typing import Any

from .models import DeliveryDistrict


def attach_district_tariff_ids(collection: dict[str, Any]) -> dict[str, Any]:
    """Сохраняет стабильный tariff id для районов, выбранных по имени в UI."""

    tariffs = list(DeliveryDistrict.objects.filter(is_active=True))
    by_id = {tariff.id: tariff for tariff in tariffs}
    by_name = {
        tariff.name.strip().casefold(): tariff
        for tariff in tariffs
        if tariff.name.strip()
    }

    for feature in collection.get("features", []):
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        if not isinstance(properties, dict) or properties.get("kind") != "district":
            continue

        raw_id = properties.get("district_tariff_id")
        try:
            tariff_id = int(raw_id) if raw_id not in (None, "") else None
        except (TypeError, ValueError):
            tariff_id = None

        if tariff_id in by_id:
            continue

        name = str(properties.get("name") or "").strip().casefold()
        tariff = by_name.get(name)
        if tariff is not None:
            properties["district_tariff_id"] = tariff.id
        else:
            properties.pop("district_tariff_id", None)

    return collection
