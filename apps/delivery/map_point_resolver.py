from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .map_models import MarketMapRevision
from .map_validation import point_in_geometry
from .models import Container


@dataclass(frozen=True)
class ResolvedMarketPoint:
    container: Container
    bazar_name: str
    district_name: str
    passage_number: str

    @property
    def container_number(self) -> str:
        return self.container.number

    @property
    def address(self) -> str:
        parts = [f"Базар: {self.bazar_name}"]
        if self.district_name:
            parts.append(f"Район: {self.district_name}")
        if self.passage_number:
            parts.append(f"Проход: {self.passage_number}")
        if self.container_number:
            parts.append(f"Контейнер: {self.container_number}")
        return " · ".join(parts)

    def as_response(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "source": "safa_map",
            "bazar": self.bazar_name,
            "district": self.district_name,
            "passage": self.passage_number,
            "container": self.container_number,
            "container_id": self.container.id,
        }


def _contains(feature: dict[str, Any], *, lat: float, lon: float) -> bool:
    geometry = feature.get("geometry") or {}
    try:
        return point_in_geometry([lon, lat], geometry)
    except (TypeError, ValueError, IndexError):
        return False


def _features(revision: MarketMapRevision) -> list[dict[str, Any]]:
    geojson = revision.geojson if isinstance(revision.geojson, dict) else {}
    raw = geojson.get("features") or []
    return [feature for feature in raw if isinstance(feature, dict)]


def _latest_published_revisions() -> list[MarketMapRevision]:
    revisions = (
        MarketMapRevision.objects.filter(status=MarketMapRevision.Status.PUBLISHED)
        .select_related("bazar")
        .order_by("bazar_id", "-version")
    )
    latest: list[MarketMapRevision] = []
    seen: set[int] = set()
    for revision in revisions:
        if revision.bazar_id in seen:
            continue
        seen.add(revision.bazar_id)
        latest.append(revision)
    return latest


def _district_name_at(
    features: list[dict[str, Any]], *, lat: float, lon: float
) -> str:
    for feature in features:
        properties = feature.get("properties") or {}
        if properties.get("kind") != "district":
            continue
        if _contains(feature, lat=lat, lon=lon):
            return str(properties.get("name") or "").strip()
    return ""


def _container_for_feature(
    feature: dict[str, Any], *, bazar_id: int
) -> Container | None:
    properties = feature.get("properties") or {}
    raw_container_id = properties.get("container_id")
    try:
        container_id = int(raw_container_id) if raw_container_id not in (None, "") else None
    except (TypeError, ValueError):
        container_id = None

    queryset = Container.objects.filter(
        is_active=True,
        passage__bazar_id=bazar_id,
    ).select_related("passage", "passage__bazar")

    if container_id is not None:
        container = queryset.filter(pk=container_id).first()
        if container is not None:
            return container

    raw_passage_id = properties.get("passage_id")
    try:
        passage_id = int(raw_passage_id) if raw_passage_id not in (None, "") else None
    except (TypeError, ValueError):
        passage_id = None
    number = str(properties.get("number") or properties.get("name") or "").strip()
    if passage_id is None or not number:
        return None
    return queryset.filter(passage_id=passage_id, number=number).first()


def resolve_market_point(lat: float, lon: float) -> ResolvedMarketPoint | None:
    """Resolve an exact point inside a published Safa container."""

    lat_value = float(lat)
    lon_value = float(lon)

    for revision in _latest_published_revisions():
        features = _features(revision)
        boundaries = [
            feature
            for feature in features
            if (feature.get("properties") or {}).get("kind") == "bazar"
        ]
        if boundaries and not any(
            _contains(feature, lat=lat_value, lon=lon_value)
            for feature in boundaries
        ):
            continue

        for feature in features:
            properties = feature.get("properties") or {}
            if properties.get("kind") != "container":
                continue
            if not bool(properties.get("is_active", True)):
                continue
            if not _contains(feature, lat=lat_value, lon=lon_value):
                continue

            container = _container_for_feature(feature, bazar_id=revision.bazar_id)
            if container is None:
                continue

            return ResolvedMarketPoint(
                container=container,
                bazar_name=container.passage.bazar.name,
                district_name=_district_name_at(
                    features,
                    lat=float(container.lat),
                    lon=float(container.lon),
                ),
                passage_number=container.passage.number,
            )

    return None
