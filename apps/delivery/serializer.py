from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP

import requests
from django.db import IntegrityError, transaction
from rest_framework import serializers

from apps.delivery.geo import haversine_m
from apps.payments.models import CarrierSettlement
from apps.payments.amounts import (
    commission_for_payment_amount,
    effective_safa_test_price,
    carrier_income_for_shipment,
    payment_amount_for_shipment,
)
from .geocoding import GeocodeNotFound, twogis_resolve_best
from .models import (
    AmanatCampaign,
    AmanatCategory,
    AmanatDonation,
    Bazar,
    Container,
    Passage,
    Shipment,
    ShipmentStop,
)
from .specialists import point_inside_bazar
from .map_point_resolver import resolve_market_point

logger = logging.getLogger(__name__)

_DEC6 = Decimal("0.000001")


def _norm(s: str | None) -> str:
    return (s or "").strip()


def _d6(x: float) -> Decimal:
    return Decimal(str(x)).quantize(_DEC6, rounding=ROUND_HALF_UP)


def _rid(ctx: dict) -> str | None:
    req = ctx.get("request")
    if not req:
        return None
    return req.headers.get("X-Request-ID")


def _uid(ctx: dict) -> int | None:
    req = ctx.get("request")
    if not req or not getattr(req, "user", None):
        return None
    return getattr(req.user, "id", None)


def get_or_create_container_ui(
    *,
    bazar: str,
    passage: str,
    container: str,
    title: str | None,
    lat: float | None,
    lon: float | None,
    q: str | None,
    request_id: str | None,
    user_id: int | None,
) -> Container:
    bazar = _norm(bazar)
    passage = _norm(passage)
    container = _norm(container)
    title = _norm(title)
    q = _norm(q)

    if not bazar or not passage or not container:
        raise serializers.ValidationError("bazar, passage, container обязательны")

    with transaction.atomic():
        bazar_obj = Bazar.objects.filter(name__iexact=bazar).first()
        if not bazar_obj:
            try:
                bazar_obj = Bazar.objects.create(name=bazar)
                logger.info(
                    "bazar_created",
                    extra={"request_id": request_id, "user_id": user_id, "bazar": bazar_obj.name},
                )
            except IntegrityError:
                bazar_obj = Bazar.objects.filter(name__iexact=bazar).first()
                if not bazar_obj:
                    raise

        # Номер прохода уникален внутри района, поэтому в базаре может быть
        # несколько проходов с одним номером. Старый API района не передаёт —
        # берём уже существующий проход, а новый создаём вне районов.
        passage_obj = Passage.objects.filter(bazar=bazar_obj, number=passage).order_by("district", "id").first()
        passage_created = False
        if passage_obj is None:
            try:
                passage_obj = Passage.objects.create(bazar=bazar_obj, district="", number=passage)
                passage_created = True
            except IntegrityError:
                passage_obj = Passage.objects.get(bazar=bazar_obj, district="", number=passage)

        if passage_created:
            logger.info(
                "passage_created",
                extra={"request_id": request_id, "user_id": user_id, "bazar": bazar_obj.name, "passage": passage_obj.number},
            )

        obj = (
            Container.objects.select_related("passage", "passage__bazar")
            .filter(passage=passage_obj, number=container)
            .first()
        )

        created = False
        if not obj:
            use_lat = lat
            use_lon = lon

            if use_lat is None or use_lon is None:
                query = q or f"{bazar_obj.name}, контейнер {container}, {passage_obj.number} проход"
                try:
                    best = twogis_resolve_best(q=query, page_size=10)
                    use_lat = best.get("lat")
                    use_lon = best.get("lon")
                    logger.info(
                        "container_geocoded",
                        extra={
                            "request_id": request_id,
                            "user_id": user_id,
                            "query": query,
                            "lat": use_lat,
                            "lon": use_lon,
                        },
                    )
                except GeocodeNotFound:
                    logger.warning(
                        "container_geocode_not_found",
                        extra={"request_id": request_id, "user_id": user_id, "query": query},
                    )
                    raise serializers.ValidationError("Не нашли контейнер по поиску. Дай координаты или уточни q")
                except (requests.RequestException, ValueError):
                    logger.warning(
                        "container_geocode_failed",
                        extra={"request_id": request_id, "user_id": user_id},
                    )
                    raise serializers.ValidationError("Не смогли получить координаты (2GIS). Попробуй ещё раз")

            if use_lat is None or use_lon is None:
                raise serializers.ValidationError("Для нового контейнера нужны lat/lon (или корректный q для 2GIS)")

            payload = {
                "passage": passage_obj,
                "number": container,
                "lat": _d6(float(use_lat)),
                "lon": _d6(float(use_lon)),
                "is_active": True,
            }
            if title:
                payload["title"] = title

            try:
                obj = Container.objects.create(**payload)
                created = True
            except IntegrityError:
                obj = Container.objects.select_related("passage", "passage__bazar").get(
                    passage=passage_obj,
                    number=container,
                )
                created = False

        if not obj.is_active:
            obj.is_active = True
            obj.save(update_fields=["is_active"])

        if title and not _norm(obj.title):
            obj.title = title
            obj.save(update_fields=["title"])

        logger.info(
            "container_resolved",
            extra={
                "request_id": request_id,
                "user_id": user_id,
                "container_created": created,
                "container_id": obj.id,
                "bazar": obj.passage.bazar.name,
                "passage": obj.passage.number,
                "container": obj.number,
            },
        )
        return obj


class BazarSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bazar
        fields = ["id", "name", "district"]


class PassageSerializer(serializers.ModelSerializer):
    bazar_id = serializers.IntegerField(source="bazar.id", read_only=True)
    bazar_name = serializers.CharField(source="bazar.name", read_only=True)

    class Meta:
        model = Passage
        fields = ["id", "bazar_id", "bazar_name", "district", "number", "angle"]


class ContainerSerializer(serializers.ModelSerializer):
    bazar_id = serializers.IntegerField(source="passage.bazar.id", read_only=True)
    bazar_name = serializers.CharField(source="passage.bazar.name", read_only=True)
    bazar_district = serializers.CharField(source="passage.bazar.district", read_only=True)
    passage_id = serializers.IntegerField(source="passage.id", read_only=True)
    passage_number = serializers.CharField(source="passage.number", read_only=True)
    ui_label = serializers.SerializerMethodField()
    display_title = serializers.SerializerMethodField()

    class Meta:
        model = Container
        fields = [
            "id",
            "bazar_id",
            "bazar_name",
            "bazar_district",
            "passage_id",
            "passage_number",
            "number",
            "title",
            "is_active",
            "lat",
            "lon",
            "ui_label",
            "display_title",
        ]

    def get_ui_label(self, obj: Container) -> str:
        return obj.ui_label

    def get_display_title(self, obj: Container) -> str:
        return obj.display_title


def mask_amanat_donor_label(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return "Анонимный пользователь"
    if not text.startswith("+"):
        return text
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) < 6:
        return "Анонимный пользователь"
    return f"+{digits[:3]} *** ** {digits[-3:]}"


class AmanatCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AmanatCategory
        fields = ["id", "name", "slug"]


class AmanatDonationSerializer(serializers.ModelSerializer):
    donor_label = serializers.SerializerMethodField()

    class Meta:
        model = AmanatDonation
        fields = ["id", "donor_label", "amount", "status", "created_at", "paid_at"]
        read_only_fields = fields

    def get_donor_label(self, obj: AmanatDonation) -> str:
        if obj.is_anonymous:
            return "Анонимный пользователь"
        if obj.donor_label:
            return mask_amanat_donor_label(obj.donor_label)
        phone = getattr(obj.donor, "phone_number", "") if obj.donor_id else ""
        name = " ".join(
            part
            for part in (
                getattr(obj.donor, "first_name", "") if obj.donor_id else "",
                getattr(obj.donor, "last_name", "") if obj.donor_id else "",
            )
            if part
        )
        return name or mask_amanat_donor_label(phone)


