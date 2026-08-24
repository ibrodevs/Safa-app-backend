from django.db import migrations


def reopen_auto_approved_kyc(apps, schema_editor):
    CourierKYC = apps.get_model("users", "CourierKYC")
    User = apps.get_model("users", "User")

    auto_approved_user_ids = list(
        CourierKYC.objects.filter(
            status="approved",
            checked_at__isnull=True,
            user__role="carrier",
        ).values_list("user_id", flat=True)
    )
    if not auto_approved_user_ids:
        return

    CourierKYC.objects.filter(user_id__in=auto_approved_user_ids).update(
        status="pending",
        comment="",
    )
    User.objects.filter(
        pk__in=auto_approved_user_ids,
        role="carrier",
    ).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0014_user_specialist_type"),
    ]

    operations = [
        migrations.RunPython(
            reopen_auto_approved_kyc,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
