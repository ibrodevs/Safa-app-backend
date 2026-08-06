from django.db import migrations


def seed_medrese_amanat(apps, schema_editor):
    AmanatCategory = apps.get_model("delivery", "AmanatCategory")
    AmanatCampaign = apps.get_model("delivery", "AmanatCampaign")

    education, _ = AmanatCategory.objects.update_or_create(
        slug="education",
        defaults={
            "name": "Образование",
            "sort_order": 40,
            "is_active": True,
        },
    )

    AmanatCampaign.objects.filter(
        title__in=["Айдане на операцию", "Тимуру на лечение"],
    ).update(is_featured=False, status="canceled")

    AmanatCampaign.objects.update_or_create(
        title="Пожертвование на Медресе",
        defaults={
            "category": education,
            "short_title": "Пожертвование\nна Медресе",
            "description": (
                "Сбор открыт для поддержки Медресе: оплаты учебных материалов, "
                "бытовых нужд и условий для учеников."
            ),
            "goal": "Направить пожертвования на нужды Медресе.",
            "needed_amount": 1600000,
            "collected_amount_manual": 650000,
            "safa_amount": 706624,
            "helpers_count_manual": 842,
            "ends_at": "2026-12-31",
            "is_featured": True,
            "sort_order": 0,
            "status": "active",
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("delivery", "0023_deliverydistrict_bazar_tariffs"),
    ]

    operations = [
        migrations.RunPython(seed_medrese_amanat, migrations.RunPython.noop),
    ]
