from django.db import migrations, models


def mark_existing_demo_shipments(apps, schema_editor):
    Shipment = apps.get_model("delivery", "Shipment")
    for shipment in Shipment.objects.only("id", "title", "description"):
        text = f"{shipment.title or ''} {shipment.description or ''}".strip().lower()
        if text.startswith(("demo", "демо")):
            Shipment.objects.filter(pk=shipment.pk).update(is_demo=True)


class Migration(migrations.Migration):
    dependencies = [("delivery", "0028_alter_amanatdonation_status")]

    operations = [
        migrations.AddField(
            model_name="shipment",
            name="is_demo",
            field=models.BooleanField(
                db_index=True,
                default=False,
                verbose_name="Демонстрационный заказ",
            ),
        ),
        migrations.RunPython(
            mark_existing_demo_shipments,
            migrations.RunPython.noop,
        ),
    ]
