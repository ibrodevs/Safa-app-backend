from __future__ import annotations

from collections.abc import Iterable

from .map_models import MarketMapRevision
from .models import Bazar, DeliveryDistrict


def _clean_name(value) -> str:
    return str(value or "").strip()


def map_district_names(*, current: str | None = None) -> list[str]:
    """Return district names that currently exist in the editable/published map.

    Draft revisions are included intentionally: after an administrator draws a
    district and presses "Сохранить", it should immediately be available when
    creating a district tariff, without requiring publication first.

    Legacy Bazar.district values are kept as a compatibility fallback for data
    created before map districts became the source of truth.
    """

    names: set[str] = set()

    revisions = MarketMapRevision.objects.filter(
        status__in=(MarketMapRevision.Status.DRAFT, MarketMapRevision.Status.PUBLISHED)
    ).only("geojson")
    for revision in revisions:
        for feature in (revision.geojson or {}).get("features", []):
            properties = feature.get("properties") or {}
            if properties.get("kind") != "district":
                continue
            name = _clean_name(properties.get("name"))
            if name:
                names.add(name)

    for value in Bazar.objects.exclude(district="").values_list("district", flat=True).distinct():
        name = _clean_name(value)
        if name:
            names.add(name)

    current_name = _clean_name(current)
    if current_name:
        names.add(current_name)

    return sorted(names, key=str.casefold)


def available_district_choices(
    current: str | None = None,
    *,
    exclude_configured: bool = False,
) -> list[tuple[str, str]]:
    """Build admin choices for district tariffs.

    On tariff creation, districts that already have a tariff are omitted. On
    edit, the current district remains selectable even if it is already stored.
    """

    names = map_district_names(current=current)
    current_name = _clean_name(current)

    if exclude_configured:
        configured = {
            _clean_name(name).casefold()
            for name in DeliveryDistrict.objects.values_list("name", flat=True)
            if _clean_name(name)
        }
        names = [
            name
            for name in names
            if name.casefold() == current_name.casefold() or name.casefold() not in configured
        ]

    placeholder = "Выберите район с карты" if names else "Сначала создайте и сохраните район на карте"
    return [("", placeholder), *[(name, name) for name in names]]
