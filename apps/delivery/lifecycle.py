from django.utils import timezone

from .models import Shipment


def mark_shipment_awaiting_payment(shipment: Shipment) -> Shipment:
    """Freeze the fare after the carrier finishes, without completing payment."""

    if shipment.status == Shipment.Status.AWAITING_PAYMENT:
        return shipment
    if shipment.status not in (
        Shipment.Status.ASSIGNED,
        Shipment.Status.IN_TRANSIT,
    ):
        raise ValueError("shipment_cannot_await_payment")
    if not shipment.carrier_id:
        raise ValueError("shipment_has_no_carrier")

    shipment.final_fare = int(shipment.final_fare or shipment.estimated_fare or 0)
    if shipment.final_fare <= 0:
        raise ValueError("shipment_has_no_final_fare")
    shipment.status = Shipment.Status.AWAITING_PAYMENT
    shipment.work_completed_at = shipment.work_completed_at or timezone.now()
    shipment.save(
        update_fields=["status", "final_fare", "work_completed_at"]
    )
    return shipment
