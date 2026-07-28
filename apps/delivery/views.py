from __future__ import annotations

import logging
import uuid
from datetime import date as _date
from decimal import Decimal, ROUND_HALF_UP

import requests
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import permissions, response, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notification.events import notify_shipment_status
from apps.payments.models import PaymentAttempt
from apps.users.models import User, UserProfile
from .geocoding import twogis_autocomplete
from .geo import polyline_len_km, is_in_bishkek
from .models import Bazar, Container, GlobalDeliveryConfig, Passage, Shipment
from .pagination import StandardResultsSetPagination
from .serializer import (
    BazarSerializer,
    ContainerSerializer,
    PassageSerializer,
    QuoteInSerializer,
    QuoteOutSerializer,
    ShipmentCardSerializer,
    ShipmentCreateSerializer,
    ShipmentDetailSerializer,
    ShipmentNearbySerializer,
)
from .stats import carrier_daily_stats_with_change

logger = logging.getLogger(__name__)


def _rid(request) -> str:
    return request.headers.get("X-Request-ID") or uuid.uuid4().hex


def _broadcast(shipment: Shipment) -> None:
    layer = get_channel_layer()
    data = ShipmentDetailSerializer(shipment).data
    async_to_sync(layer.group_send)(
        f"shipment_{shipment.id}",
        {"type": "shipment.event", "payload": data},
    )


def _complete_shipment_if_needed(s: Shipment) -> None:
    if s.status == Shipment.Status.COMPLETED:
        if not s.finished_at:
            s.finalize()
            s.save(update_fields=["final_fare", "finished_at"])
        return
    s.status = Shipment.Status.COMPLETED
    s.finalize()
    s.save(update_fields=["status", "final_fare", "finished_at"])


def _increment_carrier_rating(shipment: Shipment) -> None:
    carrier = shipment.carrier
    if not carrier:
        return
    if getattr(carrier, "role", None) != User.Roles.CARRIER:
        return
    try:
        profile, _ = UserProfile.objects.get_or_create(user=carrier)
        profile.rate = int(profile.rate or 0) + 1
        profile.client_rate_count = str(int(profile.client_rate_count or 0) + 1)
        profile.save(update_fields=["rate", "client_rate_count"])
    except Exception as e:
        logger.exception(
            "increment_carrier_rating_failed", 
            extra={"shipment_id": shipment.id, "carrier_id": carrier.id, "error": str(e)}
        )





@extend_schema_view(
    list=extend_schema(
        tags=["Directory"],
        summary="Справочник базаров",
    ),
)
class BazarViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Bazar.objects.all().order_by("name")
    serializer_class = BazarSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset()
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(name__icontains=q)
        return qs


@extend_schema_view(
    list=extend_schema(
        tags=["Directory"],
        summary="Справочник проходов",
        parameters=[
            OpenApiParameter(name="bazar_id", required=False, type=int, description="Фильтр по базару"),
            OpenApiParameter(name="q", required=False, type=str, description="Поиск по номеру прохода"),
        ],
    ),
)
class PassageViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Passage.objects.select_related("bazar").all().order_by("bazar__name", "number")
    serializer_class = PassageSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset()
        bazar_id = self.request.query_params.get("bazar_id")
        if bazar_id:
            qs = qs.filter(bazar_id=bazar_id)
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(number__icontains=q) | Q(bazar__name__icontains=q))
        return qs


