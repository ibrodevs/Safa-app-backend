from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response

from .map_point_resolver import resolve_market_point
from .views import ReverseGeocodeView


class SafaReverseGeocodeView(ReverseGeocodeView):
    """Resolve Safa containers before falling back to external geocoding."""

    def get(self, request):
        raw_lat = request.query_params.get("lat")
        raw_lon = request.query_params.get("lon")
        if raw_lat in (None, "") or raw_lon in (None, ""):
            return Response(
                {"error": "lat and lon are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            lat = float(raw_lat)
            lon = float(raw_lon)
        except (TypeError, ValueError):
            return Response(
                {"error": "invalid lat or lon"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return Response(
                {"error": "invalid lat or lon"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        match = resolve_market_point(lat, lon)
        if match is not None:
            return Response(match.as_response())

        return super().get(request)
