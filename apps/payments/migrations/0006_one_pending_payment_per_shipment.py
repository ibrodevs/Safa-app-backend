from django.db import migrations, models
from django.db.models import Count


def close_duplicate_pending_attempts(apps, schema_editor):
    payment_attempt = apps.get_model("payments", "PaymentAttempt")
    duplicate_shipments = (
        payment_attempt.objects.filter(status="PENDING")
        .values("shipment_id")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )
    for row in duplicate_shipments.iterator():
        attempts = payment_attempt.objects.filter(
            shipment_id=row["shipment_id"],
            status="PENDING",
        ).order_by("-created_at", "-id")
        keeper_id = attempts.values_list("id", flat=True).first()
        attempts.exclude(id=keeper_id).update(status="FAILED")


class Migration(migrations.Migration):
    dependencies = [("payments", "0005_amanatpaymentattempt")]

    operations = [
        migrations.RunPython(
            close_duplicate_pending_attempts,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="paymentattempt",
            constraint=models.UniqueConstraint(
                fields=("shipment",),
                condition=models.Q(status="PENDING"),
                name="one_pending_payment_per_shipment",
            ),
        ),
    ]
