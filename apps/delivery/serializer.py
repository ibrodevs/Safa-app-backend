from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP

import requests
from django.db import IntegrityError, transaction
from rest_framework import serializers

from apps.delivery.geo import haversine_m
from .geocoding import GeocodeNotFound, twogis_resolve_best
from .models import (
    Bazar,
    Container,
    Passage,
    Shipment,
    ShipmentStop,
)

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

        try:
            passage_obj, passage_created = Passage.objects.get_or_create(bazar=bazar_obj, number=passage)
        except IntegrityError:
            passage_obj = Passage.objects.get(bazar=bazar_obj, number=passage)
            passage_created = False

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
        fields = ["id", "name"]


class PassageSerializer(serializers.ModelSerializer):
    bazar_id = serializers.IntegerField(source="bazar.id", read_only=True)
    bazar_name = serializers.CharField(source="bazar.name", read_only=True)

    class Meta:
        model = Passage
        fields = ["id", "bazar_id", "bazar_name", "number"]


class ContainerSerializer(serializers.ModelSerializer):
    bazar_id = serializers.IntegerField(source="passage.bazar.id", read_only=True)
    bazar_name = serializers.CharField(source="passage.bazar.name", read_only=True)
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
    passage = serializers.SerializerMethodField()
    container = serializers.SerializerMethodField()
    label = serializers.SerializerMethodField()

    class Meta:
        model = ShipmentStop
        fields = ["position", "title", "lat", "lon", "bazar", "passage", "container", "label"]

    def get_bazar(self, obj: ShipmentStop):
        return obj.container.passage.bazar.name if obj.container_id else None

    def get_passage(self, obj: ShipmentStop):
        return obj.container.passage.number if obj.container_id else None

    def get_container(self, obj: ShipmentStop):
        return obj.container.number if obj.container_id else None

    def get_label(self, obj: ShipmentStop):
        return obj.container.display_title if obj.container_id else None


MAX_SHIPMENT_STOPS = 10


class ShipmentCreateSerializer(serializers.ModelSerializer):
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


class ShipmentDetailSerializer(serializers.ModelSerializer):
    stops = ShipmentStopReadSerializer(many=True, read_only=True)
    stops_count = serializers.SerializerMethodField()
    public_code = serializers.CharField(read_only=True)
    commission = serializers.SerializerMethodField()
    courier_income = serializers.SerializerMethodField()

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
            "created_at",
            "finished_at",
            "is_paid",
            "paid_at",
        ]
        read_only_fields = fields

    def get_stops_count(self, obj):
        return obj.stops.count()

    def get_commission(self, obj):
        return obj.commission_amount

    def get_courier_income(self, obj):
        return obj.courier_income


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


class ShipmentCardSerializer(serializers.ModelSerializer):
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
        return obj.stops.count()


class ShipmentNearbySerializer(serializers.ModelSerializer):
    distance_m = serializers.SerializerMethodField()
    stops = ShipmentStopReadSerializer(many=True, read_only=True)

    class Meta:
        model = Shipment
        fields = (
            "id",
            "public_code",
            "title",
            "estimated_fare",
            "status",
            "created_at",
            "distance_m",
            "stops",
        )

    def get_distance_m(self, obj) -> int | None:
        lat = self.context.get("user_lat")
        lon = self.context.get("user_lon")
        if lat is None or lon is None:
            return None

        stop = obj.stops.order_by("position").first()
        if not stop or stop.lat is None or stop.lon is None:
            return None

        d = haversine_m(lat, lon, float(stop.lat), float(stop.lon))
        return int(round(d))
