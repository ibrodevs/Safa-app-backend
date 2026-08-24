from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import Shipment
from .serializer import ShipmentDetailSerializer


def broadcast_shipment(shipment: Shipment) -> None:
    """Publish the latest shipment snapshot to connected clients."""

    layer = get_channel_layer()
    if layer is None:
        return
    data = ShipmentDetailSerializer(shipment).data
    async_to_sync(layer.group_send)(
        f"shipment_{shipment.id}",
        {"type": "shipment.event", "payload": data},
    )
