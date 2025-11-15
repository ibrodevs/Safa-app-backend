# apps/delivery/views.py
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models import OuterRef, Subquery, F, Q
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, permissions, decorators, response, status, serializers, filters
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer, OpenApiParameter

from .models import Shipment, ShipmentStop, CourierSegment, Container
from .serializer import (
    ContainerSerializer,
    CourierSegmentSerializer,
    ShipmentCreateSerializer,
    ShipmentDetailSerializer,
    ShipmentStatusSerializer,
    ShipmentCardSerializer,
    QuoteInSerializer,
    QuoteOutSerializer,
)
from .geo import polyline_len_km, haversine_m, bbox_deltas


def _broadcast(shipment: Shipment):
    layer = get_channel_layer()
    data = ShipmentDetailSerializer(shipment).data
    async_to_sync(layer.group_send)(f"shipment_{shipment.id}", {"type": "shipment.event", "payload": data})


class ContainerViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Container.objects.select_related("bazar").all()
    serializer_class = ContainerSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ["title", "number", "passage", "bazar__name"]


class CourierSegmentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CourierSegment.objects.filter(is_active=True).order_by("order", "name")
    serializer_class = CourierSegmentSerializer
    permission_classes = [permissions.IsAuthenticated]


@extend_schema_view(
    list=extend_schema(tags=["Shipments"], responses=ShipmentDetailSerializer),
    retrieve=extend_schema(tags=["Shipments"], responses=ShipmentDetailSerializer),
    create=extend_schema(tags=["Shipments"], request=ShipmentCreateSerializer, responses=ShipmentDetailSerializer),
)
class ShipmentViewSet(viewsets.ModelViewSet):
    queryset = Shipment.objects.select_related("client", "carrier", "segment").prefetch_related(
        "stops__container", "stops__container__bazar"
    )
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == "create":
            return ShipmentCreateSerializer
        if self.action in ["set_status", "accept", "set_route", "quote", "nearby", "advance"]:
            return ShipmentStatusSerializer
        return ShipmentDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        u = self.request.user
        if u.is_staff:
            return qs
        return (qs.filter(client=u) | qs.filter(carrier=u)).distinct()

    def perform_create(self, serializer):
        shipment = serializer.save()
        _broadcast(shipment)

    @extend_schema(tags=["Shipments"], summary="Курьер принимает посылку", responses=ShipmentDetailSerializer)
    @decorators.action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        s = self.get_object()
        s.carrier = request.user
        s.status = Shipment.Status.IN_TRANSIT
        s.save(update_fields=["carrier", "status"])
        _broadcast(s)
        return response.Response(ShipmentDetailSerializer(s).data)

    @extend_schema(tags=["Shipments"], summary="Сменить статус", request=ShipmentStatusSerializer, responses=ShipmentDetailSerializer)
    @decorators.action(detail=True, methods=["post"])
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
        return response.Response(ShipmentDetailSerializer(s).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Shipments"],
        summary="Задать/изменить маршрут (2–4 точки) + опция возврата",
        request=inline_serializer(
            name="SetRouteIn",
            fields={
                "stops": serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=2, max_length=4),
                "return_to_start": serializers.BooleanField(default=False),
            },
        ),
        responses=ShipmentDetailSerializer,
    )
    @decorators.action(detail=True, methods=["post"])
    def set_route(self, request, pk=None):
        from .models import ShipmentStop
        s = self.get_object()
        stops = list(request.data.get("stops", []) or [])
        rts = bool(request.data.get("return_to_start", False))
        if not isinstance(stops, list) or len(stops) < 2 or len(stops) > 4:
            return response.Response({"detail": "Нужно 2–4 точки."}, status=400)
        if rts and len(stops) >= 4:
            return response.Response({"detail": "С возвратом максимум 3 исходные точки."}, status=400)
        if rts:
            stops.append(stops[0])

        ShipmentStop.objects.filter(shipment=s).delete()
        ShipmentStop.objects.bulk_create(
            [ShipmentStop(shipment=s, container_id=cid, position=i) for i, cid in enumerate(stops)]
        )
        s.current_stop_index = 1
        s.estimate()
        s.save(update_fields=["distance_km", "estimated_fare", "current_stop_index"])
        _broadcast(s)
        return response.Response(ShipmentDetailSerializer(s).data)

    @extend_schema(tags=["Shipments"], summary="Квота по container_ids или coords", request=QuoteInSerializer, responses=QuoteOutSerializer)
    @decorators.action(detail=False, methods=["post"])
    def quote(self, request):
        ser = QuoteInSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        seg = get_object_or_404(CourierSegment, id=data["segment_id"], is_active=True)

        if data.get("container_ids") is not None:
            ids = list(data["container_ids"])
            if data.get("return_to_start"):
                ids.append(ids[0])
            if len(ids) < 2:
                return response.Response({"detail": "Нужно 2–4 точки."}, status=400)
            bulk = Container.objects.in_bulk(ids)
            geoms = [(bulk[i].lat, bulk[i].lon) for i in ids]
        else:
            stops = list(data["stops"])
            if data.get("return_to_start"):
                stops.append(stops[0])
            if len(stops) < 2:
                return response.Response({"detail": "Нужно 2–4 точки."}, status=400)
            geoms = [(p["lat"], p["lon"]) for p in stops]

        dist_km = Decimal(str(polyline_len_km(geoms))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        mult = Decimal(
            seg.size_m_multiplier if data["size"] == "M"
            else seg.size_s_multiplier if data["size"] == "S"
            else seg.size_l_multiplier
        )
        if data["fragile"]:
            mult *= (Decimal("1.00") + Decimal(seg.fragile_pct or 0) / Decimal("100"))
        cost = (Decimal(seg.base_price) + Decimal(seg.per_km_price) * dist_km) * mult
        if seg.per_unit:
            cost *= Decimal(data.get("quantity", 1))
        cost = cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if cost < Decimal(seg.min_fare or 0):
            cost = Decimal(seg.min_fare or 0)

        return response.Response(QuoteOutSerializer({"distance_km": dist_km, "estimated_fare": int(cost)}).data)

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
    @decorators.action(detail=False, methods=["get"])
    def nearby(self, request):
        lat = float(request.query_params.get("lat"))
        lon = float(request.query_params.get("lon"))
        radius_m = int(request.query_params.get("radius_m", 300))

        dlat, dlon = bbox_deltas(lat, radius_m)

        # черновой предфильтр по первой точке (position=0)
        base = (
            Shipment.objects.filter(status=Shipment.Status.PENDING)
            .filter(
                stops__position=0,
                stops__container__lat__gte=lat - dlat,
                stops__container__lat__lte=lat + dlat,
                stops__container__lon__gte=lon - dlon,
                stops__container__lon__lte=lon + dlon,
            )
            .distinct()
            .prefetch_related("stops__container", "stops__container__bazar")
        )

        # финальный расчёт дистанции в Python
        items = []
        for s in base:
            first = s.stops.order_by("position").first()
            if not first:
                continue
            dist_m = int(round(haversine_m(lat, lon, float(first.container.lat), float(first.container.lon))))
            if dist_m <= radius_m:
                items.append((dist_m, s))

        items.sort(key=lambda t: t[0])
        data = ShipmentCardSerializer([s for _, s in items], many=True).data
        for d, (dist_m, _) in zip(data, items):
            d["distance_m"] = dist_m
        return response.Response(data)

    @extend_schema(
        tags=["Shipments"],
        summary="Ручное продвижение на следующую точку/завершение",
        request=inline_serializer(name="AdvanceIn", fields={"force": serializers.BooleanField(default=False)}),
        responses=ShipmentDetailSerializer,
    )
    @decorators.action(detail=True, methods=["post"])
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
                s.save(update_fields=["current_stop_index", "status", "final_fare"])
            else:
                s.save(update_fields=["current_stop_index"])
        _broadcast(s)
        return response.Response(ShipmentDetailSerializer(s).data)
