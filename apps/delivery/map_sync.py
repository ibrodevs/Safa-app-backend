from __future__ import annotations

from functools import wraps

from django.core.exceptions import ValidationError
from django.db import transaction

from .map_models import MarketMapRevision
from .map_validation import (
    district_name_for_geometry,
    duplicate_passage_message,
    iter_district_features,
)
from .models import Passage


DEFAULT_PASSAGE_NAMES = {"", "Новый проход", "New passage"}


def sync_passages(revision: MarketMapRevision) -> None:
    """Create or update Passage records from passage features in map GeoJSON."""
    changed = False
    districts = iter_district_features(revision.geojson)

    for feature in revision.geojson.get("features", []):
        properties = feature.get("properties") or {}
        if properties.get("kind") != "passage":
            continue

        number = str(properties.get("number") or properties.get("name") or "").strip()
        if number in DEFAULT_PASSAGE_NAMES:
            raise ValidationError("Укажите название или номер каждого прохода перед сохранением")

        # Одинаковые номера проходов в разных районах одного базара — норма,
        # поэтому проход ищется и создаётся с учётом своего района.
        district = district_name_for_geometry(feature.get("geometry") or {}, districts)

        passage = None
        passage_id = properties.get("passage_id")
        if passage_id:
            passage = Passage.objects.filter(pk=passage_id, bazar=revision.bazar).first()

        if passage is None:
            passage, _ = Passage.objects.get_or_create(
                bazar=revision.bazar,
                district=district,
                number=number,
            )
        elif (passage.number, passage.district) != (number, district):
            duplicate = Passage.objects.filter(
                bazar=revision.bazar,
                district=district,
                number=number,
            ).exclude(pk=passage.pk).exists()
            if duplicate:
                raise ValidationError(duplicate_passage_message(number, district))
            passage.number = number
            passage.district = district
            passage.save(update_fields=("number", "district"))

        if (
            properties.get("passage_id") != passage.id
            or properties.get("number") != passage.number
            or properties.get("district") != passage.district
        ):
            properties["passage_id"] = passage.id
            properties["number"] = passage.number
            properties["name"] = passage.number
            properties["district"] = passage.district
            feature["properties"] = properties
            changed = True

    if changed and revision.pk:
        MarketMapRevision.objects.filter(pk=revision.pk).update(geojson=revision.geojson)


def enable_passage_sync() -> None:
    """Keep map passage features and the Passage catalog synchronized on save and publish."""
    current_save = MarketMapRevision.save
    if not getattr(current_save, "_safa_passage_save_sync_enabled", False):
        @wraps(current_save)
        @transaction.atomic
        def save_with_passage_sync(self, *args, **kwargs):
            update_fields = kwargs.get("update_fields")
            geojson_is_being_saved = update_fields is None or "geojson" in update_fields
            should_sync = (
                self.pk is not None
                and self.status == MarketMapRevision.Status.DRAFT
                and geojson_is_being_saved
            )

            if should_sync:
                sync_passages(self)

            return current_save(self, *args, **kwargs)

        save_with_passage_sync._safa_passage_save_sync_enabled = True
        MarketMapRevision.save = save_with_passage_sync

    current_publish = MarketMapRevision.publish
    if getattr(current_publish, "_safa_passage_sync_enabled", False):
        return

    @wraps(current_publish)
    @transaction.atomic
    def publish_with_passage_sync(self, *args, **kwargs):
        sync_passages(self)
        return current_publish(self, *args, **kwargs)

    publish_with_passage_sync._safa_passage_sync_enabled = True
    MarketMapRevision.publish = publish_with_passage_sync
