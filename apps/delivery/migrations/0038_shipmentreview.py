import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("delivery", "0037_validate_delivery_prices"),
        ("users", "0016_userprofile_five_star_rating"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShipmentReview",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "rating",
                    models.PositiveSmallIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(5),
                        ],
                        verbose_name="Оценка",
                    ),
                ),
                ("comment", models.TextField(blank=True, max_length=1000, verbose_name="Комментарий")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Оставлен")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Изменён")),
                (
                    "shipment",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="review",
                        to="delivery.shipment",
                        verbose_name="Заказ",
                    ),
                ),
            ],
            options={
                "verbose_name": "Отзыв о специалисте",
                "verbose_name_plural": "Отзывы о специалистах",
                "ordering": ("-created_at",),
            },
        ),
    ]