class AmanatCampaignSerializer(serializers.ModelSerializer):
    category_id = serializers.IntegerField(source="category.id", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    category_slug = serializers.CharField(source="category.slug", read_only=True)
    cover_image_url = serializers.SerializerMethodField()
    collected_amount = serializers.IntegerField(read_only=True)
    voluntary_amount = serializers.IntegerField(read_only=True)
    remaining_amount = serializers.IntegerField(read_only=True)
    helpers_count = serializers.IntegerField(read_only=True)
    progress = serializers.SerializerMethodField()
    latest_donations = serializers.SerializerMethodField()

    class Meta:
        model = AmanatCampaign
        fields = [
            "id",
            "category_id",
            "category_name",
            "category_slug",
            "title",
            "short_title",
            "description",
            "goal",
            "needed_amount",
            "collected_amount",
            "voluntary_amount",
            "safa_amount",
            "remaining_amount",
            "helpers_count",
            "cover_image_url",
            "ends_at",
            "status",
            "is_featured",
            "progress",
            "latest_donations",
        ]
        read_only_fields = fields

    def get_cover_image_url(self, obj: AmanatCampaign) -> str:
        if not obj.cover_image:
            return ""
        request = self.context.get("request")
        url = obj.cover_image.url
        return request.build_absolute_uri(url) if request else url

    def get_progress(self, obj: AmanatCampaign) -> float:
        if not obj.needed_amount:
            return 0
        return min(obj.collected_amount / obj.needed_amount, 1)

    def get_latest_donations(self, obj: AmanatCampaign):
        qs = getattr(obj, "_latest_paid_donations", None)
        if qs is None:
            qs = obj.donations.filter(
                status=AmanatDonation.Status.PAID,
            ).select_related("donor").order_by("-created_at")[:20]
        return AmanatDonationSerializer(qs, many=True, context=self.context).data


class AmanatDonateSerializer(serializers.Serializer):
    amount = serializers.IntegerField(min_value=1)
    is_anonymous = serializers.BooleanField(required=False, default=False)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=255)


class ShipmentStopInSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    lat = serializers.FloatField(required=False)
    lon = serializers.FloatField(required=False)

    bazar = serializers.CharField(required=False, allow_blank=True)
    passage = serializers.CharField(required=False, allow_blank=True)
    container = serializers.CharField(required=False, allow_blank=True)

    q = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        title = _norm(attrs.get("title"))
        lat = attrs.get("lat")
        lon = attrs.get("lon")

        bazar = _norm(attrs.get("bazar"))
        passage = _norm(attrs.get("passage"))
        container = _norm(attrs.get("container"))
        q = _norm(attrs.get("q"))

        has_title = bool(title)
        has_coords = lat is not None and lon is not None
        has_container_key = bool(bazar and passage and container)
        has_search = bool(q)

        if not has_title and not has_coords and not has_container_key and not has_search:
            raise serializers.ValidationError(
                "Нужно хотя бы одно из: title, lat+lon, bazar+passage+container, q"
            )

        if (bazar or passage or container) and not has_container_key:
            raise serializers.ValidationError("Для контейнера нужны все поля: bazar, passage, container")

        return attrs


class ShipmentStopReadSerializer(serializers.ModelSerializer):
    bazar = serializers.SerializerMethodField()
    district = serializers.SerializerMethodField()
    passage = serializers.SerializerMethodField()
    container = serializers.SerializerMethodField()
    label = serializers.SerializerMethodField()

    class Meta:
        model = ShipmentStop
        fields = [
            "position",
            "title",
            "lat",
            "lon",
            "bazar",
            "district",
            "passage",
            "container",
            "label",
        ]

    def _resolved_market_point(self, obj: ShipmentStop):
        if not obj.container_id or obj.lat is None or obj.lon is None:
            return None
        cache = self.context.setdefault("_safa_market_stop_cache", {})
        if obj.container_id not in cache:
            match = resolve_market_point(float(obj.lat), float(obj.lon))
            if match is not None and match.container.id != obj.container_id:
                match = None
            cache[obj.container_id] = match
        return cache[obj.container_id]

    def get_bazar(self, obj: ShipmentStop):
        match = self._resolved_market_point(obj)
        if match is not None:
            return match.bazar_name
        return obj.container.passage.bazar.name if obj.container_id else None

    def get_district(self, obj: ShipmentStop):
        match = self._resolved_market_point(obj)
        if match is not None and match.district_name:
            return match.district_name
        # Точку не удалось разложить по опубликованной карте — район знает проход.
        return (obj.container.passage.district or None) if obj.container_id else None

    def get_passage(self, obj: ShipmentStop):
        match = self._resolved_market_point(obj)
        if match is not None:
            return match.passage_number
        return obj.container.passage.number if obj.container_id else None

    def get_container(self, obj: ShipmentStop):
        match = self._resolved_market_point(obj)
        if match is not None:
            return match.container_number
        return obj.container.number if obj.container_id else None

    def get_label(self, obj: ShipmentStop):
        parts = []
        bazar = self.get_bazar(obj)
        district = self.get_district(obj)
        passage = self.get_passage(obj)
        container = self.get_container(obj)
        if bazar:
            parts.append(f"Базар: {bazar}")
        if district:
            parts.append(f"Район: {district}")
        if passage:
            parts.append(f"Проход: {passage}")
        if container:
            parts.append(f"Контейнер: {container}")
        return " · ".join(parts) or (obj.title or "")


