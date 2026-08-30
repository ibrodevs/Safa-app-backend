from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


def reset_legacy_automatic_rating(apps, schema_editor):
    UserProfile = apps.get_model("users", "UserProfile")
    UserProfile.objects.all().update(rate=0, client_rate_count="0")


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0015_reopen_auto_approved_kyc"),
    ]

    operations = [
        migrations.RunPython(reset_legacy_automatic_rating, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="userprofile",
            name="rate",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=3,
                validators=[MinValueValidator(0), MaxValueValidator(5)],
                verbose_name="Средняя оценка",
            ),
        ),
        migrations.AlterField(
            model_name="userprofile",
            name="client_rate_count",
            field=models.PositiveIntegerField(
                default=0,
                verbose_name="Сколько клиентов оценили",
            ),
        ),
    ]
