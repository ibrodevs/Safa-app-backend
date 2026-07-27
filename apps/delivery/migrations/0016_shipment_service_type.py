from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("delivery", "0015_remove_bazar_coordinates_bazar_bottom_right_lat_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="shipment",
            name="service_type",
            field=models.CharField(
                choices=[
                    ("amanat", "Аманат"),
                    ("cars", "Тачки"),
                    ("delivery", "Доставка"),
                ],
                default="delivery",
                max_length=20,
                verbose_name="Тип услуги",
            ),
        ),
    ]
