from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

import apps.delivery.map_validation


class Migration(migrations.Migration):
    dependencies = [
        ("delivery", "0016_add_shipment_service_type"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MarketMapRevision",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("version", models.PositiveIntegerField(verbose_name="Версия")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Черновик"),
                            ("published", "Опубликована"),
                            ("archived", "Архив"),
                        ],
                        db_index=True,
                        default="draft",
                        max_length=16,
                        verbose_name="Статус",
                    ),
                ),
                (
                    "geojson",
                    models.JSONField(
                        default=apps.delivery.map_validation.empty_feature_collection,
                        verbose_name="GeoJSON",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создана")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Изменена")),
                ("published_at", models.DateTimeField(blank=True, null=True, verbose_name="Опубликована")),
                (
                    "bazar",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="map_revisions",
                        to="delivery.bazar",
                        verbose_name="Базар",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_market_maps",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Автор",
                    ),
                ),
            ],
            options={
                "verbose_name": "Карта базара",
                "verbose_name_plural": "Карты базаров",
                "ordering": ("bazar__name", "-version"),
            },
        ),
        migrations.AddConstraint(
            model_name="marketmaprevision",
            constraint=models.UniqueConstraint(
                fields=("bazar", "version"),
                name="uniq_market_map_bazar_version",
            ),
        ),
        migrations.AddIndex(
            model_name="marketmaprevision",
            index=models.Index(
                fields=["bazar", "status", "-version"],
                name="market_map_lookup_idx",
            ),
        ),
    ]
