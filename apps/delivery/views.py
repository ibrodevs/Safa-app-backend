from __future__ import annotations

import logging
import uuid
from datetime import date as _date
from decimal import Decimal, ROUND_HALF_UP

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Count, IntegerField, Prefetch, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.urls import reverse
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
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notification.events import notify_shipment_offer_for_carrier, notify_shipment_status
from apps.payments.models import AmanatPaymentAttempt, PaymentAttempt
from apps.payments.amounts import (
    effective_finik_test_amount,
    effective_safa_test_price,
    payment_amount_for_shipment,
)
from apps.payments.settlement import complete_paid_shipment
from apps.users.models import User
from .geocoding import twogis_autocomplete
from .lifecycle import ShipmentFareUnavailable, mark_shipment_awaiting_payment
from .rating import apply_rating_for_completed_shipment
from .realtime import broadcast_courier_position, broadcast_shipment
from .reverse_geocoding import reverse_geocode_address
from .operations import cancel_shipment
from .geo import haversine_m, polyline_len_km
from .models import AmanatCampaign, AmanatCategory, AmanatDonation, Bazar, Container, CourierPosition, GlobalDeliveryConfig, Passage, Shipment, ShipmentStop
from .pagination import StandardResultsSetPagination
from .serializer import (
    AmanatCampaignSerializer,
    AmanatCategorySerializer,
    AmanatDonateSerializer,
    AmanatDonationSerializer,
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


def _demo_shipment_q() -> Q:
    return Q(is_demo=True)


def _mark_work_done(s: Shipment) -> None:
    """Freeze the fare and, for legacy prepaid orders, settle immediately."""

    mark_shipment_awaiting_payment(s)
    if not s.is_paid:
        return

    successful_attempt = (
        s.payment_attempts.filter(status=PaymentAttempt.Status.SUCCEEDED)
        .order_by("-updated_at")
        .first()
    )
    if successful_attempt is None:
        logger.error("paid_shipment_has_no_successful_attempt", extra={"shipment_id": s.id})
        return

    complete_paid_shipment(shipment=s, payment_attempt=successful_attempt)
    apply_rating_for_completed_shipment(s)


def _quote_fixed_bazar_fare(stops: list[dict]) -> int | None:
    bazaars = list(
        Bazar.objects.select_related("district_tariff").filter(
            top_left_lat__isnull=False,
            top_left_lon__isnull=False,
            bottom_right_lat__isnull=False,
            bottom_right_lon__isnull=False,
        )
    )
    if not bazaars:
        return None

    prices: list[int] = []
    for stop in stops:
        lat = stop.get("lat")
        lon = stop.get("lon")
        matched_price = None
        for bazar in bazaars:
            if (float(bazar.bottom_right_lat) <= lat <= float(bazar.top_left_lat)) and (
                float(bazar.top_left_lon) <= lon <= float(bazar.bottom_right_lon)
            ):
                matched_price = bazar.effective_fixed_price
                break
        if matched_price is None:
            return None
        prices.append(int(matched_price))

    return max(prices) if prices else None


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
    queryset = Passage.objects.select_related("bazar").all().order_by("bazar__name", "district", "number")
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
            qs = qs.filter(
                Q(number__icontains=q)
                | Q(district__icontains=q)
                | Q(bazar__name__icontains=q)
            )
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
    list=extend_schema(tags=["Amanat"], summary="Категории Safa Amanat"),
)
class AmanatCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AmanatCategory.objects.filter(is_active=True).order_by("sort_order", "name")
    serializer_class = AmanatCategorySerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None


