from django.db import transaction
from django.utils import timezone

from apps.notification.events import notify_shipment_status

from .models import Shipment
from .realtime import broadcast_shipment


@transaction.atomic
def cancel_shipment(
    shipment: Shipment,
    *,
    protect_terminal: bool = True,
    emit_events: bool = True,
) -> Shipment:
    locked = Shipment.objects.select_for_update().get(pk=shipment.pk)
    if protect_terminal and locked.status in (
        Shipment.Status.AWAITING_PAYMENT,
        Shipment.Status.COMPLETED,
        Shipment.Status.CANCELED,
    ):
        raise ValueError("terminal_shipment")
    locked.status = Shipment.Status.CANCELED
    locked.save(update_fields=["status"])
    if emit_events:
        notify_shipment_status(locked)
        broadcast_shipment(locked)
    return locked


def reestimate_shipment(
    shipment: Shipment,
    *,
    protect_terminal: bool = True,
    emit_events: bool = True,
) -> Shipment:
    if protect_terminal and shipment.status in (
        Shipment.Status.COMPLETED,
        Shipment.Status.CANCELED,
    ):
        raise ValueError("terminal_shipment")
    shipment.estimate()
    shipment.save(update_fields=["distance_km", "estimated_fare"])
    if emit_events:
        broadcast_shipment(shipment)
    return shipment


def sync_shipment_admin_state(shipment: Shipment) -> Shipment:
    """Keep manual staff edits consistent with shipment lifecycle timestamps."""
    now = timezone.now()
    if shipment.is_paid:
        shipment.paid_at = shipment.paid_at or now
    else:
        shipment.paid_at = None

    if shipment.status == Shipment.Status.COMPLETED:
        shipment.work_completed_at = shipment.work_completed_at or now
        shipment.finished_at = shipment.finished_at or now
    elif shipment.status == Shipment.Status.AWAITING_PAYMENT:
        shipment.work_completed_at = shipment.work_completed_at or now
        shipment.finished_at = None
    elif shipment.status == Shipment.Status.CANCELED:
        shipment.finished_at = shipment.finished_at or now
    else:
        shipment.work_completed_at = None
        shipment.finished_at = None
    return shipment


def normalize_shipment_stops(shipment: Shipment) -> Shipment:
    for index, stop in enumerate(shipment.stops.order_by("position", "id")):
        if stop.position != index:
            type(stop).objects.filter(pk=stop.pk).update(position=index)
    shipment.estimate()
    shipment.save(update_fields=["distance_km", "estimated_fare"])
    return shipment