MAX_SHIPMENT_STOPS = 30


class ShipmentTestPriceRepresentationMixin:
    """Expose the temporary test price without destroying real stored fares."""

    def to_representation(self, instance):
        data = super().to_representation(instance)
        test_price = effective_safa_test_price()
        if test_price is None:
            return data
        if "estimated_fare" in data:
            data["estimated_fare"] = int(test_price)
        if "final_fare" in data and int(getattr(instance, "final_fare", 0) or 0) > 0:
            data["final_fare"] = int(test_price)
        return data


class ShipmentCreateSerializer(ShipmentTestPriceRepresentationMixin, serializers.ModelSerializer):
    stops = serializers.ListField(
        child=ShipmentStopInSerializer(),
        min_length=2,
        max_length=MAX_SHIPMENT_STOPS,
        write_only=True,
    )
    return_to_start = serializers.BooleanField(default=False, write_only=True)
    estimated_fare = serializers.IntegerField(read_only=True)

    class Meta:
        model = Shipment
        fields = [
            "id",
            "title",
            "service_type",
            "description",
            "client_id",
            "carrier_id",
            "current_stop_index",
            "stops",
            "return_to_start",
            "estimated_fare",
        ]
        extra_kwargs = {}

    def validate(self, attrs):
        stops = attrs.get("stops") or []
        rts = attrs.get("return_to_start", False)
        service_type = attrs.get("service_type", Shipment.ServiceType.DELIVERY)
        max_stops = MAX_SHIPMENT_STOPS if service_type == Shipment.ServiceType.CARS else 2

        if not isinstance(stops, list) or len(stops) < 2 or len(stops) > max_stops:
            if service_type == Shipment.ServiceType.CARS:
                raise serializers.ValidationError({"stops": f"Нужно 2–{MAX_SHIPMENT_STOPS} точек"})
            raise serializers.ValidationError({"stops": "Для этой услуги нужны ровно 2 точки"})
        if rts and len(stops) >= MAX_SHIPMENT_STOPS:
            raise serializers.ValidationError(
                {"return_to_start": f"С возвратом максимум {MAX_SHIPMENT_STOPS - 1} исходных точек"}
            )
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        if not request or not getattr(request, "user", None):
            logger.error("shipment_create_no_request_context")
            raise serializers.ValidationError("request context is required")

        request_id = _rid(self.context)
        user_id = _uid(self.context)

        stops_data = list(validated_data.pop("stops"))
        return_to_start = validated_data.pop("return_to_start", False)
        service_type = validated_data.get(
            "service_type", Shipment.ServiceType.DELIVERY
        )

        resolved: list[dict] = []
        stop_errors: dict[int, str] = {}

        for i, stop in enumerate(stops_data):
            try:
                title = _norm(stop.get("title"))
                lat = stop.get("lat")
                lon = stop.get("lon")

                bazar = _norm(stop.get("bazar"))
                passage = _norm(stop.get("passage"))
                container = _norm(stop.get("container"))
                q = _norm(stop.get("q"))

                if bazar and passage and container:
                    c = get_or_create_container_ui(
                        bazar=bazar,
                        passage=passage,
                        container=container,
                        title=title or None,
                        lat=lat,
                        lon=lon,
                        q=q or None,
                        request_id=request_id,
                        user_id=user_id,
                    )
                    resolved.append({"kind": "container", "container": c, "title": title})
                    continue

                if lat is not None and lon is not None:
                    resolved.append({"kind": "coords", "title": title or "", "lat": lat, "lon": lon})
                    continue

                if title:
                    resolved.append({"kind": "coords", "title": title, "lat": None, "lon": None})
                    continue

                if q:
                    best = twogis_resolve_best(q=q, page_size=10)
                    out_title = title or (best.get("title") or best.get("address") or "Точка")
                    resolved.append({"kind": "coords", "title": out_title, "lat": best.get("lat"), "lon": best.get("lon")})
                    logger.info(
                        "stop_geocoded",
                        extra={"request_id": request_id, "user_id": user_id, "stop_index": i, "query": q},
                    )
                    continue

                stop_errors[i] = "invalid_stop"
                logger.warning(
                    "shipment_stop_invalid",
                    extra={"request_id": request_id, "user_id": user_id, "stop_index": i},
                )

            except GeocodeNotFound:
                stop_errors[i] = "Не нашли точку. Уточни q"
                logger.warning(
                    "shipment_stop_geocode_not_found",
                    extra={"request_id": request_id, "user_id": user_id, "stop_index": i},
                )
            except (requests.RequestException, ValueError):
                stop_errors[i] = "Не смогли получить координаты (2GIS). Попробуй ещё раз"
                logger.warning(
                    "shipment_stop_geocode_failed",
                    extra={"request_id": request_id, "user_id": user_id, "stop_index": i},
                )
            except serializers.ValidationError as e:
                msg = str(e.detail) if hasattr(e, "detail") else "validation_error"
                stop_errors[i] = msg
                logger.warning(
                    "shipment_stop_validation_error",
                    extra={"request_id": request_id, "user_id": user_id, "stop_index": i, "detail": msg},
                )
            except Exception:
                stop_errors[i] = "unexpected_error"
                logger.exception(
                    "shipment_stop_unexpected_error",
                    extra={"request_id": request_id, "user_id": user_id, "stop_index": i},
                )

        if stop_errors:
            logger.info(
                "shipment_create_stop_errors",
                extra={"request_id": request_id, "user_id": user_id, "errors": stop_errors},
            )
            raise serializers.ValidationError({"stops": stop_errors})

        if return_to_start and resolved:
            resolved.append(dict(resolved[0]))

        # Delivery and cart routes are normal city addresses and must not be
        # tied to polygons drawn in the admin map. Amanat keeps its bazaar-only
        # constraint because it is the dedicated market donation flow.
        if service_type == Shipment.ServiceType.AMANAT:
            outside_bazar: dict[int, str] = {}
            for idx, stop in enumerate(resolved):
                if stop["kind"] == "container":
                    continue
                if not point_inside_bazar(stop.get("lat"), stop.get("lon")):
                    outside_bazar[idx] = "Точка должна быть внутри базара"
            if outside_bazar:
                raise serializers.ValidationError({"stops": outside_bazar})

        with transaction.atomic():
            shipment = Shipment(client=request.user, **validated_data)
            shipment.save()

            for idx, stop in enumerate(resolved):
                if stop["kind"] == "container":
                    ss = ShipmentStop(shipment=shipment, position=idx, container=stop["container"])
                    if stop.get("title"):
                        ss.title = stop["title"]
                    ss.save()
                else:
                    ShipmentStop.objects.create(
                        shipment=shipment,
                        position=idx,
                        title=stop["title"],
                        lat=stop["lat"],
                        lon=stop["lon"],
                    )

            shipment.current_stop_index = 0
            shipment.estimate()
            shipment.save(update_fields=["distance_km", "estimated_fare", "current_stop_index"])

        logger.info(
            "shipment_created",
            extra={"request_id": request_id, "user_id": user_id, "shipment_id": shipment.id},
        )
        return shipment


