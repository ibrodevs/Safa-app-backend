from django.db import migrations


def sync_succeeded_attempt_shipments(apps, schema_editor):
    PaymentAttempt = apps.get_model("payments", "PaymentAttempt")
    Shipment = apps.get_model("delivery", "Shipment")

    for attempt in PaymentAttempt.objects.filter(status="SUCCEEDED").iterator():
        Shipment.objects.filter(pk=attempt.shipment_id, is_paid=False).update(
            is_paid=True,
            paid_at=attempt.updated_at,
        )
        Shipment.objects.filter(pk=attempt.shipment_id, paid_at__isnull=True).update(
            paid_at=attempt.updated_at,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("delivery", "0030_performance_indexes"),
        ("payments", "0006_one_pending_payment_per_shipment"),
    ]

    operations = [
        migrations.RunPython(
            sync_succeeded_attempt_shipments,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