@extend_schema_view(
    list=extend_schema(
        tags=["Amanat"],
        summary="Активные сборы Safa Amanat",
        parameters=[
            OpenApiParameter(name="category", required=False, type=str, description="slug категории"),
            OpenApiParameter(name="featured", required=False, type=bool, description="Только главный сбор"),
        ],
        responses=AmanatCampaignSerializer,
    ),
    retrieve=extend_schema(tags=["Amanat"], responses=AmanatCampaignSerializer),
)
class AmanatCampaignViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        AmanatCampaign.objects.select_related("category")
        .annotate(
            _paid_donations_amount=Coalesce(
                Sum(
                    "donations__amount",
                    filter=Q(donations__status=AmanatDonation.Status.PAID),
                ),
                Value(0),
                output_field=IntegerField(),
            ),
            _paid_donations_count=Count(
                "donations",
                filter=Q(donations__status=AmanatDonation.Status.PAID),
            ),
        )
        .prefetch_related(
            Prefetch(
                "donations",
                queryset=AmanatDonation.objects.filter(
                    status=AmanatDonation.Status.PAID,
                )
                .select_related("donor")
                .order_by("-created_at")[:5],
                to_attr="_latest_paid_donations",
            )
        )
        .filter(status=AmanatCampaign.Status.ACTIVE)
        .order_by("sort_order", "-created_at")
    )
    serializer_class = AmanatCampaignSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset()
        category = (self.request.query_params.get("category") or "").strip()
        if category:
            qs = qs.filter(category__slug=category)
        featured = (self.request.query_params.get("featured") or "").strip().lower()
        if featured in ("1", "true", "yes"):
            qs = qs.filter(is_featured=True)
        return qs

    @extend_schema(
        tags=["Amanat"],
        request=AmanatDonateSerializer,
        responses={201: AmanatDonationSerializer},
    )
    @action(detail=True, methods=["post"])
    def donate(self, request, pk=None):
        campaign = self.get_object()
        serializer = AmanatDonateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user if request.user.is_authenticated else None
        donor_label = getattr(user, "phone_number", "") if user else ""
        account_id = str(getattr(settings, "FINIK_ACCOUNT_ID", "") or "").strip()
        api_key = str(getattr(settings, "FINIK_API_KEY", "") or "").strip()
        if not account_id or not api_key:
            return Response(
                {"detail": "finik_not_configured"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        requested_amount = int(serializer.validated_data["amount"])
        test_amount = effective_finik_test_amount()
        # Preserve the legacy donation-only override for existing deployments.
        if test_amount is None:
            test_amount = getattr(settings, "FINIK_TEST_AMOUNT", None)
        amount = int(test_amount if test_amount is not None else requested_amount)
        finik_request_id = uuid.uuid4().hex
        with transaction.atomic():
            donation = AmanatDonation.objects.create(
                campaign=campaign,
                donor=user,
                donor_label=donor_label,
                amount=amount,
                is_anonymous=serializer.validated_data.get("is_anonymous", False),
                comment=serializer.validated_data.get("comment", ""),
                status=AmanatDonation.Status.PENDING,
            )
            attempt = AmanatPaymentAttempt.objects.create(
                donation=donation,
                amount=amount,
                currency=getattr(settings, "FINIK_CURRENCY", "KGS"),
                finik_request_id=finik_request_id,
            )

        callback_url = str(
            getattr(settings, "FINIK_CALLBACK_URL", "") or ""
        ).strip() or request.build_absolute_uri(reverse("finik-callback"))
        required_fields = {
            "paymentId": str(attempt.id),
            "finikRequestId": finik_request_id,
            "paymentKind": "amanat",
            "donationId": str(donation.id),
            "campaignId": str(campaign.id),
        }
        return Response(
            {
                "paymentId": str(attempt.id),
                "finikRequestId": finik_request_id,
                "callbackUrl": callback_url,
                "requiredFields": required_fields,
                "amount": amount,
                "currency": attempt.currency,
                "accountId": account_id,
                "donationId": donation.id,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["get"],
        url_path=r"donations/(?P<donation_id>[^/.]+)",
    )
    def donation_status(self, request, pk=None, donation_id=None):
        campaign = self.get_object()
        try:
            donation = campaign.donations.get(id=donation_id, donor=request.user)
        except AmanatDonation.DoesNotExist:
            return Response({"detail": "not_found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(
            AmanatDonationSerializer(
                donation,
                context=self.get_serializer_context(),
            ).data
        )


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
    queryset = Shipment.objects.select_related(
        "client",
        "carrier",
        "carrier_settlement",
    ).prefetch_related(
        Prefetch(
            "stops",
            queryset=ShipmentStop.objects.select_related(
                "container",
                "container__passage",
                "container__passage__bazar",
            ).order_by("position"),
        )
    )
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
        return qs.exclude(_demo_shipment_q()).filter(Q(client=user) | Q(carrier=user)).distinct()

    def perform_create(self, serializer):
        rid = _rid(self.request)
        if (
            getattr(self.request.user, "role", None) != User.Roles.CLIENT
            and not self.request.user.is_staff
        ):
            raise PermissionDenied("only_for_client")
        try:
            shipment = serializer.save()
            broadcast_shipment(shipment)
            notify_shipment_offer_for_carrier(shipment)
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

    def destroy(self, request, *args, **kwargs):
        shipment = self.get_object()
        if shipment.client_id != request.user.id and not request.user.is_staff:
            return response.Response({"detail": "only_for_client"}, status=status.HTTP_403_FORBIDDEN)
        if shipment.status in (
            Shipment.Status.AWAITING_PAYMENT,
            Shipment.Status.COMPLETED,
            Shipment.Status.CANCELED,
        ):
            return response.Response({"detail": "terminal_shipment"}, status=status.HTTP_409_CONFLICT)
        try:
            cancel_shipment(shipment)
        except ValueError:
            return response.Response(
                {"detail": "terminal_shipment"},
                status=status.HTTP_409_CONFLICT,
            )
        return response.Response(status=status.HTTP_204_NO_CONTENT)

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
                Shipment.objects.select_for_update(of=("self",))
                # `carrier` is nullable. PostgreSQL rejects FOR UPDATE when a
                # nullable relation is pulled in through LEFT OUTER JOIN:
                # "FOR UPDATE cannot be applied to the nullable side...".
                # Lock the shipment row itself and load the optional carrier
                # separately when the serializer needs it.
                .select_related("client")
                .prefetch_related("stops")
                .filter(pk=pk)
                .first()
            )
            if not shipment:
                return response.Response({"detail": "not_found"}, status=status.HTTP_404_NOT_FOUND)
            if shipment.is_demo:
                return response.Response({"detail": "demo_shipment_unavailable"}, status=status.HTTP_404_NOT_FOUND)
            if shipment.client_id == user.id:
                return response.Response(
                    {"detail": "client_cannot_accept_own_shipment"},
                    status=status.HTTP_403_FORBIDDEN,
                )
            # Mobile networks may retry the request, and a user can tap twice
            # before the first response arrives. Accepting the same shipment
            # again by its assigned carrier is a successful idempotent action.
            if (
                shipment.carrier_id == user.id
                and shipment.status
                in {
                    Shipment.Status.ASSIGNED,
                    Shipment.Status.IN_TRANSIT,
                    Shipment.Status.AWAITING_PAYMENT,
                    Shipment.Status.COMPLETED,
                }
            ):
                return response.Response(ShipmentDetailSerializer(shipment).data)
            if shipment.status != Shipment.Status.PENDING or shipment.carrier_id is not None:
                return response.Response({"detail": "already_accepted"}, status=status.HTTP_409_CONFLICT)
            # Лента показывает специалисту все свободные заказы, поэтому
            # приём не должен отказывать по типу специализации — иначе
            # карточка видна, а кнопка «Принять» отвечает 403.
            if not user.is_active:
                return response.Response(
                    {"detail": "specialist_not_approved"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            shipment.carrier = user
            shipment.status = Shipment.Status.ASSIGNED
            shipment.save(update_fields=["carrier", "status"])

        broadcast_shipment(shipment)
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
            Shipment.Status.IN_TRANSIT: {
                Shipment.Status.AWAITING_PAYMENT,
                Shipment.Status.CANCELED,
            },
            Shipment.Status.AWAITING_PAYMENT: set(),
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
        if (
            s.carrier_id
            and s.carrier_id != request.user.id
            and s.client_id != request.user.id
            and not request.user.is_staff
        ):
            return response.Response({"detail": "only_assigned_carrier"}, status=status.HTTP_403_FORBIDDEN)
        if new_status not in allowed.get(old_status, set()):
            return response.Response({"detail": "status_transition_not_allowed"}, status=status.HTTP_409_CONFLICT)

        if new_status == Shipment.Status.AWAITING_PAYMENT:
            try:
                _mark_work_done(s)
            except ValueError as exc:
                return response.Response(
                    {"detail": str(exc)},
                    status=status.HTTP_409_CONFLICT,
                )
            notify_shipment_status(s)
        else:
            s.status = new_status
            update_fields = ["status"]
            if new_status == Shipment.Status.PENDING:
                s.carrier = None
                update_fields.append("carrier")
            s.save(update_fields=update_fields)
            if new_status != old_status:
                notify_shipment_status(s)

        broadcast_shipment(s)

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

        test_price = effective_safa_test_price()
        if test_price is not None:
            logger.warning(
                "quote_test_pricing",
                extra={
                    "request_id": rid,
                    "user_id": request.user.id,
                    "distance_km": str(dist_km),
                    "estimated_fare": int(test_price),
                },
            )
            return response.Response(
                QuoteOutSerializer(
                    {
                        "distance_km": dist_km,
                        "estimated_fare": int(test_price),
                    }
                ).data
            )

        fixed_fare = _quote_fixed_bazar_fare(stops)
        if fixed_fare is not None:
            logger.info(
                "quote_calculated",
                extra={
                    "request_id": rid,
                    "user_id": request.user.id,
                    "distance_km": str(dist_km),
                    "estimated_fare": fixed_fare,
                    "pricing": "bazar_fixed",
                },
            )
            return response.Response(
                QuoteOutSerializer({"distance_km": dist_km, "estimated_fare": fixed_fare}).data
            )

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
        if getattr(request.user, "role", None) != User.Roles.CARRIER:
            return response.Response({"detail": "only_for_carrier"}, status=status.HTTP_403_FORBIDDEN)
        try:
            lat = float(request.query_params.get("lat", 0))
            lon = float(request.query_params.get("lon", 0))
        except (ValueError):
            lat, lon = 0.0, 0.0

        # Лента специалиста показывает каждый свободный заказ.
        #
        # Раньше сюда добавлялись три отсева — граница Бишкека, вхождение всех
        # точек в опубликованный базар и совпадение specialist_type с типом
        # услуги. Любой из них молча прятал только что созданный клиентом
        # заказ, и специалист вообще не понимал, что заявка есть. Теперь
        # отсеиваются только заказы, которые специалист физически не может
        # взять: демо, уже занятые и собственные.
        qs = (
            Shipment.objects.filter(status=Shipment.Status.PENDING, carrier__isnull=True)
            .exclude(_demo_shipment_q())
            .exclude(client_id=request.user.id)
            .prefetch_related(
                Prefetch(
                    "stops",
                    queryset=ShipmentStop.objects.select_related(
                        "container",
                        "container__passage",
                        "container__passage__bazar",
                    ).order_by("position"),
                )
            )
            .order_by("created_at")
        )

        # Расстояние влияет только на порядок: заказ без координат первой точки
        # уходит в конец списка, но из ленты не исчезает.
        far_away = float("inf")
        ordered_pairs = []
        for index, s in enumerate(qs):
            # `stops` is already ordered and prefetched above. Calling
            # `.order_by().first()` here used to bypass that cache and issue one
            # SQL query per shipment.
            stops = list(s.stops.all())
            first_stop = stops[0] if stops else None
            if first_stop is not None and first_stop.lat is not None and first_stop.lon is not None:
                distance = haversine_m(lat, lon, float(first_stop.lat), float(first_stop.lon))
            else:
                distance = far_away
            # index держит стабильный порядок создания внутри одной дистанции.
            ordered_pairs.append((distance, index, s))

        ordered_shipments = [
            shipment for _, _, shipment in sorted(ordered_pairs, key=lambda item: (item[0], item[1]))
        ]

        page = self.paginate_queryset(ordered_shipments)
        serializer = self.get_serializer(
            page if page is not None else ordered_shipments,
            many=True,
            context={"request": request, "user_lat": lat, "user_lon": lon},
        )

        logger.info(
            "nearby_listed",
            extra={"request_id": rid, "user_id": request.user.id, "lat": lat, "lon": lon, "count": len(ordered_shipments)},
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

        if (
            s.status != Shipment.Status.AWAITING_PAYMENT
            or not s.carrier_id
            or not s.work_completed_at
        ):
            return response.Response(
                {"detail": "payment_not_due"},
                status=status.HTTP_409_CONFLICT,
            )

        account_id = str(getattr(settings, "FINIK_ACCOUNT_ID", "") or "").strip()
        api_key = str(getattr(settings, "FINIK_API_KEY", "") or "").strip()
        if not account_id or not api_key:
            logger.error("pay_finik_account_not_configured")
            return response.Response(
                {"detail": "finik_not_configured"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        with transaction.atomic():
            locked = Shipment.objects.select_for_update().get(pk=s.pk)
            if locked.is_paid:
                return response.Response({"detail": "already_paid"}, status=status.HTTP_409_CONFLICT)
            if (
                locked.status != Shipment.Status.AWAITING_PAYMENT
                or not locked.carrier_id
                or not locked.work_completed_at
            ):
                return response.Response({"detail": "payment_not_due"}, status=status.HTTP_409_CONFLICT)

            amount = payment_amount_for_shipment(locked)
            if amount <= 0:
                logger.warning(
                    "pay_finik_bad_amount",
                    extra={"request_id": rid, "user_id": request.user.id, "shipment_id": locked.id, "amount": amount},
                )
                return response.Response({"detail": "bad_amount"}, status=status.HTTP_400_BAD_REQUEST)

            attempt = (
                locked.payment_attempts.filter(status=PaymentAttempt.Status.PENDING)
                .order_by("-created_at")
                .first()
            )
            if attempt is None:
                attempt = PaymentAttempt.objects.create(
                    provider="FINIK",
                    shipment=locked,
                    amount=amount,
                    currency=getattr(settings, "FINIK_CURRENCY", "KGS"),
                    finik_request_id=uuid.uuid4().hex,
                    status=PaymentAttempt.Status.PENDING,
                )
            else:
                amount = int(attempt.amount)

        callback_url = str(getattr(settings, "FINIK_CALLBACK_URL", "") or "").strip()
        if not callback_url:
            callback_url = request.build_absolute_uri(reverse("finik-callback"))

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
                "finikRequestId": attempt.finik_request_id,
                "callbackUrl": callback_url,
                "requiredFields": {
                    "paymentId": str(attempt.id),
                    "finikRequestId": attempt.finik_request_id,
                    "shipmentId": str(s.id),
                },
                "amount": amount,
                "currency": attempt.currency,
                "accountId": account_id,
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

        try:
            nxt = s.next_stop()
            if not nxt:
                _mark_work_done(s)
                notify_shipment_status(s)
            else:
                if s.status == Shipment.Status.ASSIGNED:
                    s.status = Shipment.Status.IN_TRANSIT
                s.current_stop_index += 1
                if s.current_stop_index >= s.stops.count():
                    _mark_work_done(s)
                    notify_shipment_status(s)
                else:
                    s.save(update_fields=["current_stop_index", "status"])
                    notify_shipment_status(s)
        except ShipmentFareUnavailable:
            logger.warning(
                "shipment_advance_missing_fare",
                extra={
                    "request_id": rid,
                    "user_id": request.user.id,
                    "shipment_id": s.id,
                },
            )
            return response.Response(
                {"detail": "shipment_has_no_final_fare"},
                status=status.HTTP_409_CONFLICT,
            )

        broadcast_shipment(s)

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


@extend_schema(tags=["Специалисты"])
class CourierPositionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Обновить текущую позицию специалиста",
        request=inline_serializer(
            name="CourierPositionRequest",
            fields={
                "lat": serializers.FloatField(),
                "lon": serializers.FloatField(),
            },
        ),
        responses=inline_serializer(
            name="CourierPositionResponse",
            fields={
                "lat": serializers.FloatField(),
                "lon": serializers.FloatField(),
                "updated_at": serializers.DateTimeField(),
            },
        ),
    )
    def post(self, request):
        user = request.user
        if getattr(user, "role", None) != User.Roles.CARRIER:
            return Response({"detail": "only_for_carrier"}, status=status.HTTP_403_FORBIDDEN)
        if not user.is_active:
            return Response({"detail": "specialist_not_approved"}, status=status.HTTP_403_FORBIDDEN)

        try:
            lat = float(request.data.get("lat"))
            lon = float(request.data.get("lon"))
        except (TypeError, ValueError):
            return Response({"detail": "lat_lon_required"}, status=status.HTTP_400_BAD_REQUEST)

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return Response({"detail": "invalid_coordinates"}, status=status.HTTP_400_BAD_REQUEST)

        position, _ = CourierPosition.objects.update_or_create(
            user=user,
            defaults={
                "lat": Decimal(str(lat)).quantize(Decimal("0.000001")),
                "lon": Decimal(str(lon)).quantize(Decimal("0.000001")),
            },
        )
        broadcast_courier_position(position)
        return Response(
            {
                "lat": float(position.lat),
                "lon": float(position.lon),
                "updated_at": position.updated_at,
            }
        )


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

        resolved = reverse_geocode_address(float(lat), float(lon))
        if resolved is None:
            logger.warning("reverse_geocode_unavailable", extra={"request_id": rid})
            return Response({"error": "reverse_geocode_unavailable"}, status=502)
        address, source = resolved
        logger.info(
            "reverse_geocode_ok",
            extra={"request_id": rid, "provider": source},
        )
        return Response({"address": address, "source": source})


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