class ShipmentDetailSerializer(ShipmentTestPriceRepresentationMixin, serializers.ModelSerializer):
    stops = ShipmentStopReadSerializer(many=True, read_only=True)
    stops_count = serializers.SerializerMethodField()
    public_code = serializers.CharField(read_only=True)
    commission = serializers.SerializerMethodField()
    courier_income = serializers.SerializerMethodField()
    settlement_status = serializers.SerializerMethodField()
    settled_amount = serializers.SerializerMethodField()
    payment_due_amount = serializers.SerializerMethodField()
    payment_due_income = serializers.SerializerMethodField()

    class Meta:
        model = Shipment
        fields = [
            "id",
            "public_code",
            "status",
            "title",
            "service_type",
            "description",
            "client_id",
            "carrier_id",
            "current_stop_index",
            "stops",
            "stops_count",
            "estimated_fare",
            "final_fare",
            "commission",
            "courier_income",
            "settlement_status",
            "settled_amount",
            "payment_due_amount",
            "payment_due_income",
            "created_at",
            "finished_at",
            "work_completed_at",
            "is_paid",
            "paid_at",
        ]
        read_only_fields = fields

    def get_stops_count(self, obj):
        return len(obj.stops.all())

    def get_commission(self, obj):
        return commission_for_payment_amount(payment_amount_for_shipment(obj))

    def get_courier_income(self, obj):
        return carrier_income_for_shipment(obj)

    def get_settlement_status(self, obj):
        try:
            return obj.carrier_settlement.status
        except (AttributeError, CarrierSettlement.DoesNotExist):
            return None

    def get_settled_amount(self, obj):
        try:
            return obj.carrier_settlement.net_amount
        except (AttributeError, CarrierSettlement.DoesNotExist):
            return 0

    def get_payment_due_amount(self, obj):
        return payment_amount_for_shipment(obj)

    def get_payment_due_income(self, obj):
        return carrier_income_for_shipment(obj)


class ShipmentStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shipment
        fields = ["status"]


class CoordsSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    lat = serializers.FloatField()
    lon = serializers.FloatField()


class QuoteInSerializer(serializers.Serializer):
    stops = serializers.ListField(child=CoordsSerializer(), min_length=2, max_length=MAX_SHIPMENT_STOPS)
    return_to_start = serializers.BooleanField(default=False)

    def validate(self, attrs):
        stops = attrs.get("stops") or []
        if len(stops) < 2:
            raise serializers.ValidationError({"stops": f"Нужно 2–{MAX_SHIPMENT_STOPS} точек"})
        if attrs.get("return_to_start") and len(stops) >= MAX_SHIPMENT_STOPS:
            raise serializers.ValidationError(
                {"return_to_start": f"С возвратом максимум {MAX_SHIPMENT_STOPS - 1} исходных точек"}
            )
        return attrs


class QuoteOutSerializer(serializers.Serializer):
    distance_km = serializers.DecimalField(max_digits=7, decimal_places=2)
    estimated_fare = serializers.IntegerField()


class ShipmentCardSerializer(ShipmentTestPriceRepresentationMixin, serializers.ModelSerializer):
    stops_count = serializers.SerializerMethodField()
    public_code = serializers.CharField(read_only=True)

    class Meta:
        model = Shipment
        fields = [
            "id",
            "public_code",
            "title",
            "service_type",
            "estimated_fare",
            "is_paid",
            "paid_at",
            "stops_count",
            "status",
            "created_at",
        ]

    def get_stops_count(self, obj):
        return len(obj.stops.all())


class ShipmentNearbySerializer(ShipmentTestPriceRepresentationMixin, serializers.ModelSerializer):
    distance_m = serializers.SerializerMethodField()
    stops = ShipmentStopReadSerializer(many=True, read_only=True)
    stops_count = serializers.SerializerMethodField()
    commission = serializers.SerializerMethodField()
    courier_income = serializers.SerializerMethodField()

    class Meta:
        model = Shipment
        fields = (
            "id",
            "public_code",
            "title",
            "service_type",
            "description",
            "estimated_fare",
            "final_fare",
            "commission",
            "courier_income",
            "status",
            "created_at",
            "finished_at",
            "is_paid",
            "paid_at",
            "distance_m",
            "stops_count",
            "stops",
        )

    def get_stops_count(self, obj) -> int:
        return len(obj.stops.all())

    def get_commission(self, obj) -> int:
        return commission_for_payment_amount(payment_amount_for_shipment(obj))

    def get_courier_income(self, obj) -> int:
        return carrier_income_for_shipment(obj)

    def get_distance_m(self, obj) -> int | None:
        lat = self.context.get("user_lat")
        lon = self.context.get("user_lon")
        if lat is None or lon is None:
            return None

        stops = list(obj.stops.all())
        stop = stops[0] if stops else None
        if not stop or stop.lat is None or stop.lon is None:
            return None

        d = haversine_m(lat, lon, float(stop.lat), float(stop.lon))
        return int(round(d))
