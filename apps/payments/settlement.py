from django.db import transaction
from django.utils import timezone

from apps.delivery.models import Shipment
from apps.payments.models import CarrierSettlement, PaymentAttempt


def complete_paid_shipment(
    *,
    shipment: Shipment,
    payment_attempt: PaymentAttempt,
) -> CarrierSettlement:
    """Complete a paid shipment and credit its carrier exactly once."""

    if not shipment.carrier_id:
        raise ValueError("shipment_has_no_carrier")
    if not shipment.is_paid:
        raise ValueError("shipment_is_not_paid")
    if shipment.status not in (
        Shipment.Status.AWAITING_PAYMENT,
        Shipment.Status.COMPLETED,
    ):
        raise ValueError("shipment_is_not_ready_for_settlement")

    gross = int(shipment.final_fare or shipment.estimated_fare or 0)
    commission = int(shipment.commission_amount)
    net = gross - commission
    if gross <= 0 or net < 0:
        raise ValueError("invalid_settlement_amount")

    with transaction.atomic():
        locked = Shipment.objects.select_for_update().get(pk=shipment.pk)
        existing = CarrierSettlement.objects.filter(shipment=locked).first()
        if existing:
            return existing

        locked.status = Shipment.Status.COMPLETED
        locked.finished_at = locked.finished_at or timezone.now()
        locked.save(update_fields=["status", "finished_at"])

        settlement = CarrierSettlement.objects.create(
            shipment=locked,
            payment_attempt=payment_attempt,
            carrier_id=locked.carrier_id,
            gross_amount=gross,
            commission_amount=commission,
            net_amount=net,
            currency=payment_attempt.currency,
        )

    shipment.status = Shipment.Status.COMPLETED
    shipment.finished_at = locked.finished_at
    return settlement
