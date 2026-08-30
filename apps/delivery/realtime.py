import logging
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import CourierPosition, Shipment
from .serializer import ShipmentDetailSerializer

logger = logging.getLogger(__name__)


def broadcast_shipment(shipment: Shipment) -> None:
    """Publish the latest shipment snapshot to connected clients."""
    try:
        layer = get_channel_layer()
        if layer is None:
            return
        data = ShipmentDetailSerializer(shipment).data
        async_to_sync(layer.group_send)(
            f"shipment_{shipment.id}",
            {"type": "shipment.event", "payload": data},
        )
    except Exception as exc:
        logger.exception("broadcast_shipment_failed shipment=%s: %s", getattr(shipment, "id", None), exc)


def courier_position_payload(
    shipment: Shipment,
    position: CourierPosition,
) -> dict:
    return {
        "type": "telemetry",
        "shipment_id": shipment.id,
        "status": shipment.status,
        "courier": {
            "lat": str(position.lat),
            "lon": str(position.lon),
            "updated_at": position.updated_at.isoformat(),
        },
    }


def broadcast_courier_position(position: CourierPosition) -> None:
    """Publish one GPS update to every active order of this specialist."""
    try:
        layer = get_channel_layer()
        if layer is None:
            return
        shipments = Shipment.objects.filter(
            carrier_id=position.user_id,
            status__in=(
                Shipment.Status.ASSIGNED,
                Shipment.Status.IN_TRANSIT,
                Shipment.Status.AWAITING_PAYMENT,
            ),
        ).only("id", "status")
        for shipment in shipments.iterator():
            async_to_sync(layer.group_send)(
                f"shipment_{shipment.id}",
                {
                    "type": "shipment.event",
                    "payload": courier_position_payload(shipment, position),
                },
            )
    except Exception as exc:
        logger.exception("broadcast_courier_position_failed: %s", exc)
