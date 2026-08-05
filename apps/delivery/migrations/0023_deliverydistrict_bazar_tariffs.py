from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("delivery", "0022_alter_marketdistrictmapsection_options"),
    ]

    operations = [
        migrations.CreateModel(
            name="DeliveryDistrict",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=155, unique=True, verbose_name="Район")),
                ("fixed_price", models.PositiveIntegerField(blank=True, null=True, verbose_name="Фиксированная цена внутри района")),
                ("base_price", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name="Базовая стоимость района")),
                ("per_km_price", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name="Стоимость за км в районе")),
                ("min_fare", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name="Минималка района")),
                ("is_active", models.BooleanField(default=True, verbose_name="Активен")),
            ],
            options={
                "verbose_name": "Тариф района",
                "verbose_name_plural": "Тарифы районов",
                "ordering": ["name"],
            },
        ),
        migrations.AddField(
            model_name="bazar",
            name="district_tariff",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="bazars",
                to="delivery.deliverydistrict",
                verbose_name="Тариф района",
            ),
        ),
        migrations.AddField(
            model_name="bazar",
            name="fixed_price",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="Фиксированная цена базара"),
        ),
    ]
