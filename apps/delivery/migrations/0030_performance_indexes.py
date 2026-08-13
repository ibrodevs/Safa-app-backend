from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("delivery", "0029_shipment_is_demo"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="container",
            index=models.Index(
                fields=["is_active", "lat", "lon"],
                name="container_viewport_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="shipment",
            index=models.Index(
                fields=["status", "carrier", "is_demo", "created_at"],
                name="shipment_nearby_idx",
            ),
        ),
    ]
