from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Iterable

from django.core.exceptions import ValidationError


ALLOWED_KINDS = {"bazar", "district", "sector", "row", "passage", "container"}
POLYGON_KINDS = {"bazar", "district", "sector"}
LINE_KINDS = {"row", "passage"}
MAX_FEATURES = 5000
MAX_POINTS_PER_GEOMETRY = 2500

STYLE_DEFAULTS = {
    "bazar": {
        "min_zoom": 10,
        "stroke_width": 4,
        "stroke_color": "#ff6b35",
        "fill_color": "#ff6b35",
        "fill_opacity": 0.12,
        "z_index": 10,
    },
    "district": {
        "min_zoom": 13,
        "stroke_width": 3,
        "stroke_color": "#2563eb",
        "fill_color": "#60a5fa",
        "fill_opacity": 0.16,
        "z_index": 20,
    },
    "sector": {
        "min_zoom": 14,
        "stroke_width": 2,
        "stroke_color": "#16a34a",
        "fill_color": "#4ade80",
        "fill_opacity": 0.18,
        "z_index": 30,
    },
    "row": {
        "min_zoom": 16,
        "stroke_width": 3,
        "stroke_color": "#7c3aed",
        "fill_color": "#a78bfa",
        "fill_opacity": 0,
        "z_index": 50,
        "line_pattern": "dashed",
    },
    "passage": {
        "min_zoom": 14,
        "stroke_width": 5,
        "stroke_color": "#d97706",
        "fill_color": "#fbbf24",
        "fill_opacity": 0,
        "z_index": 60,
        "line_pattern": "solid",
    },
    "container": {
        "min_zoom": 15,
        "stroke_width": 2,
        "stroke_color": "#dc2626",
        "fill_color": "#ef4444",
        "fill_opacity": 1,
        "z_index": 100,
    },
}


def empty_feature_collection() -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": []}


def _number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{label}: координата должна быть числом")
    number = float(value)
    if not math.isfinite(number):
        raise ValidationError(f"{label}: координата должна быть конечным числом")
    return number


