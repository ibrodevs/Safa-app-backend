# Generated manually to allow deleting shipments together with their payment attempts.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("delivery", "0018_remove_amanatdonation_user_and_more"),
        ("payments", "0002_remove_paymentattempt_payments_pa_shipmen_de05ba_idx_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="paymentattempt",
            name="shipment",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="payment_attempts",
                to="delivery.shipment",
            ),
        ),
    ]
