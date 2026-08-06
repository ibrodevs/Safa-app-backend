from django.test import TestCase

from .map_models import MarketMapRevision
from .map_sync import sync_passages
from .models import Bazar, Passage


class PassageMapSyncTests(TestCase):
    def test_passage_feature_creates_catalog_record(self):
        bazar = Bazar.objects.create(name="Тестовый базар")
        revision = MarketMapRevision.objects.create(
            bazar=bazar,
            version=1,
            geojson={
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "id": "passage-1",
                        "properties": {
                            "kind": "passage",
                            "name": "12 проход",
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[74.60, 42.87], [74.61, 42.88]],
                        },
                    }
                ],
            },
        )

        sync_passages(revision)

        passage = Passage.objects.get(bazar=bazar, number="12 проход")
        revision.refresh_from_db()
        properties = revision.geojson["features"][0]["properties"]
        self.assertEqual(properties["passage_id"], passage.id)
        self.assertEqual(properties["number"], "12 проход")

    def test_existing_passage_is_not_duplicated(self):
        bazar = Bazar.objects.create(name="Второй базар")
        passage = Passage.objects.create(bazar=bazar, number="5")
        revision = MarketMapRevision.objects.create(
            bazar=bazar,
            version=1,
            geojson={
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "kind": "passage",
                            "name": "5",
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[74.60, 42.87], [74.61, 42.88]],
                        },
                    }
                ],
            },
        )

        sync_passages(revision)

        self.assertEqual(Passage.objects.filter(bazar=bazar, number="5").count(), 1)
        revision.refresh_from_db()
        self.assertEqual(
            revision.geojson["features"][0]["properties"]["passage_id"],
            passage.id,
        )
