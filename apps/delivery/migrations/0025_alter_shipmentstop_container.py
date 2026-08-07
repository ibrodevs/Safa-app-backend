import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("delivery", "0024_medrese_amanat_campaign"),
    ]

    operations = [
        migrations.AlterField(
            model_name="shipmentstop",
            name="container",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="shipment_stops",
                to="delivery.container",
                verbose_name="Контейнер",
            ),
        ),
    ]
