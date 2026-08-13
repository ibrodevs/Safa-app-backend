from __future__ import annotations

import hashlib
import json

from django.core.cache import cache
from django.http import HttpResponseNotModified
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .map_models import MarketMapRevision
from .map_validation import filter_feature_collection, representative_point


class PublishedMarketMapView(APIView):
    """Возвращает только опубликованные слои карты.

    Поддерживает фильтрацию по базару, масштабу и видимой области. Формат ответа
    остаётся стандартным GeoJSON FeatureCollection, а версии вынесены в
    дополнительные поля верхнего уровня.
    """

    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        try:
            bazar_id = self._optional_int(request.query_params.get("bazar_id"), minimum=1)
            zoom = self._optional_int(request.query_params.get("zoom"), minimum=0, maximum=22)
            max_containers = self._optional_int(
                request.query_params.get("max_containers"),
                minimum=1,
                maximum=1000,
            )
            bbox = self._bbox(request)
            center = self._center(request, bbox=bbox)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        signature = list(
            MarketMapRevision.objects.filter(
                status=MarketMapRevision.Status.PUBLISHED,
                **({"bazar_id": bazar_id} if bazar_id is not None else {}),
            )
            .order_by("bazar_id", "-version")
            .values_list("id", "bazar_id", "version", "updated_at")
        )
        cache_key = self._cache_key(
            signature=signature,
            bazar_id=bazar_id,
            zoom=zoom,
            bbox=bbox,
            center=center,
            max_containers=max_containers,
        )
        cached = cache.get(cache_key)
        if cached is not None:
            payload, etag = cached
            return self._response(request, payload=payload, etag=etag)

        revisions = self._latest_revisions(bazar_id=bazar_id)
        features = []
        versions = {}
        for revision in revisions:
            filtered = filter_feature_collection(revision.geojson, zoom=zoom, bbox=bbox)
            for feature in filtered.get("features", []):
                properties = feature.setdefault("properties", {})
                properties.setdefault("bazar_id", revision.bazar_id)
                properties.setdefault("bazar_name", revision.bazar.name)
                properties.setdefault("bazar_district", revision.bazar.district)
                features.append(feature)
            versions[str(revision.bazar_id)] = revision.version

        if max_containers is not None:
            features = self._limit_containers(
                features,
                max_containers=max_containers,
                center=center,
            )

        payload = {
            "type": "FeatureCollection",
            "features": features,
            "versions": versions,
            "count": len(features),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        etag = '"' + hashlib.sha256(encoded).hexdigest() + '"'
        cache.set(cache_key, (payload, etag), timeout=60)
        return self._response(request, payload=payload, etag=etag)

    @staticmethod
    def _response(request, *, payload, etag):
        if request.headers.get("If-None-Match") == etag:
            response = HttpResponseNotModified()
            response["ETag"] = etag
            return response

        response = Response(payload)
        response["ETag"] = etag
        response["Cache-Control"] = "private, max-age=60"
        return response

    @staticmethod
    def _cache_key(*, signature, bazar_id, zoom, bbox, center, max_containers):
        raw = json.dumps(
            {
                "signature": [
                    [revision_id, market_id, version, updated_at.isoformat()]
                    for revision_id, market_id, version, updated_at in signature
                ],
                "bazar_id": bazar_id,
                "zoom": zoom,
                "bbox": bbox,
                "center": center,
                "max_containers": max_containers,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "published-market-map:" + hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _latest_revisions(*, bazar_id: int | None):
        queryset = (
            MarketMapRevision.objects.filter(status=MarketMapRevision.Status.PUBLISHED)
            .select_related("bazar")
            .order_by("bazar_id", "-version")
        )
        if bazar_id is not None:
            queryset = queryset.filter(bazar_id=bazar_id)

        output = []
        seen = set()
        for revision in queryset:
            if revision.bazar_id in seen:
                continue
            seen.add(revision.bazar_id)
            output.append(revision)
        return output

    @staticmethod
    def _optional_int(value, *, minimum: int, maximum: int | None = None) -> int | None:
        if value in (None, ""):
            return None
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Некорректное целое значение") from exc
        if number < minimum or (maximum is not None and number > maximum):
            raise ValueError("Значение выходит за допустимый диапазон")
        return number

    @staticmethod
    def _bbox(request):
        names = ("min_lon", "min_lat", "max_lon", "max_lat")
        raw = [request.query_params.get(name) for name in names]
        if all(value in (None, "") for value in raw):
            return None
        if any(value in (None, "") for value in raw):
            raise ValueError("Для bbox нужны min_lon, min_lat, max_lon и max_lat")
        try:
            min_lon, min_lat, max_lon, max_lat = [float(value) for value in raw]
        except (TypeError, ValueError) as exc:
            raise ValueError("Некорректные координаты bbox") from exc
        if min_lon > max_lon or min_lat > max_lat:
            raise ValueError("Минимальные координаты bbox не могут быть больше максимальных")
        if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180 and -90 <= min_lat <= 90 and -90 <= max_lat <= 90):
            raise ValueError("bbox выходит за допустимый диапазон координат")
        return min_lon, min_lat, max_lon, max_lat

    @staticmethod
    def _center(request, *, bbox):
        raw_lat = request.query_params.get("center_lat")
        raw_lon = request.query_params.get("center_lon")
        if raw_lat in (None, "") and raw_lon in (None, ""):
            if bbox is None:
                return None
            min_lon, min_lat, max_lon, max_lat = bbox
            return (min_lat + max_lat) / 2, (min_lon + max_lon) / 2
        if raw_lat in (None, "") or raw_lon in (None, ""):
            raise ValueError("Для центра нужны center_lat и center_lon")
        try:
            lat = float(raw_lat)
            lon = float(raw_lon)
        except (TypeError, ValueError) as exc:
            raise ValueError("Некорректные координаты центра") from exc
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Центр выходит за допустимый диапазон координат")
        return lat, lon

    @staticmethod
    def _limit_containers(features, *, max_containers: int, center):
        containers = []
        output = []
        for index, feature in enumerate(features):
            properties = feature.get("properties") or {}
            if properties.get("kind") != "container":
                output.append((index, feature))
                continue
            distance = index
            if center is not None:
                try:
                    lon, lat = representative_point(feature.get("geometry") or {})
                    distance = (lat - center[0]) ** 2 + (lon - center[1]) ** 2
                except Exception:
                    distance = float("inf")
            containers.append((distance, index, feature))

        if len(containers) <= max_containers:
            return features

        kept_container_indexes = {
            index
            for _, index, _ in sorted(
                containers,
                key=lambda item: item[0],
            )[:max_containers]
        }
        for _, index, feature in containers:
            if index in kept_container_indexes:
                output.append((index, feature))
        return [feature for _, feature in sorted(output, key=lambda item: item[0])]