@extend_schema_view(
    list=extend_schema(
        tags=["Directory"],
        summary="Справочник контейнеров",
        parameters=[
            OpenApiParameter(name="bazar_id", required=False, type=int, description="Фильтр по базару"),
            OpenApiParameter(name="passage_id", required=False, type=int, description="Фильтр по проходу"),
            OpenApiParameter(name="q", required=False, type=str, description="Поиск (номер/название/проход/базар)"),
            OpenApiParameter(name="min_lat", required=False, type=float, description="Нижняя граница видимой области"),
            OpenApiParameter(name="max_lat", required=False, type=float, description="Верхняя граница видимой области"),
            OpenApiParameter(name="min_lon", required=False, type=float, description="Левая граница видимой области"),
            OpenApiParameter(name="max_lon", required=False, type=float, description="Правая граница видимой области"),
        ],
    ),
)
class ContainerViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        Container.objects.filter(is_active=True)
        .select_related("passage", "passage__bazar")
        .order_by("passage__bazar__name", "passage__number", "number")
    )
    serializer_class = ContainerSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset()
        bazar_id = self.request.query_params.get("bazar_id")
        if bazar_id:
            qs = qs.filter(passage__bazar_id=bazar_id)
        passage_id = self.request.query_params.get("passage_id")
        if passage_id:
            qs = qs.filter(passage_id=passage_id)
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(number__icontains=q)
                | Q(title__icontains=q)
                | Q(passage__number__icontains=q)
                | Q(passage__bazar__name__icontains=q)
            )
        try:
            min_lat = self.request.query_params.get("min_lat")
            max_lat = self.request.query_params.get("max_lat")
            min_lon = self.request.query_params.get("min_lon")
            max_lon = self.request.query_params.get("max_lon")
            if all(v not in (None, "") for v in (min_lat, max_lat, min_lon, max_lon)):
                lat_a, lat_b = float(min_lat), float(max_lat)
                lon_a, lon_b = float(min_lon), float(max_lon)
                qs = qs.filter(
                    lat__gte=min(lat_a, lat_b),
                    lat__lte=max(lat_a, lat_b),
                    lon__gte=min(lon_a, lon_b),
                    lon__lte=max(lon_a, lon_b),
                )
        except (TypeError, ValueError):
            pass
        return qs


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
    queryset = Shipment.objects.select_related("client", "carrier").prefetch_related("stops")
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_serializer_class(self):
        if self.action == "nearby":
            return ShipmentNearbySerializer
        if self.action == "list":
            return ShipmentDetailSerializer
        if self.action == "create":
            return ShipmentCreateSerializer
        if self.action in ("retrieve", "accept", "advance"):
            return ShipmentDetailSerializer
        return ShipmentDetailSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if self.action == "nearby":
            try:
                ctx["user_lat"] = float(self.request.query_params.get("lat"))
                ctx["user_lon"] = float(self.request.query_params.get("lon"))
            except (TypeError, ValueError):
                ctx["user_lat"] = ctx["user_lon"] = None
        return ctx

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        if not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.is_staff:
            return qs
        return qs.exclude(title__startswith="DEMO ").filter(Q(client=user) | Q(carrier=user)).distinct()

    def perform_create(self, serializer):
        rid = _rid(self.request)
        try:
            shipment = serializer.save()
            _broadcast(shipment)
            logger.info(
                "shipment_created",
                extra={"request_id": rid, "shipment_id": shipment.id, "user_id": self.request.user.id},
            )
        except Exception:
            logger.exception(
                "shipment_create_failed",
                extra={"request_id": rid, "user_id": self.request.user.id},
            )
            raise

    @extend_schema(
        tags=["Shipments"],
        summary="Курьер принимает посылку",
        responses=ShipmentDetailSerializer,
    )
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        rid = _rid(request)
        user = request.user

        if getattr(user, "role", None) != User.Roles.CARRIER:
            logger.warning(
                "shipment_accept_forbidden",
                extra={"request_id": rid, "user_id": user.id, "shipment_id": pk},
            )
            return response.Response({"detail": "only_for_carrier"}, status=status.HTTP_403_FORBIDDEN)

        with transaction.atomic():
            shipment = (
                Shipment.objects.select_for_update()
                .select_related("client", "carrier")
                .prefetch_related("stops")
                .filter(pk=pk)
                .first()
            )
            if not shipment:
                return response.Response({"detail": "not_found"}, status=status.HTTP_404_NOT_FOUND)
            if shipment.client_id == user.id:
                return response.Response(
                    {"detail": "client_cannot_accept_own_shipment"},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if shipment.status != Shipment.Status.PENDING or shipment.carrier_id is not None:
                return response.Response({"detail": "already_accepted"}, status=status.HTTP_409_CONFLICT)

            shipment.carrier = user
            shipment.status = Shipment.Status.ASSIGNED
            shipment.save(update_fields=["carrier", "status"])

        _broadcast(shipment)
        notify_shipment_status(shipment)

        logger.info(
            "shipment_accepted",
            extra={"request_id": rid, "user_id": user.id, "shipment_id": shipment.id},
        )
        return response.Response(ShipmentDetailSerializer(shipment).data)

    @extend_schema(
        tags=["Shipments"],
        summary="Смена статуса",
        request=inline_serializer(
            name="ShipmentSetStatusRequest",
            fields={"status": serializers.ChoiceField(choices=[c for c, _ in Shipment.Status.choices])},
        ),
        responses=ShipmentDetailSerializer,
    )
    @action(detail=True, methods=["post"])
    def set_status(self, request, pk=None):
        rid = _rid(request)
        s = self.get_object()
        new_status = request.data.get("status")

        old_status = s.status
        allowed = {
            Shipment.Status.PENDING: {Shipment.Status.CANCELED},
            Shipment.Status.ASSIGNED: {
                Shipment.Status.PENDING,
                Shipment.Status.IN_TRANSIT,
                Shipment.Status.CANCELED,
            },
            Shipment.Status.IN_TRANSIT: {Shipment.Status.COMPLETED, Shipment.Status.CANCELED},
            Shipment.Status.COMPLETED: set(),
            Shipment.Status.CANCELED: set(),
        }

        if new_status not in Shipment.Status.values:
            return response.Response({"detail": "bad_status"}, status=status.HTTP_400_BAD_REQUEST)
        if s.client_id == request.user.id and new_status not in {
            Shipment.Status.CANCELED,
            Shipment.Status.PENDING,
        }:
            return response.Response(
                {"detail": "only_carrier_can_set_this_status"},
                status=status.HTTP_403_FORBIDDEN,
            )
        if s.carrier_id and s.carrier_id != request.user.id and not request.user.is_staff:
            return response.Response({"detail": "only_assigned_carrier"}, status=status.HTTP_403_FORBIDDEN)
        if new_status not in allowed.get(old_status, set()):
            return response.Response({"detail": "status_transition_not_allowed"}, status=status.HTTP_409_CONFLICT)

        if new_status == Shipment.Status.COMPLETED:
            _complete_shipment_if_needed(s)
        else:
            s.status = new_status
            s.save(update_fields=["status"])
            if new_status != old_status:
                notify_shipment_status(s)

        _broadcast(s)

        logger.info(
            "shipment_status_changed",
            extra={
                "request_id": rid,
                "shipment_id": s.id,
                "user_id": request.user.id,
                "old_status": old_status,
                "new_status": s.status,
            },
        )
        return response.Response(ShipmentDetailSerializer(s).data)

    @extend_schema(
        tags=["Shipments"],
        summary="Квота по координатам (расчёт стоимости маршрута)",
        request=QuoteInSerializer,
        responses=QuoteOutSerializer,
    )
    @action(detail=False, methods=["post"])
    def quote(self, request):
        rid = _rid(request)
        ser = QuoteInSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        stops = list(data["stops"])
        if data.get("return_to_start"):
            stops.append(stops[0])

        if len(stops) < 2:
            logger.warning(
                "quote_invalid_stops",
                extra={"request_id": rid, "user_id": request.user.id},
            )
            return response.Response({"detail": "Нужно минимум 2 точки."}, status=400)

        geoms = [(p["lat"], p["lon"]) for p in stops]
        dist_km = Decimal(str(polyline_len_km(geoms))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        config = GlobalDeliveryConfig.get_config()
        base_price = Decimal(config.base_price)
        per_km_price = Decimal(config.per_km_price)
        min_fare = Decimal(config.min_fare)

        cost = base_price + per_km_price * dist_km
        cost = cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        if cost < min_fare:
            cost = min_fare

        logger.info(
            "quote_calculated",
            extra={
                "request_id": rid,
                "user_id": request.user.id,
                "distance_km": str(dist_km),
                "estimated_fare": int(cost),
            },
        )
        return response.Response(QuoteOutSerializer({"distance_km": dist_km, "estimated_fare": int(cost)}).data)

    @extend_schema(
        tags=["Shipments"],
        summary="Ближайшие заказы для курьера",
        parameters=[
            OpenApiParameter(
                "lat",
                OpenApiTypes.FLOAT,
                OpenApiParameter.QUERY,
                description="Широта курьера",
                required=True,
            ),
            OpenApiParameter(
                "lon",
                OpenApiTypes.FLOAT,
                OpenApiParameter.QUERY,
                description="Долгота курьера",
                required=True,
            ),
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
        responses=OpenApiResponse(
            response=ShipmentNearbySerializer(many=True),
            description="Пагинированный список ближайших доставок",
        ),
    )
    @action(detail=False, methods=["get"], url_path="nearby")
    def nearby(self, request):
        rid = _rid(request)
        try:
            lat = float(request.query_params.get("lat", 0))
            lon = float(request.query_params.get("lon", 0))
        except (ValueError):
            lat, lon = 0.0, 0.0

        # Поиск завершенных заказов или тех, что в ожидании.
        # Теперь фильтруем по Бишкеку и показываем всем онлайн курьерам.
        qs = (
            Shipment.objects.filter(status=Shipment.Status.PENDING, carrier__isnull=True)
            .exclude(title__startswith="DEMO ")
            .prefetch_related("stops")
            .order_by("created_at")
        )

        # Оставляем только заказы, где первая точка (забор) в Бишкеке
        filtered_ids = []
        for s in qs:
            first_stop = s.stops.order_by("position").first()
            if first_stop and first_stop.lat and first_stop.lon:
                if is_in_bishkek(float(first_stop.lat), float(first_stop.lon)):
                    filtered_ids.append(s.id)
        
        qs = qs.filter(id__in=filtered_ids)

        page = self.paginate_queryset(qs)
        serializer = self.get_serializer(
            page or qs,
            many=True,
            context={"request": request, "user_lat": lat, "user_lon": lon},
        )

        logger.info(
            "nearby_listed",
            extra={"request_id": rid, "user_id": request.user.id, "lat": lat, "lon": lon, "count": qs.count()},
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return response.Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="pay/finik")
    def pay_finik(self, request, pk=None):
        rid = _rid(request)
        s = self.get_object()

        if s.client_id != request.user.id:
            logger.warning(
                "pay_finik_forbidden",
                extra={"request_id": rid, "user_id": request.user.id, "shipment_id": s.id},
            )
            return response.Response({"detail": "only_for_client"}, status=status.HTTP_403_FORBIDDEN)

        if s.is_paid:
            logger.info(
                "pay_finik_already_paid",
                extra={"request_id": rid, "user_id": request.user.id, "shipment_id": s.id},
            )
            return response.Response({"detail": "already_paid"}, status=status.HTTP_409_CONFLICT)

        amount = int(s.final_fare or s.estimated_fare or 0)
        if amount <= 0:
            logger.warning(
                "pay_finik_bad_amount",
                extra={"request_id": rid, "user_id": request.user.id, "shipment_id": s.id, "amount": amount},
            )
            return response.Response({"detail": "bad_amount"}, status=status.HTTP_400_BAD_REQUEST)

        finik_request_id = uuid.uuid4().hex

        attempt = PaymentAttempt.objects.create(
            provider="FINIK",
            shipment=s,
            amount=amount,
            currency=getattr(settings, "FINIK_CURRENCY", "KGS"),
            finik_request_id=finik_request_id,
            status=PaymentAttempt.Status.PENDING,
        )

        callback_url = settings.FINIK_CALLBACK_URL

        logger.info(
            "pay_finik_created",
            extra={
                "request_id": rid,
                "user_id": request.user.id,
                "shipment_id": s.id,
                "attempt_id": str(attempt.id),
                "amount": amount,
            },
        )

        return response.Response(
            {
                "paymentId": str(attempt.id),
                "finikRequestId": finik_request_id,
                "callbackUrl": callback_url,
                "requiredFields": {"paymentId": str(attempt.id), "shipmentId": str(s.id)},
                "amount": amount,
                "currency": attempt.currency,
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        tags=["Shipments"],
        summary="Курьер продвигает доставку к следующей точке / завершает доставку",
        request=None,
        responses=ShipmentDetailSerializer,
    )
    @action(detail=True, methods=["post"])
    def advance(self, request, pk=None):
        rid = _rid(request)
        s = self.get_object()
        if s.carrier_id != request.user.id and not request.user.is_staff:
            return response.Response({"detail": "only_assigned_carrier"}, status=status.HTTP_403_FORBIDDEN)
        if s.status not in (Shipment.Status.ASSIGNED, Shipment.Status.IN_TRANSIT):
            return response.Response({"detail": "status_transition_not_allowed"}, status=status.HTTP_409_CONFLICT)
        prev_index = s.current_stop_index
        prev_status = s.status

        nxt = s.next_stop()
        if not nxt:
            if s.status != Shipment.Status.COMPLETED:
                _complete_shipment_if_needed(s)
                _increment_carrier_rating(s)
                notify_shipment_status(s)
        else:
            if s.status == Shipment.Status.ASSIGNED:
                s.status = Shipment.Status.IN_TRANSIT
            s.current_stop_index += 1
            if s.current_stop_index >= s.stops.count():
                if s.status != Shipment.Status.COMPLETED:
                    _complete_shipment_if_needed(s)
                    _increment_carrier_rating(s)
                    notify_shipment_status(s)
            else:
                s.save(update_fields=["current_stop_index", "status"])
                notify_shipment_status(s)

        _broadcast(s)

        logger.info(
            "shipment_advanced",
            extra={
                "request_id": rid,
                "user_id": request.user.id,
                "shipment_id": s.id,
                "prev_index": prev_index,
                "new_index": s.current_stop_index,
                "prev_status": prev_status,
                "new_status": s.status,
            },
        )
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
        rid = _rid(request)
        qs = self.get_queryset().filter(status=Shipment.Status.COMPLETED).order_by("-created_at")

        page = self.paginate_queryset(qs)
        if page is not None:
            ser = ShipmentCardSerializer(page, many=True)
            logger.info(
                "history_listed",
                extra={"request_id": rid, "user_id": request.user.id, "count": len(ser.data)},
            )
            return self.get_paginated_response(ser.data)

        ser = ShipmentCardSerializer(qs, many=True)
        logger.info(
            "history_listed",
            extra={"request_id": rid, "user_id": request.user.id, "count": len(ser.data)},
        )
        return response.Response(ser.data)


@extend_schema(tags=["Гео"])
class ReverseGeocodeView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="Реверс-геокодинг (координаты → адрес)",
        parameters=[
            OpenApiParameter(name="lat", required=True, type=float, description="Широта"),
            OpenApiParameter(name="lon", required=True, type=float, description="Долгота"),
        ],
        responses={
            200: {
                "type": "object",
                "properties": {"address": {"type": "string"}},
            },
            400: {"type": "object", "properties": {"error": {"type": "string"}}},
            502: {"type": "object", "properties": {"error": {"type": "string"}}},
        },
        examples=[OpenApiExample("Пример запроса", value={"lat": 55.75, "lon": 37.61})],
    )
    def get(self, request):
        rid = _rid(request)
        lat = request.query_params.get("lat")
        lon = request.query_params.get("lon")

        if not lat or not lon:
            logger.warning("reverse_geocode_missing_params", extra={"request_id": rid})
            return Response({"error": "lat and lon are required"}, status=400)

        api_key = getattr(settings, "YANDEX_API_KEY", None)
        if not api_key:
            logger.error("reverse_geocode_no_api_key", extra={"request_id": rid})
            return Response({"error": "yandex_api_key_not_configured"}, status=502)

        url = f"https://geocode-maps.yandex.ru/1.x/?apikey={api_key}&geocode={lon},{lat}&format=json"

        try:
            r = requests.get(url, timeout=7)
            r.raise_for_status()
            data = r.json()
            address = (
                data["response"]["GeoObjectCollection"]["featureMember"][0]["GeoObject"]["metaDataProperty"][
                    "GeocoderMetaData"
                ]["text"]
            )
            logger.info("reverse_geocode_ok", extra={"request_id": rid})
            return Response({"address": address})
        except Exception:
            logger.exception("reverse_geocode_failed", extra={"request_id": rid})
            return Response({"error": "reverse_geocode_failed"}, status=502)


@extend_schema(tags=["Гео"])
class AutocompleteView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="Автодополнение адреса на Дордое (2ГИС)",
        description="Поиск по Дордою через 2ГИС. Можно передавать market/container/passage или свободный текст q.",
        parameters=[
            OpenApiParameter(name="market", required=False, type=str),
            OpenApiParameter(name="container", required=False, type=str),
            OpenApiParameter(name="passage", required=False, type=str),
            OpenApiParameter(name="q", required=False, type=str),
            OpenApiParameter(name="page_size", required=False, type=int, description="1–20, default 5"),
        ],
        responses={
            200: {
                "type": "object",
                "properties": {"results": {"type": "array"}},
            },
            400: {"type": "object", "properties": {"detail": {"type": "string"}}},
            502: {"type": "object", "properties": {"detail": {"type": "string"}}},
        },
        examples=[
            OpenApiExample("По market/container/passage", value={"market": "Алкан базары", "container": "74", "passage": "8"}),
            OpenApiExample("По свободному тексту", value={"q": "Контейнер 74, 8 проход"}),
        ],
    )
    def get(self, request):
        rid = _rid(request)
        market = request.query_params.get("market")
        container = request.query_params.get("container")
        passage = request.query_params.get("passage")
        q = request.query_params.get("q")

        page_size = request.query_params.get("page_size")
        try:
            page_size_int = int(page_size) if page_size is not None else 5
        except (TypeError, ValueError):
            page_size_int = 5
        page_size_int = max(1, min(page_size_int, 20))

        if not any([market, container, passage, q]):
            logger.warning("autocomplete_missing_query", extra={"request_id": rid})
            return Response({"detail": "нужно хотя бы одно из: market/container/passage/q"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            results = twogis_autocomplete(
                market=market,
                container=container,
                passage=passage,
                q=q,
                page_size=page_size_int,
            )
            logger.info(
                "autocomplete_ok",
                extra={
                    "request_id": rid,
                    "page_size": page_size_int,
                    "has_market": bool(market),
                    "has_container": bool(container),
                    "has_passage": bool(passage),
                    "has_q": bool(q),
                    "results_count": len(results),
                },
            )
            return Response({"results": results})
        except requests.HTTPError as e:
            logger.warning(
                "autocomplete_2gis_http_error",
                extra={"request_id": rid, "status_code": getattr(e.response, "status_code", None)},
            )
            return Response({"detail": "2gis_error"}, status=status.HTTP_502_BAD_GATEWAY)
        except ValueError:
            logger.warning("autocomplete_2gis_bad_json", extra={"request_id": rid})
            return Response({"detail": "2gis_bad_json"}, status=status.HTTP_502_BAD_GATEWAY)
        except requests.RequestException:
            logger.warning("autocomplete_2gis_request_failed", extra={"request_id": rid})
            return Response({"detail": "2gis_request_failed"}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception:
            logger.exception("autocomplete_unexpected_error", extra={"request_id": rid})
            return Response({"detail": "unexpected_error"}, status=status.HTTP_502_BAD_GATEWAY)


@extend_schema(
    tags=["Статистика"],
    summary="Дневная статистика курьера",
    parameters=[
        OpenApiParameter(
            name="date",
            description="Дата в формате YYYY-MM-DD (по умолчанию сегодня)",
            required=False,
            type=str,
        ),
    ],
    responses={
        200: {
            "type": "object",
            "properties": {
                "date": {"type": "string"},
                "gross_total": {"type": "integer"},
                "earned": {"type": "integer"},
                "commission": {"type": "integer"},
                "clients": {"type": "integer"},
                "change_percent_vs_prev": {"type": "integer", "nullable": True},
            },
        }
    },
)
class CarrierDailyStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        rid = _rid(request)
        user = request.user

        if getattr(user, "role", None) != User.Roles.CARRIER:
            logger.warning("carrier_stats_forbidden", extra={"request_id": rid, "user_id": user.id})
            return Response({"detail": "only_for_carrier"}, status=status.HTTP_403_FORBIDDEN)

        date_str = request.query_params.get("date")
        if date_str:
            try:
                day = _date.fromisoformat(date_str)
            except ValueError:
                logger.warning("carrier_stats_bad_date", extra={"request_id": rid, "user_id": user.id, "date": date_str})
                return Response({"detail": "bad_date_format"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            day = timezone.localdate()

        data = carrier_daily_stats_with_change(carrier_id=user.id, day=day)
        logger.info("carrier_stats_ok", extra={"request_id": rid, "user_id": user.id, "date": str(day)})
        return Response(data)


@extend_schema(tags=["Служба поддержки"])
class SupportView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({
            "phone": "+996 555 123 456",
            "telegram": "@dogo_support",
            "working_hours": "24/7",
            "message": "Мы всегда на связи!"
        })
