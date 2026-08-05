from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0013_create_test_user"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="courierkyc",
            options={
                "verbose_name": "Заявка специалиста",
                "verbose_name_plural": "Заявки специалистов",
            },
        ),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("carrier", "Специалист"),
                    ("client", "Клиент"),
                ],
                default="client",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="specialist_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("cart", "Тачкист"),
                    ("delivery", "Доставщик"),
                ],
                max_length=16,
                null=True,
                verbose_name="Тип специалиста",
            ),
        ),
    ]
