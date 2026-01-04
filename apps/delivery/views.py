from __future__ import annotations
import re
from decimal import Decimal, ROUND_HALF_UP
import requests
from apps.notification.events import (
    notify_shipment_offer_for_carrier,
    notify_shipment_status,
    notify_shipment_canceled,
)
from asgiref.sync import async_to_sync
from django.utils import timezone
from channels.layers import get_channel_layer
from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import viewsets, permissions, response, status, serializers
from rest_framework.decorators import action
from .stats import carrier_daily_stats_with_change
from apps.users.models import UserProfile, User
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
    OpenApiTypes,
    inline_serializer,
    OpenApiExample
)
from datetime import date as _date
import logging
import uuid
from .models import Shipment, ShipmentStop, CourierSegment
from .serializer import (
    CourierSegmentSerializer,
    ShipmentCreateSerializer,
    ShipmentDetailSerializer,
    ShipmentStatusSerializer,
    ShipmentCardSerializer,
    QuoteInSerializer,
    QuoteOutSerializer,
    ShipmentNearbySerializer
)
from .geo import polyline_len_km, haversine_m, bbox_deltas
from .pagination import StandardResultsSetPagination
from apps.users.models import User
from apps.payments.models import *
logger = logging.getLogger(__name__)


def _broadcast(shipment: Shipment):
    layer = get_channel_layer()
    data = ShipmentDetailSerializer(shipment).data
    async_to_sync(layer.group_send)(
        f"shipment_{shipment.id}",
        {"type": "shipment.event", "payload": data},
    )


@extend_schema_view(
    list=extend_schema(
        tags=["Shipments"],
        summary="Список активных тарифных сегментов доставки",
        description="Возвращает все активные сегменты (тарифы) для доставки.",
        responses=CourierSegmentSerializer(many=True),
    ),
    retrieve=extend_schema(
        tags=["Shipments"],
        summary="Детали тарифного сегмента",
        responses=CourierSegmentSerializer,
    ),
)
class CourierSegmentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CourierSegment.objects.filter(is_active=True).order_by("order", "name")
    serializer_class = CourierSegmentSerializer
    permission_classes = [permissions.IsAuthenticated]





