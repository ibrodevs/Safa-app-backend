from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from apps.users.models import User
from .geo import haversine_m
from .map_pricing import point_inside_published_or_legacy_bazar
from .models import CourierPosition, Shipment


@dataclass(frozen=True)
class SpecialistCandidate:
    user_id: int
    distance_m: float


def point_inside_bazar(lat, lon) -> bool:
    """Проверяет опубликованную границу карты, затем legacy-прямоугольник."""

    return point_inside_published_or_legacy_bazar(lat, lon)


def shipment_all_stops_in_bazars(shipment: Shipment) -> bool:
    stops = list(shipment.stops.all())
    if not stops:
        return False
    for stop in stops:
        if stop.container_id:
            continue
        if not point_inside_bazar(stop.lat, stop.lon):
            return False
    return True


def shipment_matches_specialist(shipment: Shipment, user: User) -> bool:
    if not user.is_active or getattr(user, "role", None) != User.Roles.CARRIER:
        return False
    if not shipment_all_stops_in_bazars(shipment):
        return False

    specialist_type = getattr(user, "specialist_type", None)
    if specialist_type == User.SpecialistType.CART:
        return shipment.service_type == Shipment.ServiceType.CARS
    if specialist_type == User.SpecialistType.DELIVERY:
        return shipment.service_type in (
            Shipment.ServiceType.DELIVERY,
            Shipment.ServiceType.AMANAT,
        )
    return shipment.service_type in (
        Shipment.ServiceType.CARS,
        Shipment.ServiceType.DELIVERY,
        Shipment.ServiceType.AMANAT,
    )


def nearest_specialist_candidates(shipment: Shipment) -> list[SpecialistCandidate]:
    first_stop = shipment.stops.order_by("position").first()
    if not first_stop or first_stop.lat is None or first_stop.lon is None:
        return []

    max_distance_m = int(getattr(settings, "SPECIALIST_OFFER_RADIUS_M", 2500))
    max_candidates = int(getattr(settings, "SPECIALIST_OFFER_MAX_CANDIDATES", 20))
    stale_minutes = int(getattr(settings, "SPECIALIST_POSITION_STALE_MINUTES", 30))
    stale_after = timezone.now() - timezone.timedelta(minutes=stale_minutes)

    positions = (
        CourierPosition.objects.select_related("user")
        .filter(
            user__role=User.Roles.CARRIER,
            user__is_active=True,
            updated_at__gte=stale_after,
        )
        .exclude(user_id=shipment.client_id)
    )

    candidates: list[SpecialistCandidate] = []
    for position in positions:
        user = position.user
        if not shipment_matches_specialist(shipment, user):
            continue
        distance_m = haversine_m(
            float(position.lat),
            float(position.lon),
            float(first_stop.lat),
            float(first_stop.lon),
        )
        if distance_m <= max_distance_m:
            candidates.append(
                SpecialistCandidate(user_id=user.id, distance_m=distance_m),
            )

    candidates.sort(key=lambda item: item.distance_m)
    return candidates[:max_candidates]
