from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import requests

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404

from rest_framework import viewsets, permissions, response, status, serializers
from rest_framework.decorators import action

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
    OpenApiTypes,
    inline_serializer,
)

from .models import Shipment, ShipmentStop, CourierSegment
from .serializer import (
    CourierSegmentSerializer,
    ShipmentCreateSerializer,
    ShipmentDetailSerializer,
    ShipmentStatusSerializer,
    ShipmentCardSerializer,
    QuoteInSerializer,
    QuoteOutSerializer,
)
from .geo import polyline_len_km, haversine_m, bbox_deltas
from .pagination import StandardResultsSetPagination


def _broadcast(shipment: Shipment):
    layer = get_channel_layer()
    data = ShipmentDetailSerializer(shipment).data
    async_to_sync(layer.group_send)(
        f"shipment_{shipment.id}",
        {"type": "shipment.event", "payload": data},
    )


class CourierSegmentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CourierSegment.objects.filter(is_active=True).order_by("order", "name")
    serializer_class = CourierSegmentSerializer
    permission_classes = [permissions.IsAuthenticated]


@extend_schema_view(
    list=extend_schema(tags=["Shipments"], responses=ShipmentDetailSerializer),
    retrieve=extend_schema(tags=["Shipments"], responses=ShipmentDetailSerializer),
    create=extend_schema(
        tags=["Shipments"],
        request=ShipmentCreateSerializer,
        responses=ShipmentDetailSerializer,
    ),
)
class ShipmentViewSet(viewsets.ModelViewSet):
    queryset = (
        Shipment.objects
        .select_related("client", "carrier", "segment")
        .prefetch_related("stops")
    )
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_serializer_class(self):
        if self.action == "create":
            return ShipmentCreateSerializer
        if self.action in ["set_status", "accept", "advance"]:
            return ShipmentStatusSerializer
        return ShipmentDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        if not user.is_authenticated:
            return qs.none()

        if user.is_superuser or user.is_staff:
            return qs

        return qs.filter(Q(client=user) | Q(carrier=user)).distinct()

    def perform_create(self, serializer):
        shipment = serializer.save()
        _broadcast(shipment)

    @extend_schema(
        tags=["Shipments"],
        summary="Курьер принимает посылку",
        responses=ShipmentDetailSerializer,
    )
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        s = self.get_object()
        s.carrier = request.user
        s.status = Shipment.Status.ASSIGNED
        s.save(update_fields=["carrier", "status"])
        _broadcast(s)
        return response.Response(ShipmentDetailSerializer(s).data)

    @extend_schema(
        tags=["Shipments"],
        summary="Сменить статус",
        request=ShipmentStatusSerializer,
        responses=ShipmentDetailSerializer,
    )
    @action(detail=True, methods=["post"])
    def set_status(self, request, pk=None):
        s = self.get_object()
        ser = ShipmentStatusSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        s.status = ser.validated_data["status"]
        if s.status == Shipment.Status.COMPLETED:
            s.finalize()
            s.save(update_fields=["status", "final_fare"])
        else:
            s.save(update_fields=["status"])
        _broadcast(s)
        return response.Response(
            ShipmentDetailSerializer(s).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["Shipments"],
        summary="Квота по координатам (расчёт стоимости маршрута)",
        request=QuoteInSerializer,
        responses=QuoteOutSerializer,
    )
    @action(detail=False, methods=["post"])
    def quote(self, request):
        ser = QuoteInSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        seg = get_object_or_404(
            CourierSegment,
            id=data["segment_id"],
            is_active=True,
        )

        stops = list(data["stops"])
        if data.get("return_to_start"):
            stops.append(stops[0])

        if len(stops) < 2:
            return response.Response(
                {"detail": "Нужно минимум 2 точки."},
                status=400,
            )

        geoms = [(p["lat"], p["lon"]) for p in stops]
        dist_km = Decimal(str(polyline_len_km(geoms))).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

        mult = Decimal(
            seg.size_m_multiplier if data["size"] == "M"
            else seg.size_s_multiplier if data["size"] == "S"
            else seg.size_l_multiplier
        )
        if data["fragile"]:
            mult *= (
                Decimal("1.00")
                + Decimal(seg.fragile_pct or 0) / Decimal("100")
            )

        cost = (
            Decimal(seg.base_price)
            + Decimal(seg.per_km_price) * dist_km
        ) * mult

        if seg.per_unit:
            cost *= Decimal(data.get("quantity", 1))

        cost = cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        min_fare = Decimal(seg.min_fare or 0)
        if cost < min_fare:
            cost = min_fare

        return response.Response(
            QuoteOutSerializer(
                {"distance_km": dist_km, "estimated_fare": int(cost)}
            ).data
        )

    @extend_schema(
        tags=["Shipments"],
        summary="Ближайшие заказы для курьера",
        parameters=[
            OpenApiParameter(name="lat", type=float, required=True),
            OpenApiParameter(name="lon", type=float, required=True),
            OpenApiParameter(name="radius_m", type=int, required=False),
        ],
        responses=ShipmentCardSerializer(many=True),
    )
    @action(detail=False, methods=["get"])
    def nearby(self, request):
        try:
            lat = float(request.query_params["lat"])
            lon = float(request.query_params["lon"])
        except (KeyError, TypeError, ValueError):
            return response.Response(
                {"detail": "lat/lon required"},
                status=400,
            )

        radius_m = int(request.query_params.get("radius_m", 300) or 300)

        dlat, dlon = bbox_deltas(lat, radius_m)

        base = (
            Shipment.objects.filter(status=Shipment.Status.PENDING)
            .filter(
                stops__position=0,
                stops__lat__gte=lat - dlat,
                stops__lat__lte=lat + dlat,
                stops__lon__gte=lon - dlon,
                stops__lon__lte=lon + dlon,
            )
            .distinct()
            .prefetch_related("stops")
        )

        items: list[tuple[int, Shipment]] = []
        for s in base:
            first = s.stops.order_by("position").first()
            if not first:
                continue
            dist_m = int(
                round(
                    haversine_m(
                        lat,
                        lon,
                        float(first.lat),
                        float(first.lon),
                    )
                )
            )
            if dist_m <= radius_m:
                items.append((dist_m, s))

        items.sort(key=lambda t: t[0])
        data = ShipmentCardSerializer(
            [s for _, s in items],
            many=True,
        ).data
        for d, (dist_m, _) in zip(data, items):
            d["distance_m"] = dist_m
        return response.Response(data)

    @extend_schema(
        tags=["Shipments"],
        summary="Ручное продвижение на следующую точку/завершение",
        request=inline_serializer(
            name="AdvanceIn",
            fields={"force": serializers.BooleanField(default=False)},
        ),
        responses=ShipmentDetailSerializer,
    )
    @action(detail=True, methods=["post"])
    def advance(self, request, pk=None):
        s = self.get_object()
        nxt = s.next_stop()
        if not nxt:
            s.status = Shipment.Status.COMPLETED
            s.finalize()
            s.save(update_fields=["status", "final_fare"])
        else:
            s.current_stop_index += 1
            if s.current_stop_index >= s.stops.count():
                s.status = Shipment.Status.COMPLETED
                s.finalize()
                s.save(
                    update_fields=[
                        "current_stop_index",
                        "status",
                        "final_fare",
                    ]
                )
            else:
                s.save(update_fields=["current_stop_index"])
        _broadcast(s)
        return response.Response(ShipmentDetailSerializer(s).data)

    @extend_schema(
        tags=["Shipments"],
        summary="История завершённых доставок для текущего пользователя",
        parameters=[
            OpenApiParameter(
                name="page",
                description="Номер страницы (начиная с 1)",
                required=False,
                type=int,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name="page_size",
                description="Количество записей на странице (макс 100)",
                required=False,
                type=int,
                location=OpenApiParameter.QUERY,
            ),
        ],
        responses=ShipmentCardSerializer(many=True),
    )
    @action(detail=False, methods=["get"], url_path="history")
    def history(self, request):
        qs = (
            self.get_queryset()
            .filter(status=Shipment.Status.COMPLETED)
            .order_by("-created_at")
        )

        page = self.paginate_queryset(qs)
        if page is not None:
            ser = ShipmentCardSerializer(page, many=True)
            return self.get_paginated_response(ser.data)

        ser = ShipmentCardSerializer(qs, many=True)
        return response.Response(ser.data)


