from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("delivery", "0036_faqitem_privacypolicy"),
    ]

    operations = [
        migrations.AlterField(
            model_name="deliverydistrict",
            name="per_km_price",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
                validators=[MinValueValidator(0)],
                verbose_name="Стоимость за км в районе",
            ),
        ),
        migrations.AlterField(
            model_name="deliverydistrict",
            name="min_fare",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
                validators=[MinValueValidator(0)],
                verbose_name="Минималка района",
            ),
        ),
        migrations.AlterField(
            model_name="globaldeliveryconfig",
            name="base_price",
            field=models.DecimalField(
                decimal_places=2,
                default=50,
                max_digits=10,
                validators=[MinValueValidator(0)],
                verbose_name="Базовая стоимость",
            ),
        ),
        migrations.AlterField(
            model_name="globaldeliveryconfig",
            name="per_km_price",
            field=models.DecimalField(
                decimal_places=2,
                default=20,
                max_digits=10,
                validators=[MinValueValidator(0)],
                verbose_name="Стоимость за км",
            ),
        ),
        migrations.AlterField(
            model_name="globaldeliveryconfig",
            name="min_fare",
            field=models.DecimalField(
                decimal_places=2,
                default=50,
                max_digits=10,
                validators=[MinValueValidator(0)],
                verbose_name="Минималка",
            ),
        ),
    ]
