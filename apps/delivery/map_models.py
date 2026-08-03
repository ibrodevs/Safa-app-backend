from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from .map_validation import (
    STYLE_DEFAULTS,
    empty_feature_collection,
    representative_point,
    validate_feature_collection,
)
from .models import Bazar, Container, Passage


class MarketMapRevision(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        PUBLISHED = "published", "Опубликована"
        ARCHIVED = "archived", "Архив"

    bazar = models.ForeignKey(
        Bazar,
        on_delete=models.CASCADE,
        related_name="map_revisions",
        verbose_name="Базар",
    )
    version = models.PositiveIntegerField(verbose_name="Версия")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        verbose_name="Статус",
    )
    geojson = models.JSONField(default=empty_feature_collection, verbose_name="GeoJSON")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_market_maps",
        verbose_name="Автор",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создана")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Изменена")
    published_at = models.DateTimeField(null=True, blank=True, verbose_name="Опубликована")

    class Meta:
        app_label = "delivery"
        ordering = ("bazar__name", "-version")
        verbose_name = "Карта базара"
        verbose_name_plural = "Карты базаров"
        constraints = [
            models.UniqueConstraint(
                fields=("bazar", "version"),
                name="uniq_market_map_bazar_version",
            ),
        ]
        indexes = [
            models.Index(fields=("bazar", "status", "-version"), name="market_map_lookup_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.bazar.name} · v{self.version} · {self.get_status_display()}"

    def clean(self) -> None:
        super().clean()
        self.geojson = validate_feature_collection(self.geojson)

    @classmethod
    def latest_published(cls, bazar: Bazar | int) -> "MarketMapRevision | None":
        bazar_id = bazar.pk if isinstance(bazar, Bazar) else int(bazar)
        return (
            cls.objects.filter(bazar_id=bazar_id, status=cls.Status.PUBLISHED)
            .order_by("-version")
            .first()
        )

    @classmethod
    def next_version(cls, bazar: Bazar) -> int:
        current = (
            cls.objects.filter(bazar=bazar)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
        )
        return int(current or 0) + 1

    @classmethod
    def get_or_create_draft(cls, *, bazar: Bazar, user=None) -> tuple["MarketMapRevision", bool]:
        draft = cls.objects.filter(bazar=bazar, status=cls.Status.DRAFT).order_by("-version").first()
        if draft:
            return draft, False

        published = cls.latest_published(bazar)
        geojson = deepcopy(published.geojson) if published else build_initial_geojson(bazar)
        return (
            cls.objects.create(
                bazar=bazar,
                version=cls.next_version(bazar),
                status=cls.Status.DRAFT,
                geojson=geojson,
                created_by=user if getattr(user, "is_authenticated", False) else None,
            ),
            True,
        )

    @transaction.atomic
    def publish(self, *, user=None) -> "MarketMapRevision":
        locked = MarketMapRevision.objects.select_for_update().get(pk=self.pk)
        if locked.status != self.Status.DRAFT:
            raise ValidationError("Публиковать можно только черновик")

        locked.geojson = validate_feature_collection(locked.geojson)
        boundaries = [
            feature
            for feature in locked.geojson.get("features", [])
            if (feature.get("properties") or {}).get("kind") == "bazar"
        ]
        if len(boundaries) != 1:
            raise ValidationError("Перед публикацией нарисуйте одну границу базара")

        locked._sync_containers()
        MarketMapRevision.objects.filter(
            bazar=locked.bazar,
            status=self.Status.PUBLISHED,
        ).update(status=self.Status.ARCHIVED)
        locked.status = self.Status.PUBLISHED
        locked.published_at = timezone.now()
        if user is not None and getattr(user, "is_authenticated", False) and locked.created_by_id is None:
            locked.created_by = user
        locked.save(
            update_fields=("geojson", "status", "published_at", "created_by", "updated_at")
        )
        return locked

    def _sync_containers(self) -> None:
        for feature in self.geojson.get("features", []):
            properties = feature.get("properties") or {}
            if properties.get("kind") != "container":
                continue
            center = representative_point(feature.get("geometry") or {})
            lon = Decimal(str(center[0])).quantize(Decimal("0.000001"))
            lat = Decimal(str(center[1])).quantize(Decimal("0.000001"))

            container = None
            container_id = properties.get("container_id")
            if container_id:
                container = (
                    Container.objects.select_related("passage", "passage__bazar")
                    .filter(pk=container_id, passage__bazar=self.bazar)
                    .first()
                )

            if container is None:
                passage_id = properties.get("passage_id")
                number = str(properties.get("number") or properties.get("name") or "").strip()
                passage = Passage.objects.filter(pk=passage_id, bazar=self.bazar).first() if passage_id else None
                if passage is None or not number:
                    raise ValidationError(
                        f"Для нового контейнера '{properties.get('name', '')}' выберите проход и номер"
                    )
                container, _ = Container.objects.get_or_create(
                    passage=passage,
                    number=number,
                    defaults={
                        "title": str(properties.get("title") or "").strip(),
                        "lat": lat,
                        "lon": lon,
                        "is_active": True,
                    },
                )

            container.lat = lat
            container.lon = lon
            container.is_active = bool(properties.get("is_active", True))
            title = str(properties.get("title") or "").strip()
            if title:
                container.title = title
            container.save(update_fields=("lat", "lon", "is_active", "title"))

            properties["container_id"] = container.id
            properties["passage_id"] = container.passage_id
            properties["number"] = container.number
            properties["name"] = properties.get("name") or container.display_title


def build_initial_geojson(bazar: Bazar) -> dict[str, Any]:
    """Build a non-blocking draft from legacy rectangle and container fields.

    Old data may contain containers outside the legacy rectangle. The editor must
    still open so an administrator can redraw the real boundary; strict spatial
    validation is applied when the draft is saved or published.
    """

    features: list[dict[str, Any]] = []
    if all(
        value is not None
        for value in (
            bazar.top_left_lat,
            bazar.top_left_lon,
            bazar.bottom_right_lat,
            bazar.bottom_right_lon,
        )
    ):
        left = float(bazar.top_left_lon)
        right = float(bazar.bottom_right_lon)
        top = float(bazar.top_left_lat)
        bottom = float(bazar.bottom_right_lat)
        features.append(
            {
                "type": "Feature",
                "id": f"bazar-{bazar.id}",
                "properties": {
                    "kind": "bazar",
                    "name": bazar.name,
                    "bazar_id": bazar.id,
                    **STYLE_DEFAULTS["bazar"],
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [left, top],
                        [right, top],
                        [right, bottom],
                        [left, bottom],
                        [left, top],
                    ]],
                },
            }
        )

    for passage in bazar.passages.select_related("bazar").prefetch_related("containers"):
        for item in passage.containers.filter(is_active=True):
            features.append(
                {
                    "type": "Feature",
                    "id": f"container-{item.id}",
                    "properties": {
                        "kind": "container",
                        "name": item.display_title,
                        "title": item.title,
                        "number": item.number,
                        "bazar_id": bazar.id,
                        "passage_id": item.passage_id,
                        "container_id": item.id,
                        **STYLE_DEFAULTS["container"],
                        "is_active": item.is_active,
                    },
                    "geometry": container_rectangle(float(item.lon), float(item.lat)),
                }
            )

    return {"type": "FeatureCollection", "features": features}


class MarketBoundaryMapSection(MarketMapRevision):
    class Meta:
        proxy = True
        app_label = "delivery"
        verbose_name = "Карта: граница базара"
        verbose_name_plural = "Карта: границы базаров"


class MarketPassageMapSection(MarketMapRevision):
    class Meta:
        proxy = True
        app_label = "delivery"
        verbose_name = "Карта: проход"
        verbose_name_plural = "Карта: проходы"


class MarketContainerMapSection(MarketMapRevision):
    class Meta:
        proxy = True
        app_label = "delivery"
        verbose_name = "Карта: контейнер"
        verbose_name_plural = "Карта: контейнеры"


def container_rectangle(lon: float, lat: float, *, half_width: float = 0.000018, half_height: float = 0.000012) -> dict[str, Any]:
    left = lon - half_width
    right = lon + half_width
    bottom = lat - half_height
    top = lat + half_height
    return {
        "type": "Polygon",
        "coordinates": [[
            [left, top],
            [right, top],
            [right, bottom],
            [left, bottom],
            [left, top],
        ]],
    }