UA = {"User-Agent": "dordoi-go/1.0 (+contact@example.com)"}


@extend_schema(tags=["Гео"])
class GeoViewSet(viewsets.ViewSet):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="Построить маршрут между двумя точками (для Яндекс.Карт)",
        parameters=[
            OpenApiParameter(
                "from_lat",
                OpenApiTypes.FLOAT,
                OpenApiParameter.QUERY,
                required=True,
                description="Широта точки отправления",
            ),
            OpenApiParameter(
                "from_lon",
                OpenApiTypes.FLOAT,
                OpenApiParameter.QUERY,
                required=True,
                description="Долгота точки отправления",
            ),
            OpenApiParameter(
                "to_lat",
                OpenApiTypes.FLOAT,
                OpenApiParameter.QUERY,
                required=True,
                description="Широта точки назначения",
            ),
            OpenApiParameter(
                "to_lon",
                OpenApiTypes.FLOAT,
                OpenApiParameter.QUERY,
                required=True,
                description="Долгота точки назначения",
            ),
        ],
        responses={
            200: OpenApiTypes.OBJECT,
            400: OpenApiResponse(
                description="from_lon,from_lat,to_lon,to_lat required"
            ),
            404: OpenApiResponse(description="no_route"),
        },
    )
    @action(detail=False, methods=["get"], url_path="route")
    def route(self, request):
        try:
            flat = float(request.query_params["from_lat"])
            flon = float(request.query_params["from_lon"])
            tlat = float(request.query_params["to_lat"])
            tlon = float(request.query_params["to_lon"])
        except Exception:
            return response.Response(
                {"detail": "from_lon,from_lat,to_lon,to_lat required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        osrm_url = getattr(settings, "OSRM_URL", "").rstrip("/")
        if not osrm_url:
            return response.Response(
                {"detail": "OSRM_URL is not configured"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        url = f"{osrm_url}/route/v1/driving/{flon},{flat};{tlon},{tlat}"
        try:
            r = requests.get(
                url,
                params={
                    "overview": "full",
                    "geometries": "geojson",
                    "alternatives": "false",
                    "steps": "false",
                },
                headers=UA,
                timeout=10,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            return response.Response(
                {"detail": f"osrm_error: {e}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        data = r.json()
        routes = data.get("routes") or []
        if not routes:
            return response.Response(
                {"detail": "no_route"},
                status=status.HTTP_404_NOT_FOUND,
            )

        route0 = routes[0]
        distance_km = round(route0["distance"] / 1000.0, 2)
        duration_min = round(route0["duration"] / 60.0)

        return response.Response(
            {
                "distance_km": distance_km,
                "duration_min": duration_min,
                "geometry": route0["geometry"],
            },
            status=status.HTTP_200_OK,
        )
