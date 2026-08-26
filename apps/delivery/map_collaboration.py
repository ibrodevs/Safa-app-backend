from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from .map_models import MarketMapRevision
from .map_tariff_sync import attach_district_tariff_ids
from .map_validation import validate_feature_collection
from .models import Bazar, DeliveryDistrict


class MapEditConflict(ValidationError):
    """Raised when two editors changed the same map object differently."""


@dataclass(frozen=True)
class MapSaveResult:
    revision: MarketMapRevision
    merged: bool


def _features_by_id(collection: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(feature["id"]): feature
        for feature in collection.get("features", [])
    }


def _feature_label(feature: dict[str, Any] | None, feature_id: str) -> str:
    properties = (feature or {}).get("properties") or {}
    return str(properties.get("name") or properties.get("number") or feature_id)


def merge_feature_collections(
    *,
    base: dict[str, Any],
    submitted: dict[str, Any],
    current: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Three-way merge a map by stable feature id.

    Independent additions, edits and deletions are combined. If both editors
    changed the same feature differently, the save is rejected instead of
    silently losing either person's work.
    """

    base_by_id = _features_by_id(base)
    submitted_by_id = _features_by_id(submitted)
    current_by_id = _features_by_id(current)
    merged_by_id: dict[str, dict[str, Any]] = {}
    conflicts: list[str] = []

    all_ids = set(base_by_id) | set(submitted_by_id) | set(current_by_id)
    for feature_id in all_ids:
        base_feature = base_by_id.get(feature_id)
        submitted_feature = submitted_by_id.get(feature_id)
        current_feature = current_by_id.get(feature_id)

        if submitted_feature == base_feature:
            chosen = current_feature
        elif current_feature == base_feature:
            chosen = submitted_feature
        elif submitted_feature == current_feature:
            chosen = submitted_feature
        else:
            conflicts.append(
                _feature_label(submitted_feature or current_feature or base_feature, feature_id)
            )
            continue

        if chosen is not None:
            merged_by_id[feature_id] = deepcopy(chosen)

    if conflicts:
        names = ", ".join(f"«{name}»" for name in conflicts[:5])
        suffix = " и другие" if len(conflicts) > 5 else ""
        raise MapEditConflict(
            "Другой администратор одновременно изменил те же объекты: "
            f"{names}{suffix}. Обновите страницу и повторите изменение. "
            "Ничьи данные не были перезаписаны."
        )

    # Keep the current server order, then append genuinely new client objects.
    ordered_ids = [
        feature_id
        for feature_id in current_by_id
        if feature_id in merged_by_id
    ]
    ordered_ids.extend(
        feature_id
        for feature_id in submitted_by_id
        if feature_id in merged_by_id and feature_id not in current_by_id
    )
    merged = {
        "type": "FeatureCollection",
        "features": [merged_by_id[feature_id] for feature_id in ordered_ids],
    }
    return merged, merged != submitted


def sync_district_catalog(collection: dict[str, Any]) -> dict[str, Any]:
    """Make every named map district immediately visible in district lists."""

    for feature in collection.get("features", []):
        properties = feature.get("properties") or {}
        if properties.get("kind") != "district":
            continue
        name = str(properties.get("name") or "").strip()
        if not name:
            continue
        district = DeliveryDistrict.objects.filter(name__iexact=name).first()
        if district is None:
            district, _ = DeliveryDistrict.objects.get_or_create(name=name)
        properties["district_tariff_id"] = district.id
    return attach_district_tariff_ids(collection)


@transaction.atomic
def save_collaborative_map(
    *,
    bazar: Bazar,
    submitted_geojson: dict[str, Any],
    base_geojson: dict[str, Any] | None,
    user=None,
) -> MapSaveResult:
    # Locking the bazar serializes draft creation as well as saves for one map.
    locked_bazar = Bazar.objects.select_for_update().get(pk=bazar.pk)
    revision, _ = MarketMapRevision.get_or_create_draft(
        bazar=locked_bazar,
        user=user,
    )
    revision = MarketMapRevision.objects.select_for_update().get(pk=revision.pk)

    submitted = validate_feature_collection(submitted_geojson)
    if base_geojson is None:
        # Compatibility for older clients. The updated web editor always sends
        # its initial base snapshot and therefore uses the safe merge path.
        merged_collection = submitted
        was_merged = False
    else:
        base = validate_feature_collection(base_geojson)
        current = validate_feature_collection(revision.geojson)
        merged_collection, was_merged = merge_feature_collections(
            base=base,
            submitted=submitted,
            current=current,
        )

    merged_collection = validate_feature_collection(merged_collection)
    revision.geojson = sync_district_catalog(merged_collection)
    revision.full_clean()
    revision.save(update_fields=("geojson", "updated_at"))
    return MapSaveResult(revision=revision, merged=was_merged)


@transaction.atomic
def publish_collaborative_map(
    *,
    bazar: Bazar,
    submitted_geojson: dict[str, Any],
    base_geojson: dict[str, Any] | None,
    user=None,
) -> MapSaveResult:
    result = save_collaborative_map(
        bazar=bazar,
        submitted_geojson=submitted_geojson,
        base_geojson=base_geojson,
        user=user,
    )
    published = result.revision.publish(user=user)
    return MapSaveResult(revision=published, merged=result.merged)
