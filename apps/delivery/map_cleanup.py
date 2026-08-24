from __future__ import annotations

from django.db import transaction

from .map_models import MarketMapRevision
from .models import Bazar, Container, Passage, ShipmentStop


LEGACY_BOUNDARY_FIELDS = (
    "top_left_lat",
    "top_left_lon",
    "bottom_right_lat",
    "bottom_right_lon",
)


def _district_names(bazar: Bazar) -> set[str]:
    """Районы существуют только как фигуры на карте, поэтому считаем их по GeoJSON."""
    names: set[str] = set()
    for revision in MarketMapRevision.objects.filter(bazar=bazar).only("geojson"):
        for feature in (revision.geojson or {}).get("features", []):
            properties = feature.get("properties") or {}
            if properties.get("kind") != "district":
                continue
            names.add(str(properties.get("name") or "").strip().casefold())
    names.discard("")
    return names


def _delete_containers(container_ids: list[int]) -> int:
    """Удаляет контейнеры, не трогая историю заказов.

    ShipmentStop.container переведён в SET_NULL (см. DeleveryConfig.ready), а
    адрес и координаты остановка хранит своей копией, поэтому удаление
    контейнера только очищает ссылку.
    """
    if not container_ids:
        return 0
    return Container.objects.filter(id__in=container_ids).delete()[0]


@transaction.atomic
def purge_bazar_map(bazar: Bazar) -> dict[str, int]:
    """Удаляет карту базара вместе со всем, что на ней нарисовано.

    Сносим версии карты (черновики, опубликованные, архивные), а вместе с ними
    районы, проходы и контейнеры базара. Проходы и контейнеры стоят на PROTECT,
    поэтому порядок удаления важен: сначала контейнеры, потом проходы.

    Тарифы районов (DeliveryDistrict) — общий справочник, не привязанный к
    базару, он остаётся нетронутым.
    """
    container_ids = list(
        Container.objects.filter(passage__bazar=bazar).values_list("id", flat=True)
    )
    districts = len(_district_names(bazar))
    detached = ShipmentStop.objects.filter(container_id__in=container_ids).count()

    containers = _delete_containers(container_ids)
    passages = Passage.objects.filter(bazar=bazar).delete()[0]
    revisions = MarketMapRevision.objects.filter(bazar=bazar).delete()[0]

    # Старый прямоугольник базара — тоже карта: иначе редактор нарисует её заново.
    if any(getattr(bazar, field) is not None for field in LEGACY_BOUNDARY_FIELDS):
        for field in LEGACY_BOUNDARY_FIELDS:
            setattr(bazar, field, None)
        bazar.save(update_fields=LEGACY_BOUNDARY_FIELDS)

    return {
        "districts": districts,
        "passages": passages,
        "containers": containers,
        "revisions": revisions,
        "detached_stops": detached,
    }


@transaction.atomic
def delete_passage_with_containers(passage: Passage) -> dict[str, int]:
    """Удаляет проход вместе с его контейнерами (Container стоит на PROTECT)."""
    containers = _delete_containers(list(passage.containers.values_list("id", flat=True)))
    passage.delete()
    return {"containers": containers}


@transaction.atomic
def delete_bazar_with_map(bazar: Bazar) -> dict[str, int]:
    """Удаляет базар целиком: карту, районы, проходы, контейнеры и сам базар."""
    stats = purge_bazar_map(bazar)
    bazar.delete()
    return stats


def describe_map_purge(stats: dict[str, int]) -> str:
    text = (
        f"районов — {stats['districts']}, "
        f"проходов — {stats['passages']}, "
        f"контейнеров — {stats['containers']}"
    )
    if stats.get("detached_stops"):
        text += f"; остановок в посылках откреплено — {stats['detached_stops']}"
    return text
