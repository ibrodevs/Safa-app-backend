from __future__ import annotations

import hashlib
import json

from django.http import HttpResponseNotModified
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .map_models import MarketMapRevision
from .map_validation import filter_feature_collection


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
            bbox = self._bbox(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

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

        payload = {
            "type": "FeatureCollection",
            "features": features,
            "versions": versions,
            "count": len(features),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        etag = '"' + hashlib.sha256(encoded).hexdigest() + '"'
        if request.headers.get("If-None-Match") == etag:
            response = HttpResponseNotModified()
            response["ETag"] = etag
            return response

        response = Response(payload)
        response["ETag"] = etag
        response["Cache-Control"] = "private, max-age=60"
        return response

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
