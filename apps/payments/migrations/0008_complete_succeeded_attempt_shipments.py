from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import migrations
from django.utils import timezone


def complete_succeeded_attempt_shipments(apps, schema_editor):
    PaymentAttempt = apps.get_model("payments", "PaymentAttempt")
    CarrierSettlement = apps.get_model("payments", "CarrierSettlement")
    Shipment = apps.get_model("delivery", "Shipment")

    commission_pct = Decimal(
        str(getattr(settings, "PLATFORM_COMMISSION_PCT", Decimal("0")))
    )
    attempts = PaymentAttempt.objects.filter(status="SUCCEEDED").iterator()
    for attempt in attempts:
        try:
            shipment = Shipment.objects.get(pk=attempt.shipment_id)
        except Shipment.DoesNotExist:
            continue

        paid_at = shipment.paid_at or attempt.updated_at or timezone.now()
        shipment.is_paid = True
        shipment.paid_at = paid_at

        # A successful order necessarily had an assigned specialist. If old
        # inconsistent data has no specialist, preserve it for manual review
        # instead of creating a settlement for the wrong user.
        if shipment.carrier_id and shipment.status in {
            "awaiting_payment",
            "completed",
        }:
            shipment.status = "completed"
            shipment.finished_at = shipment.finished_at or paid_at

        shipment.save(
            update_fields=["is_paid", "paid_at", "status", "finished_at"]
        )

        if not shipment.carrier_id or shipment.status != "completed":
            continue
        if CarrierSettlement.objects.filter(shipment_id=shipment.id).exists():
            continue

        gross = int(attempt.amount)
        commission = int(
            (Decimal(gross) * commission_pct).quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP,
            )
        )
        net = gross - commission
        if gross <= 0 or net < 0:
            continue
        CarrierSettlement.objects.create(
            shipment_id=shipment.id,
            payment_attempt_id=attempt.id,
            carrier_id=shipment.carrier_id,
            gross_amount=gross,
            commission_amount=commission,
            net_amount=net,
            currency=attempt.currency,
            credited_at=paid_at,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0007_sync_succeeded_attempt_shipments"),
    ]

    operations = [
        migrations.RunPython(
            complete_succeeded_attempt_shipments,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