def _increment_carrier_rating(shipment):
    carrier = shipment.carrier
    if not carrier:
        return
    if getattr(carrier, "role", None) != User.Roles.CARRIER:
        return

    profile, _ = UserProfile.objects.get_or_create(user=carrier)
    profile.rate = (profile.rate or 0) + 1
    profile.client_rate_count = (profile.client_rate_count or 0) + 1
    profile.save(update_fields=["rate", "client_rate_count"])


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
        if self.action == "nearby":
            return ShipmentNearbySerializer
        elif self.action in ("list",):
            return ShipmentDetailSerializer
        elif self.action == "create":
            return ShipmentCreateSerializer
        elif self.action in ("retrieve", "accept", "advance"):
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
        user = request.user
        if getattr(user, "role", None) != User.Roles.CARRIER:
            return response.Response(
                {"detail": "only_for_carrier"},
                status=status.HTTP_403_FORBIDDEN,
            )

        shipment = get_object_or_404(
            Shipment,
            pk=pk,
            status=Shipment.Status.PENDING,
            carrier__isnull=True,
        )

        shipment.carrier = user
        shipment.status = Shipment.Status.ASSIGNED
        shipment.save(update_fields=["carrier", "status"])

        _broadcast(shipment)
        notify_shipment_status(shipment)

        return response.Response(ShipmentDetailSerializer(shipment).data)



    @extend_schema(
        tags=["Shipments"],
        summary="Смена статуса",
        request=inline_serializer(
            name="ShipmentSetStatusRequest",
            fields={
                "status": serializers.ChoiceField(choices=[c for c, _ in Shipment.Status.choices]),
            },
        ),
        responses=ShipmentDetailSerializer,
    )
    @action(detail=True, methods=["post"])
    def set_status(self, request, pk=None):
        s = self.get_object()
        new_status = request.data.get("status")

        old_status = s.status

        if new_status == Shipment.Status.COMPLETED:
            _complete_shipment_if_needed(s)
        else:
            s.status = new_status
            s.save(update_fields=["status"])
            if new_status != old_status:
                notify_shipment_status(s)

        _broadcast(s)
        return response.Response(ShipmentDetailSerializer(s).data)




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
        try:
            lat = float(request.query_params["lat"])
            lon = float(request.query_params["lon"])
        except (KeyError, ValueError):
            return response.Response(
                {"detail": "lat и lon обязательны"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = Shipment.objects.filter(
            status=Shipment.Status.PENDING,
            carrier__isnull=True,
        ).order_by("created_at")

        page = self.paginate_queryset(qs)
        serializer = self.get_serializer(
            page or qs,
            many=True,
            context={"request": request, "user_lat": lat, "user_lon": lon},
        )

        if page is not None:
            return self.get_paginated_response(serializer.data)

        return response.Response(serializer.data)




    @action(detail=True, methods=["post"], url_path="pay/finik")
    def pay_finik(self, request, pk=None):
        s = self.get_object()

        if s.client_id != request.user.id:
            return response.Response({"detail": "only_for_client"}, status=status.HTTP_403_FORBIDDEN)

        if s.is_paid:
            return response.Response({"detail": "already_paid"}, status=status.HTTP_409_CONFLICT)

        amount = int(s.final_fare or s.estimated_fare or 0)
        if amount <= 0:
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

        return response.Response({
            "paymentId": str(attempt.id),
            "finikRequestId": finik_request_id,
            "callbackUrl": callback_url,
            "requiredFields": {
                "paymentId": str(attempt.id),
                "shipmentId": str(s.id),
            },
            "amount": amount,
            "currency": attempt.currency,
        }, status=status.HTTP_201_CREATED)





    @extend_schema(
        tags=["Shipments"],
        summary="Курьер продвигает доставку к следующей точке / завершает доставку",
        request=None,
        responses=ShipmentDetailSerializer,
    )
    @action(detail=True, methods=["post"])
    def advance(self, request, pk=None):
        s = self.get_object()
        nxt = s.next_stop()
        if not nxt:
            if s.status != Shipment.Status.COMPLETED:
                s.status = Shipment.Status.COMPLETED
                s.finalize()
                s.save(update_fields=["status", "final_fare", "finished_at"])
                _increment_carrier_rating(s)
                notify_shipment_status(s)
        else:
            s.current_stop_index += 1
            if s.current_stop_index >= s.stops.count():
                if s.status != Shipment.Status.COMPLETED:
                    s.status = Shipment.Status.COMPLETED
                    s.finalize()
                    s.save(
                        update_fields=[
                            "current_stop_index",
                            "status",
                            "final_fare",
                            "finished_at",
                        ]
                    )
                    _increment_carrier_rating(s)
                    notify_shipment_status(s)
            else:
                s.save(update_fields=["current_stop_index"])
                notify_shipment_status(s)

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

TWOGIS_API_KEY = "c65e5972-5592-4197-9dd2-e43bdcfd83fd"


YANDEX_API_KEY = "bc8fb1c9-1361-46e4-b872-a95d055823e8"

@extend_schema(tags=["Гео"])
class ReverseGeocodeView(APIView):
    permission_classes = [permissions.AllowAny]
    @extend_schema(
        summary="Реверс-геокодинг (координаты → адрес)",
        description="Принимает широту и долготу, обращается к API Яндекса и возвращает текстовый адрес.",
        parameters=[
            OpenApiParameter(
                name="lat",
                required=True,
                type=float,
                description="Широта"
            ),
            OpenApiParameter(
                name="lon",
                required=True,
                type=float,
                description="Долгота"
            ),
        ],
        responses={
            200: {
                "type": "object",
                "properties": {
                    "address": {
                        "type": "string",
                        "example": "Россия, Москва, Красная площадь"
                    }
                }
            },
            400: {
                "type": "object",
                "properties": {
                    "error": {"type": "string"}
                }
            }
        },
        examples=[
            OpenApiExample(
                "Пример запроса",
                summary="Пример координат",
                value={"lat": 55.75, "lon": 37.61}
            )
        ]
    )
    def get(self, request):
        lat = request.query_params.get('lat')
        lon = request.query_params.get('lon')

        if not lat or not lon:
            return Response({"error": "lat and lon are required"}, status=400)

        url = (
            f"https://geocode-maps.yandex.ru/1.x/"
            f"?apikey={YANDEX_API_KEY}&geocode={lon},{lat}&format=json"
        )

        r = requests.get(url)
        data = r.json()

        try:
            address = (
                data["response"]["GeoObjectCollection"]["featureMember"][0]
                ["GeoObject"]["metaDataProperty"]["GeocoderMetaData"]["text"]
            )
        except:
            address = None

        return Response({"address": address})




DORDOI_LON = 74.6217
DORDOI_LAT = 42.9367
DORDOI_RADIUS = 4000

logger = logging.getLogger(__name__)

_MARKET_WORDS = (
    "дордой",
    "рынок дордой",
    "мурас спорт",
    "алкан базары",
    "рынок",
    "базар",
    "базары",
)
_RE_PASSAGE = re.compile(r"(\d+)\s*[-–]?\s*й?\s*проход", re.IGNORECASE)
_RE_CONTAINER = re.compile(r"контейнер\s+(\d+)", re.IGNORECASE)


def _split_market_container_passage(title: str, address: str) -> tuple[str | None, str | None, str | None]:
    full = f"{title}, {address}".strip(", ")

    market = None
    container = None
    passage = None

    parts = [p.strip() for p in full.split(",") if p.strip()]
    markets = [
        p
        for p in parts
        if any(w in p.lower() for w in _MARKET_WORDS)
    ]
    if markets:
        market = markets[-1]

    m = _RE_CONTAINER.search(full)
    if m:
        container = m.group(1)

    m = _RE_PASSAGE.search(full)
    if m:
        passage = m.group(1)

    return market, container, passage


def _build_query_text(market: str | None, container: str | None, passage: str | None, q: str | None) -> str | None:
    market = (market or "").strip()
    container = (container or "").strip()
    passage = (passage or "").strip()
    q = (q or "").strip()

    if market:
        parts = [market]
        if container:
            parts.append(f"контейнер {container}")
        if passage:
            parts.append(f"{passage} проход")
        return ", ".join(parts)

    if q:
        return q

    return None


@extend_schema(tags=["Гео"])
class AutocompleteView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="Автодополнение адреса на Дордое (2ГИС)",
        description=(
            "Поиск по базару Дордой через 2ГИС. Можно передавать market/container/passage "
            "или свободный текст q. Результаты ограничены районом Дордоя."
        ),
        parameters=[
            OpenApiParameter(
                name="market",
                required=False,
                type=str,
                description="Название базара (Мурас спорт, Алкан базары, и т.п.)",
            ),
            OpenApiParameter(
                name="container",
                required=False,
                type=str,
                description="Номер контейнера (например, 74)",
            ),
            OpenApiParameter(
                name="passage",
                required=False,
                type=str,
                description="Номер прохода (например, 8)",
            ),
            OpenApiParameter(
                name="q",
                required=False,
                type=str,
                description="Свободный текст, если не используешь market/container/passage",
            ),
        ],
        responses={
            200: {
                "type": "object",
                "properties": {
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "address": {"type": "string"},
                                "market": {"type": "string", "nullable": True},
                                "container": {"type": "string", "nullable": True},
                                "passage": {"type": "string", "nullable": True},
                                "lat": {"type": "number", "format": "float"},
                                "lon": {"type": "number", "format": "float"},
                            },
                        },
                    }
                },
            },
            400: {
                "type": "object",
                "properties": {
                    "detail": {"type": "string"},
                },
            },
        },
        examples=[
            OpenApiExample(
                "По market/container/passage",
                value={"market": "Алкан базары", "container": "74", "passage": "8"},
            ),
            OpenApiExample(
                "По свободному тексту",
                value={"q": "Контейнер 74, 8 проход"},
            ),
        ],
    )
    def get(self, request):
        market = request.query_params.get("market")
        container = request.query_params.get("container")
        passage = request.query_params.get("passage")
        q = request.query_params.get("q")

        query_text = _build_query_text(market, container, passage, q)
        if not query_text:
            return Response(
                {"detail": "нужно хотя бы одно из: market или q"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        url = "https://catalog.api.2gis.com/3.0/items/geocode"
        params = {
            "key": TWOGIS_API_KEY,
            "q": query_text,
            "fields": "items.point,items.full_address_name",
            "page_size": 5,
            "point": f"{DORDOI_LON},{DORDOI_LAT}",
            "radius": DORDOI_RADIUS,
            "sort": "distance",
            "search_nearby": "true",
            "locale": "ru_KG",
        }

        try:
            r = requests.get(url, params=params, timeout=5)
        except requests.RequestException:
            return Response(
                {"detail": "2gis_request_failed"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if r.status_code != 200:
            return Response(
                {
                    "detail": "2gis_error",
                    "status_code": r.status_code,
                    "body": r.text[:200],
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        try:
            data = r.json()
        except ValueError:
            return Response(
                {
                    "detail": "2gis_bad_json",
                    "body": r.text[:200],
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        items = (data.get("result") or {}).get("items") or []

        results = []
        for item in items:
            name = item.get("name") or ""
            addr = item.get("full_address_name") or ""
            point = item.get("point") or {}
            lon = point.get("lon")
            lat = point.get("lat")

            mkt, cont, pas = _split_market_container_passage(name, addr)

            results.append(
                {
                    "title": name or addr,
                    "address": addr,
                    "market": mkt,
                    "container": cont,
                    "passage": pas,
                    "lat": lat,
                    "lon": lon,
                }
            )

        return Response({"results": results})


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
                "date": {"type": "string", "example": "2025-09-24"},
                "gross_total": {"type": "integer", "example": 7000},
                "earned": {"type": "integer", "example": 6080},
                "commission": {"type": "integer", "example": 920},
                "clients": {"type": "integer", "example": 8},
                "change_percent_vs_prev": {
                    "type": "integer",
                    "nullable": True,
                    "example": 23,
                },
            },
        }
    },
)
class CarrierDailyStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        if getattr(user, "role", None) != User.Roles.CARRIER:
            return Response(
                {"detail": "only_for_carrier"},
                status=status.HTTP_403_FORBIDDEN,
            )

        date_str = request.query_params.get("date")
        if date_str:
            try:
                day = _date.fromisoformat(date_str)
            except ValueError:
                return Response(
                    {"detail": "bad_date_format"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            day = timezone.localdate()

        data = carrier_daily_stats_with_change(
            carrier_id=user.id,
            day=day,
        )
        return Response(data)