def _opacity(value: Any, *, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = fallback
    if not math.isfinite(number):
        return fallback
    return max(0, min(1, number))


def _rotation(value: Any) -> float:
    """Поворот контейнера в градусах по часовой стрелке, приведённый к [0, 360)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return round(number % 360, 2)


def _point(value: Any, *, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise ValidationError(f"{label}: точка должна содержать [lon, lat]")
    lon = _number(value[0], label=label)
    lat = _number(value[1], label=label)
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise ValidationError(f"{label}: координаты выходят за допустимый диапазон")
    return [lon, lat]


def _line(value: Any, *, label: str, minimum: int = 2) -> list[list[float]]:
    if not isinstance(value, list) or len(value) < minimum:
        raise ValidationError(f"{label}: недостаточно точек")
    if len(value) > MAX_POINTS_PER_GEOMETRY:
        raise ValidationError(f"{label}: слишком много точек")
    return [_point(point, label=f"{label}[{index}]") for index, point in enumerate(value)]


def _orientation(a: list[float], b: list[float], c: list[float]) -> int:
    value = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])
    if abs(value) < 1e-12:
        return 0
    return 1 if value > 0 else 2


def _on_segment(a: list[float], b: list[float], c: list[float]) -> bool:
    return (
        min(a[0], c[0]) - 1e-12 <= b[0] <= max(a[0], c[0]) + 1e-12
        and min(a[1], c[1]) - 1e-12 <= b[1] <= max(a[1], c[1]) + 1e-12
    )


def _segments_intersect(a: list[float], b: list[float], c: list[float], d: list[float]) -> bool:
    o1 = _orientation(a, b, c)
    o2 = _orientation(a, b, d)
    o3 = _orientation(c, d, a)
    o4 = _orientation(c, d, b)
    if o1 != o2 and o3 != o4:
        return True
    return (
        (o1 == 0 and _on_segment(a, c, b))
        or (o2 == 0 and _on_segment(a, d, b))
        or (o3 == 0 and _on_segment(c, a, d))
        or (o4 == 0 and _on_segment(c, b, d))
    )


def _validate_ring(ring: Any, *, label: str) -> list[list[float]]:
    points = _line(ring, label=label, minimum=4)
    if points[0] != points[-1]:
        points.append(points[0][:])
    if len({(point[0], point[1]) for point in points[:-1]}) < 3:
        raise ValidationError(f"{label}: полигон должен содержать минимум три разные вершины")

    segment_count = len(points) - 1
    for first in range(segment_count):
        a, b = points[first], points[first + 1]
        for second in range(first + 1, segment_count):
            if second in {first, first + 1}:
                continue
            if first == 0 and second == segment_count - 1:
                continue
            c, d = points[second], points[second + 1]
            if _segments_intersect(a, b, c, d):
                raise ValidationError(f"{label}: граница пересекает сама себя")
    return points


def _polygon(value: Any, *, label: str) -> list[list[list[float]]]:
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{label}: Polygon должен содержать внешний контур")
    return [_validate_ring(ring, label=f"{label}[{index}]") for index, ring in enumerate(value)]


def _multipolygon(value: Any, *, label: str) -> list[list[list[list[float]]]]:
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{label}: MultiPolygon не должен быть пустым")
    return [_polygon(polygon, label=f"{label}[{index}]") for index, polygon in enumerate(value)]


def _normalize_geometry(geometry: Any, *, kind: str, label: str) -> dict[str, Any]:
    if not isinstance(geometry, dict):
        raise ValidationError(f"{label}: geometry должна быть объектом")
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")

    if kind == "container":
        if geometry_type == "Point":
            normalized = _point(coordinates, label=f"{label}.coordinates")
        elif geometry_type == "Polygon":
            normalized = _polygon(coordinates, label=f"{label}.coordinates")
        else:
            raise ValidationError(f"{label}: контейнер должен быть Point или Polygon")
    elif kind in POLYGON_KINDS:
        if geometry_type == "Polygon":
            normalized = _polygon(coordinates, label=f"{label}.coordinates")
        elif geometry_type == "MultiPolygon":
            normalized = _multipolygon(coordinates, label=f"{label}.coordinates")
        else:
            raise ValidationError(f"{label}: зона должна быть Polygon или MultiPolygon")
    elif kind in LINE_KINDS:
        if geometry_type == "LineString":
            normalized = _line(coordinates, label=f"{label}.coordinates")
        elif geometry_type == "Polygon":
            normalized = _polygon(coordinates, label=f"{label}.coordinates")
        else:
            raise ValidationError(f"{label}: ряд/проход должен быть LineString или Polygon")
    else:
        raise ValidationError(f"{label}: неизвестный тип объекта")

    return {"type": geometry_type, "coordinates": normalized}


def _iter_points(coordinates: Any) -> Iterable[list[float]]:
    if (
        isinstance(coordinates, list)
        and len(coordinates) >= 2
        and isinstance(coordinates[0], (int, float))
        and isinstance(coordinates[1], (int, float))
    ):
        yield [float(coordinates[0]), float(coordinates[1])]
        return
    if isinstance(coordinates, list):
        for item in coordinates:
            yield from _iter_points(item)


def geometry_bbox(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    points = list(_iter_points(geometry.get("coordinates")))
    if not points:
        raise ValidationError("Геометрия не содержит координат")
    lons = [point[0] for point in points]
    lats = [point[1] for point in points]
    return min(lons), min(lats), max(lons), max(lats)


def _point_on_segment(point: list[float], a: list[float], b: list[float]) -> bool:
    if _orientation(a, point, b) != 0:
        return False
    return _on_segment(a, point, b)


def point_in_ring(point: list[float], ring: list[list[float]]) -> bool:
    inside = False
    x, y = point
    for index in range(len(ring) - 1):
        a, b = ring[index], ring[index + 1]
        if _point_on_segment(point, a, b):
            return True
        ax, ay = a
        bx, by = b
        intersects = (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / ((by - ay) or 1e-30) + ax
        if intersects:
            inside = not inside
    return inside


def point_in_geometry(point: list[float], geometry: dict[str, Any]) -> bool:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    polygons = [coordinates] if geometry_type == "Polygon" else coordinates if geometry_type == "MultiPolygon" else []
    for polygon in polygons:
        if not polygon or not point_in_ring(point, polygon[0]):
            continue
        if any(point_in_ring(point, hole) for hole in polygon[1:]):
            continue
        return True
    return False


def _geometry_segments(geometry: dict[str, Any]) -> Iterable[tuple[list[float], list[float]]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    polygons = [coordinates] if geometry_type == "Polygon" else coordinates if geometry_type == "MultiPolygon" else []
    for polygon in polygons:
        for ring in polygon:
            for index in range(len(ring) - 1):
                yield ring[index], ring[index + 1]


def geometries_intersect(first: dict[str, Any], second: dict[str, Any]) -> bool:
    first_bbox = geometry_bbox(first)
    second_bbox = geometry_bbox(second)
    if (
        first_bbox[2] < second_bbox[0]
        or first_bbox[0] > second_bbox[2]
        or first_bbox[3] < second_bbox[1]
        or first_bbox[1] > second_bbox[3]
    ):
        return False

    for point in _iter_points(first.get("coordinates")):
        if point_in_geometry(point, second):
            return True
    for point in _iter_points(second.get("coordinates")):
        if point_in_geometry(point, first):
            return True
    for a, b in _geometry_segments(first):
        for c, d in _geometry_segments(second):
            if _segments_intersect(a, b, c, d):
                return True
    return False


def representative_point(geometry: dict[str, Any]) -> list[float]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "Point":
        return [float(coordinates[0]), float(coordinates[1])]

    points = list(_iter_points(coordinates))
    if not points:
        raise ValidationError("Геометрия не содержит координат")
    lons = [point[0] for point in points]
    lats = [point[1] for point in points]
    return [(min(lons) + max(lons)) / 2, (min(lats) + max(lats)) / 2]


def iter_district_features(collection: dict[str, Any]) -> list[dict[str, Any]]:
    """Возвращает фигуры районов карты — они существуют только в GeoJSON."""
    features = (collection or {}).get("features") or []
    return [
        feature
        for feature in features
        if isinstance(feature, dict) and ((feature.get("properties") or {}).get("kind") == "district")
    ]


def district_name_for_geometry(
    geometry: dict[str, Any],
    district_features: list[dict[str, Any]],
) -> str:
    """Район, внутри которого лежит объект карты.

    Проход — ломаная, и часть её точек может выходить за границу района,
    поэтому побеждает район, накрывающий больше точек. Если объект не попал
    ни в один район, возвращается пустая строка.
    """
    try:
        points = list(_iter_points((geometry or {}).get("coordinates") or []))
    except (TypeError, ValueError):
        return ""
    if not points:
        return ""

    best_name = ""
    best_score = 0
    for feature in district_features:
        name = str((feature.get("properties") or {}).get("name") or "").strip()
        if not name:
            continue
        district_geometry = feature.get("geometry") or {}
        score = sum(1 for point in points if point_in_geometry(point, district_geometry))
        if score > best_score:
            best_name = name
            best_score = score
    return best_name


METERS_PER_LAT_DEGREE = 111320.0


def passage_angle_for_geometry(geometry: dict[str, Any]) -> float | None:
    """Наклон линии прохода в градусах.

    Система координат та же, что у поворота контейнера: 0° — линия на восток,
    отсчёт по часовой стрелке. Направление рисования не важно, поэтому угол
    сводится к диапазону 0–180°. Берётся самый длинный сегмент ломаной — он
    задаёт основное направление прохода.
    """
    try:
        points = list(_iter_points((geometry or {}).get("coordinates") or []))
    except (TypeError, ValueError):
        return None
    if len(points) < 2:
        return None

    origin_lat = points[0][1]
    lon_meters = math.cos(math.radians(origin_lat)) * METERS_PER_LAT_DEGREE

    longest: tuple[float, float] | None = None
    longest_length = 0.0
    for start, end in zip(points, points[1:]):
        vector = (
            (end[0] - start[0]) * lon_meters,
            (end[1] - start[1]) * METERS_PER_LAT_DEGREE,
        )
        length = math.hypot(vector[0], vector[1])
        if length > longest_length:
            longest_length = length
            longest = vector

    if longest is None or longest_length < 1e-6:
        return None

    angle = math.degrees(math.atan2(-longest[1], longest[0])) % 360
    return round(angle % 180, 1)


def duplicate_passage_message(number: str, district: str) -> str:
    where = f"в районе «{district}»" if district else "в этом базаре вне районов"
    return f"Проход «{number}» уже существует {where}"


def validate_feature_collection(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("type") != "FeatureCollection":
        raise ValidationError("Карта должна быть GeoJSON FeatureCollection")
    raw_features = value.get("features")
    if not isinstance(raw_features, list):
        raise ValidationError("FeatureCollection.features должен быть списком")
    if len(raw_features) > MAX_FEATURES:
        raise ValidationError(f"На одной карте допускается не более {MAX_FEATURES} объектов")

    normalized_features: list[dict[str, Any]] = []
    feature_ids: set[str] = set()
    bazar_geometries: list[dict[str, Any]] = []
    district_features: list[dict[str, Any]] = []
    passage_features: list[dict[str, Any]] = []
    container_features: list[dict[str, Any]] = []

    for index, raw in enumerate(raw_features):
        label = f"features[{index}]"
        if not isinstance(raw, dict) or raw.get("type") != "Feature":
            raise ValidationError(f"{label}: ожидается GeoJSON Feature")
        properties = raw.get("properties")
        if not isinstance(properties, dict):
            raise ValidationError(f"{label}.properties должен быть объектом")
        kind = str(properties.get("kind") or "").strip().lower()
        if kind not in ALLOWED_KINDS:
            raise ValidationError(f"{label}: неизвестный kind '{kind}'")
        name = str(properties.get("name") or properties.get("number") or "").strip()
        if not name:
            raise ValidationError(f"{label}: у объекта должно быть название или номер")

        feature_id = str(raw.get("id") or f"{kind}-{index + 1}").strip()
        if feature_id in feature_ids:
            raise ValidationError(f"{label}: id '{feature_id}' повторяется")
        feature_ids.add(feature_id)

        style = STYLE_DEFAULTS[kind]
        normalized_properties = deepcopy(properties)
        normalized_properties["kind"] = kind
        normalized_properties["name"] = name
        normalized_properties["min_zoom"] = max(0, min(22, int(properties.get("min_zoom", style["min_zoom"]) or 0)))
        normalized_properties["stroke_width"] = max(
            1,
            min(12, int(properties.get("stroke_width", style["stroke_width"]) or style["stroke_width"])),
        )
        normalized_properties["stroke_color"] = str(properties.get("stroke_color") or style["stroke_color"])
        # Цвет подписи задаётся отдельно от цвета линии и хранится только если
        # админ его выбрал — иначе подпись красится цветом линии.
        label_color = str(properties.get("label_color") or "").strip()
        if label_color:
            normalized_properties["label_color"] = label_color
        else:
            normalized_properties.pop("label_color", None)
        normalized_properties["fill_color"] = str(properties.get("fill_color") or style["fill_color"])
        normalized_properties["fill_opacity"] = _opacity(
            properties.get("fill_opacity", style["fill_opacity"]),
            fallback=float(style["fill_opacity"]),
        )
        # Слой строго по типу объекта: контейнеры сверху, под ними проходы,
        # районы и граница базара. Иначе сохранённый в старой карте z_index
        # кладёт заливку района поверх контейнеров и перехватывает клики.
        normalized_properties["z_index"] = int(style["z_index"])
        if kind == "container":
            normalized_properties["rotation"] = _rotation(properties.get("rotation"))
        if "line_pattern" in style:
            pattern = str(properties.get("line_pattern") or style["line_pattern"]).strip().lower()
            normalized_properties["line_pattern"] = pattern if pattern in {"solid", "dashed"} else style["line_pattern"]
        geometry = _normalize_geometry(raw.get("geometry"), kind=kind, label=label)
        feature = {
            "type": "Feature",
            "id": feature_id,
            "properties": normalized_properties,
            "geometry": geometry,
        }
        normalized_features.append(feature)
        if kind == "bazar":
            bazar_geometries.append(geometry)
        elif kind == "district":
            district_features.append(feature)
        elif kind == "passage":
            passage_features.append(feature)
        elif kind == "container":
            container_features.append(feature)

    if len(bazar_geometries) > 1:
        raise ValidationError("В одной версии карты допускается только одна граница базара")
    if district_features and not bazar_geometries:
        raise ValidationError("Сначала создайте границу базара, потом районы внутри неё")
    if bazar_geometries:
        boundary = bazar_geometries[0]
        for feature in district_features:
            points = list(_iter_points(feature["geometry"]["coordinates"]))
            if not points or any(not point_in_geometry(point, boundary) for point in points):
                raise ValidationError(
                    f"Район '{feature['properties']['name']}' выходит за границу базара"
                )
        for index, feature in enumerate(district_features):
            for other in district_features[index + 1 :]:
                if geometries_intersect(feature["geometry"], other["geometry"]):
                    raise ValidationError(
                        f"Районы '{feature['properties']['name']}' и '{other['properties']['name']}' пересекаются"
                    )
        for feature in passage_features:
            points = list(_iter_points(feature["geometry"]["coordinates"]))
            if not points or any(not point_in_geometry(point, boundary) for point in points):
                raise ValidationError(
                    f"Проход '{feature['properties']['name']}' выходит за границу базара"
                )
        for feature in container_features:
            points = list(_iter_points(feature["geometry"]["coordinates"]))
            if not points or any(not point_in_geometry(point, boundary) for point in points):
                raise ValidationError(
                    f"Контейнер '{feature['properties']['name']}' находится за границей базара"
                )

    return {
        "type": "FeatureCollection",
        "features": normalized_features,
    }


def filter_feature_collection(
    collection: dict[str, Any],
    *,
    zoom: int | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for feature in collection.get("features", []):
        properties = feature.get("properties") or {}
        if zoom is not None and int(properties.get("min_zoom", 0) or 0) > zoom:
            continue
        if bbox is not None:
            min_lon, min_lat, max_lon, max_lat = geometry_bbox(feature.get("geometry") or {})
            query_min_lon, query_min_lat, query_max_lon, query_max_lat = bbox
            if max_lon < query_min_lon or min_lon > query_max_lon or max_lat < query_min_lat or min_lat > query_max_lat:
                continue
        features.append(feature)
    return {"type": "FeatureCollection", "features": features}
