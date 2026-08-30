from __future__ import annotations

import logging
from decimal import Decimal

from asgiref.sync import async_to_sync
from channels.generic.websocket import JsonWebsocketConsumer
from django.contrib.auth.models import AnonymousUser
from django.db import transaction
from django.utils import timezone

from .models import Shipment, CourierPosition, ARRIVAL_RADIUS_M
from .geo import haversine_m
from .realtime import courier_position_payload

logger = logging.getLogger(__name__)

BASE_SPEED_KMH = Decimal("20.0")


def _clamp_speed(v) -> Decimal | None:
    if v is None:
        return None
    try:
        v = Decimal(str(v))
    except Exception:
        return None
    if v < 0:
        return Decimal("0.0")
    if v > 120:
        return Decimal("120.0")
    return v


class ShipmentTrackingConsumer(JsonWebsocketConsumer):

    def connect(self):
        user = self.scope.get("user")

        if not user or not user.is_authenticated:
            self.close()
            return

        try:
            self.shipment_id = int(self.scope["url_route"]["kwargs"]["shipment_id"])
        except Exception:
            self.close()
            return

        try:
            shipment = Shipment.objects.get(id=self.shipment_id)
        except Shipment.DoesNotExist:
            self.close()
            return

        allowed_users = {shipment.client_id}

        if shipment.carrier_id:
            allowed_users.add(shipment.carrier_id)

        if user.id not in allowed_users:
            self.close()
            return

        self.group = f"shipment_{self.shipment_id}"

        try:
            async_to_sync(self.channel_layer.group_add)(self.group, self.channel_name)
        except Exception:
            self.close()
            return

        self.accept()
        if shipment.carrier_id:
            position = CourierPosition.objects.filter(user_id=shipment.carrier_id).first()
            if position is not None:
                self.send_json(courier_position_payload(shipment, position))

    def disconnect(self, code):
        group = getattr(self, "group", None)
        if group:
            async_to_sync(self.channel_layer.group_discard)(group, self.channel_name)

    def receive_json(self, content, **kwargs):
        t = content.get("type")
        if t == "loc":
            self._on_location(content)
        elif t == "ping":
            self.send_json({"type": "pong"})
        else:
            self.send_json({"type": "error", "detail": "bad_payload"})

    def _on_location(self, content: dict):
        try:
            user = self.scope.get("user")
            if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
                self.send_json({"type": "error", "detail": "unauthenticated"})
                return

            try:
                lat = Decimal(str(content.get("lat")))
                lon = Decimal(str(content.get("lon")))
            except Exception:
                self.send_json({"type": "error", "detail": "bad_payload"})
                return

            client_speed = _clamp_speed(content.get("speed_kmh"))

            try:
                shipment: Shipment = (
                    Shipment.objects
                    .select_related("carrier")
                    .prefetch_related("stops")
                    .get(id=self.shipment_id)
                )
            except Shipment.DoesNotExist:
                self.send_json({"type": "error", "detail": "not_found"})
                return

            if shipment.carrier_id != user.id:
                self.send_json({
                    "type": "error",
                    "detail": "forbidden",
                    "carrier_id": shipment.carrier_id,
                    "user_id": user.id,
                })
                return

            with transaction.atomic():
                pos, created = (
                    CourierPosition.objects
                    .select_for_update()
                    .get_or_create(
                        user=user,
                        defaults={"lat": lat, "lon": lon},
                    )
                )

                if not created:
                    pos.lat = lat
                    pos.lon = lon
                    pos.updated_at = timezone.now()
                    pos.save(update_fields=["lat", "lon", "updated_at"])

                dist_m_to_target = shipment.distance_to_next_m(float(lat), float(lon))
                arrived = dist_m_to_target <= ARRIVAL_RADIUS_M

                if dist_m_to_target > 0 and not arrived:
                    speed = client_speed or BASE_SPEED_KMH
                    try:
                        eta = (
                            (dist_m_to_target / Decimal("1000")) / speed * Decimal("60")
                        ).quantize(Decimal("0.1"))
                    except Exception:
                        eta = None
                    shipment.eta_to_next_min = eta or Decimal("0.0")
                else:
                    shipment.eta_to_next_min = Decimal("0.0")

                # GPS only reports arrival and ETA. Advancing to the next stop
                # or completing work is always an explicit specialist action.
                shipment.save(update_fields=["eta_to_next_min"])

            payload = {
                "type": "telemetry",
                "shipment_id": shipment.id,
                "status": shipment.status,
                "courier": {
                    "lat": str(lat),
                    "lon": str(lon),
                    "updated_at": pos.updated_at.isoformat(),
                },
                "target_index": shipment.current_stop_index,
                "distance_m": str(dist_m_to_target),
                "arrived": arrived,
                "eta_min": str(shipment.eta_to_next_min) if shipment.eta_to_next_min else None,
            }

            async_to_sync(self.channel_layer.group_send)(
                self.group,
                {"type": "shipment.event", "payload": payload},
            )

        except Exception as e:
            logger.exception("ws_error: %s", e)
            self.send_json({"type": "error", "detail": "internal_error"})

    def shipment_event(self, event):
        self.send_json(event["payload"])
