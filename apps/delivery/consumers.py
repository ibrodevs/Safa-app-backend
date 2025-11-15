# apps/delivery/consumers.py
from __future__ import annotations

from decimal import Decimal

from asgiref.sync import async_to_sync
from channels.generic.websocket import JsonWebsocketConsumer
from django.contrib.auth.models import AnonymousUser
from django.db import transaction
from django.utils import timezone

from .models import Shipment, CourierPosition, ARRIVAL_RADIUS_M
from .geo import haversine_m


def _clamp_speed(v) -> Decimal | None:
    """Обрезаем скорость до [0; 120] км/ч."""
    if v is None:
        return None
    v = Decimal(str(v))
    if v < 0:
        return Decimal("0.0")
    if v > 120:
        return Decimal("120.0")
    return v


class ShipmentTrackingConsumer(JsonWebsocketConsumer):
    """
    WS: /ws/shipments/<shipment_id>/?token=<JWT_ACCESS>

    Входящие сообщения:
      { "type": "loc", "lat": 42.874, "lon": 74.612 }
      { "type": "loc", "lat": 42.874, "lon": 74.612, "speed_kmh": 20 }
      { "type": "ping" }

    Ответы:
      - {"type": "telemetry", ...}
      - {"type": "error", "detail": "..."}
      - либо payload из REST через _broadcast(shipment)
    """

    # ---------- lifecycle ----------

    def connect(self):
        self.shipment_id = int(self.scope["url_route"]["kwargs"]["shipment_id"])
        self.group = f"shipment_{self.shipment_id}"
        async_to_sync(self.channel_layer.group_add)(self.group, self.channel_name)
        self.accept()

    def disconnect(self, code):
        group = getattr(self, "group", None)
        if group:
            async_to_sync(self.channel_layer.group_discard)(group, self.channel_name)

    # ---------- входящие сообщения ----------

    def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        if msg_type == "loc":
            self._on_location(content)
        elif msg_type == "ping":
            self.send_json({"type": "pong"})
        else:
            self.send_json({"type": "error", "detail": "bad_payload"})

    # ---------- логика трекинга ----------

    def _on_location(self, content: dict):
        user = self.scope.get("user")
        if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
            self.send_json({"type": "error", "detail": "unauthenticated"})
            return

        # координаты
        try:
            lat = Decimal(str(content.get("lat")))
            lon = Decimal(str(content.get("lon")))
        except (TypeError, ValueError, ArithmeticError):
            self.send_json({"type": "error", "detail": "bad_payload"})
            return

        client_speed = _clamp_speed(content.get("speed_kmh"))

        # посылка
        try:
            shipment: Shipment = (
                Shipment.objects
                .select_related("segment", "carrier")
                .prefetch_related("stops__container")
                .get(id=self.shipment_id)
            )
        except Shipment.DoesNotExist:
            self.send_json({"type": "error", "detail": "not_found"})
            return

        # только назначенный курьер
        if shipment.carrier_id != user.id:
            self.send_json({
                "type": "error",
                "detail": "forbidden",
                "carrier_id": shipment.carrier_id,
                "user_id": user.id,
            })
            return

        # атомарно: обновляем позицию и ETA
        with transaction.atomic():
            pos, created = (
                CourierPosition.objects
                .select_for_update()
                .get_or_create(
                    user=user,
                    defaults={"lat": lat, "lon": lon, "speed_kmh": client_speed},
                )
            )

            if created:
                speed = client_speed
            else:
                prev_lat, prev_lon, prev_at = pos.lat, pos.lon, pos.updated_at
                now = timezone.now()
                dt_s = max((now - prev_at).total_seconds(), 1.0)

                # расстояние между двумя точками в метрах
                dist_m = haversine_m(
                    float(prev_lat),
                    float(prev_lon),
                    float(lat),
                    float(lon),
                )
                dist_km = Decimal(dist_m / 1000.0)

                server_speed = (dist_km / Decimal(dt_s) * Decimal("3600")).quantize(
                    Decimal("0.1")
                )
                speed = client_speed if client_speed is not None else _clamp_speed(server_speed)

                pos.lat = lat
                pos.lon = lon
                pos.speed_kmh = speed
                pos.save(update_fields=["lat", "lon", "speed_kmh"])

            # расстояние до следующей остановки
            dist_m_to_target = shipment.distance_to_next_m(float(lat), float(lon))
            arrived = dist_m_to_target <= ARRIVAL_RADIUS_M

            if arrived:
                stops = list(shipment.stops.order_by("position"))
                if shipment.current_stop_index >= len(stops) - 1:
                    shipment.status = Shipment.Status.COMPLETED
                    shipment.finalize()
                else:
                    shipment.current_stop_index += 1
                    shipment.eta_to_next_min = Decimal("0.0")
            else:
                if speed and speed > 0 and dist_m_to_target > 0:
                    eta = (
                        (dist_m_to_target / Decimal("1000")) / speed * Decimal("60")
                    ).quantize(Decimal("0.1"))
                else:
                    eta = None
                shipment.eta_to_next_min = eta or Decimal("0.0")

            shipment.save(
                update_fields=[
                    "current_stop_index",
                    "eta_to_next_min",
                    "status",
                    "final_fare",
                ]
            )

        payload = {
            "type": "telemetry",
            "shipment_id": shipment.id,
            "status": shipment.status,
            "courier": {
                "lat": str(lat),
                "lon": str(lon),
                "speed_kmh": str(speed) if speed is not None else None,
            },
            "target_index": shipment.current_stop_index,
            "distance_m": str(dist_m_to_target),
            "eta_min": str(shipment.eta_to_next_min) if shipment.eta_to_next_min else None,
        }

        async_to_sync(self.channel_layer.group_send)(
            self.group,
            {"type": "shipment.event", "payload": payload},
        )


    def shipment_event(self, event):
        self.send_json(event["payload"])
