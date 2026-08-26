from django.db import migrations


def sync_existing_map_districts(apps, schema_editor):
    MarketMapRevision = apps.get_model("delivery", "MarketMapRevision")
    DeliveryDistrict = apps.get_model("delivery", "DeliveryDistrict")

    names = set()
    revisions = MarketMapRevision.objects.filter(
        status__in=("draft", "published")
    ).only("geojson")
    for revision in revisions.iterator():
        for feature in (revision.geojson or {}).get("features", []):
            properties = feature.get("properties") or {}
            if properties.get("kind") != "district":
                continue
            name = str(properties.get("name") or "").strip()
            if name:
                names.add(name)

    existing = {
        str(name).strip().casefold()
        for name in DeliveryDistrict.objects.values_list("name", flat=True)
        if str(name).strip()
    }
    for name in sorted(names, key=str.casefold):
        if name.casefold() in existing:
            continue
        DeliveryDistrict.objects.create(name=name, is_active=True)
        existing.add(name.casefold())


class Migration(migrations.Migration):
    dependencies = [
        ("delivery", "0032_passage_angle"),
    ]

    operations = [
        migrations.RunPython(sync_existing_map_districts, migrations.RunPython.noop),
    ]
