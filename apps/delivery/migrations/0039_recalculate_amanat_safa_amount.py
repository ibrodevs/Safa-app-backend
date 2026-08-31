from django.db import migrations, models


def recalculate_amanat_safa_amount(apps, schema_editor):
    """Replace the seeded demo amount with verified order commissions."""

    AmanatCampaign = apps.get_model("delivery", "AmanatCampaign")
    CarrierSettlement = apps.get_model("payments", "CarrierSettlement")

    commission_total = CarrierSettlement.objects.aggregate(
        total=models.Sum("commission_amount")
    )["total"] or 0

    # safa_amount used to contain a demo value (706624). There was only one
    # commission beneficiary before this migration, so all verified settlement
    # commissions belong to the current featured Amanat campaign.
    AmanatCampaign.objects.update(safa_amount=0)
    campaign = (
        AmanatCampaign.objects.filter(
            title="Пожертвование на Медресе",
            status="active",
        ).first()
        or AmanatCampaign.objects.filter(
            status="active",
            is_featured=True,
        ).first()
        or AmanatCampaign.objects.filter(status="active").first()
    )
    if campaign is not None:
        AmanatCampaign.objects.filter(pk=campaign.pk).update(
            safa_amount=int(commission_total)
        )


class Migration(migrations.Migration):
    dependencies = [
        ("delivery", "0038_shipmentreview"),
        ("payments", "0008_complete_succeeded_attempt_shipments"),
    ]

    operations = [
        migrations.RunPython(
            recalculate_amanat_safa_amount,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
