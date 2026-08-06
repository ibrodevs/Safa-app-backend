from __future__ import annotations

from functools import wraps

from django.core.exceptions import ValidationError
from django.db import transaction

from .map_models import MarketMapRevision
from .models import Passage


DEFAULT_PASSAGE_NAMES = {"", "Новый проход", "New passage"}


def sync_passages(revision: MarketMapRevision) -> None:
    """Create or update Passage records from passage features in map GeoJSON."""
    changed = False

    for feature in revision.geojson.get("features", []):
        properties = feature.get("properties") or {}
        if properties.get("kind") != "passage":
            continue

        number = str(properties.get("number") or properties.get("name") or "").strip()
        if number in DEFAULT_PASSAGE_NAMES:
            raise ValidationError("Укажите название или номер каждого прохода перед публикацией")

        passage = None
        passage_id = properties.get("passage_id")
        if passage_id:
            passage = Passage.objects.filter(pk=passage_id, bazar=revision.bazar).first()

        if passage is None:
            passage, _ = Passage.objects.get_or_create(
                bazar=revision.bazar,
                number=number,
            )
        elif passage.number != number:
            duplicate = Passage.objects.filter(
                bazar=revision.bazar,
                number=number,
            ).exclude(pk=passage.pk).exists()
            if duplicate:
                raise ValidationError(f"Проход с названием '{number}' уже существует")
            passage.number = number
            passage.save(update_fields=("number",))

        if properties.get("passage_id") != passage.id or properties.get("number") != passage.number:
            properties["passage_id"] = passage.id
            properties["number"] = passage.number
            properties["name"] = passage.number
            feature["properties"] = properties
            changed = True

    if changed:
        MarketMapRevision.objects.filter(pk=revision.pk).update(geojson=revision.geojson)


def enable_passage_sync() -> None:
    """Run passage synchronization before the existing map publication flow."""
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
