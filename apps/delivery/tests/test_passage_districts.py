from importlib import import_module

from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.delivery.map_models import MarketMapRevision
from apps.delivery.map_validation import (
    district_name_for_geometry,
    iter_district_features,
)
from apps.delivery.models import Bazar, Container, Passage
from apps.users.models import User


def _polygon(x0, y0, x1, y1):
    return {
        "type": "Polygon",
        "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
    }


def _district(feature_id, name, x0, y0, x1, y1):
    return {
        "type": "Feature",
        "id": feature_id,
        "properties": {"kind": "district", "name": name},
        "geometry": _polygon(x0, y0, x1, y1),
    }


def _passage(feature_id, number, x0, x1, y):
    return {
        "type": "Feature",
        "id": feature_id,
        "properties": {"kind": "passage", "name": number, "number": number},
        "geometry": {"type": "LineString", "coordinates": [[x0, y], [x1, y]]},
    }


def _container(feature_id, number, passage_feature_id, x, y):
    return {
        "type": "Feature",
        "id": feature_id,
        "properties": {
            "kind": "container",
            "name": number,
            "number": number,
            "passage_feature_id": passage_feature_id,
        },
        "geometry": {"type": "Point", "coordinates": [x, y]},
    }


def _map_with_two_districts():
    """Базар с районами А и Б, в каждом — «1 проход» и контейнер «10»."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "bazar-1",
                "properties": {"kind": "bazar", "name": "Дордой"},
                "geometry": _polygon(74.600, 42.880, 74.620, 42.900),
            },
            _district("district-a", "Район А", 74.601, 42.881, 74.609, 42.889),
            _district("district-b", "Район Б", 74.611, 42.881, 74.619, 42.889),
            _passage("passage-a", "1", 74.602, 74.608, 42.882),
            _passage("passage-b", "1", 74.612, 74.618, 42.882),
            _container("container-a", "10", "passage-a", 74.603, 42.8825),
            _container("container-b", "10", "passage-b", 74.613, 42.8825),
        ],
    }


class PassageDistrictGeometryTests(TestCase):
    def test_district_is_chosen_by_majority_of_points(self):
        districts = iter_district_features(_map_with_two_districts())
        self.assertEqual(len(districts), 2)

        line = {"type": "LineString", "coordinates": [[74.602, 42.882], [74.608, 42.882]]}
        self.assertEqual(district_name_for_geometry(line, districts), "Район А")

    def test_object_outside_every_district_has_no_district(self):
        districts = iter_district_features(_map_with_two_districts())
        outside = {"type": "LineString", "coordinates": [[74.6095, 42.899], [74.6105, 42.899]]}
        self.assertEqual(district_name_for_geometry(outside, districts), "")


class PassageDistrictSyncTests(TestCase):
    def setUp(self):
        self.bazar = Bazar.objects.create(name="Дордой")

    def _save_draft(self, geojson):
        revision, _ = MarketMapRevision.get_or_create_draft(bazar=self.bazar)
        revision.geojson = geojson
        revision.full_clean()
        revision.save(update_fields=("geojson", "updated_at"))
        revision.refresh_from_db()
        return revision

    def test_same_number_in_two_districts_creates_two_passages(self):
        revision = self._save_draft(_map_with_two_districts())

        passages = Passage.objects.filter(bazar=self.bazar).order_by("district")
        self.assertEqual(
            [(item.district, item.number) for item in passages],
            [("Район А", "1"), ("Район Б", "1")],
        )

        features = {feature["id"]: feature["properties"] for feature in revision.geojson["features"]}
        self.assertNotEqual(
            features["passage-a"]["passage_id"],
            features["passage-b"]["passage_id"],
        )
        self.assertEqual(features["passage-a"]["district"], "Район А")
        self.assertEqual(features["passage-b"]["district"], "Район Б")

    def test_containers_with_same_number_keep_their_own_coordinates(self):
        revision = self._save_draft(_map_with_two_districts())
        revision.publish()

        containers = Container.objects.order_by("passage__district")
        self.assertEqual(containers.count(), 2)
        self.assertEqual(
            [str(item.lon) for item in containers],
            ["74.603000", "74.613000"],
        )
        self.assertEqual(
            [item.passage.district for item in containers],
            ["Район А", "Район Б"],
        )

    def test_passage_number_stays_unique_inside_one_district(self):
        geojson = _map_with_two_districts()
        # Проход, нарисованный двумя кусками в одном районе, — это один проход.
        geojson["features"].append(_passage("passage-a2", "1", 74.603, 74.607, 42.884))
        revision = self._save_draft(geojson)

        self.assertEqual(Passage.objects.filter(bazar=self.bazar, district="Район А").count(), 1)
        features = {feature["id"]: feature["properties"] for feature in revision.geojson["features"]}
        self.assertEqual(
            features["passage-a"]["passage_id"],
            features["passage-a2"]["passage_id"],
        )

    def test_moving_passage_into_occupied_district_reports_the_district(self):
        self._save_draft(_map_with_two_districts())

        geojson = _map_with_two_districts()
        # Тащим проход из района А в район Б, где номер «1» уже занят.
        moved = next(item for item in geojson["features"] if item["id"] == "passage-a")
        moved["properties"]["passage_id"] = Passage.objects.get(district="Район А", number="1").pk
        moved["geometry"] = {"type": "LineString", "coordinates": [[74.612, 42.885], [74.618, 42.885]]}
        for feature in geojson["features"]:
            if feature["id"] == "passage-b":
                feature["properties"]["passage_id"] = Passage.objects.get(
                    district="Район Б", number="1"
                ).pk

        with self.assertRaises(ValidationError) as error:
            self._save_draft(geojson)
        self.assertIn("Район Б", str(error.exception))

    def test_passage_follows_its_district_when_moved_to_a_free_one(self):
        geojson = _map_with_two_districts()
        geojson["features"].append(_district("district-c", "Район В", 74.601, 42.891, 74.609, 42.897))
        self._save_draft(geojson)
        passage = Passage.objects.get(district="Район А", number="1")

        for feature in geojson["features"]:
            if feature["properties"].get("kind") != "passage":
                continue
            feature["properties"]["passage_id"] = Passage.objects.get(
                district="Район А" if feature["id"] == "passage-a" else "Район Б",
                number="1",
            ).pk
        moved = next(item for item in geojson["features"] if item["id"] == "passage-a")
        moved["geometry"] = {"type": "LineString", "coordinates": [[74.602, 42.893], [74.608, 42.893]]}
        # Контейнер уезжает вместе со своим проходом, иначе он останется вне района.
        container = next(item for item in geojson["features"] if item["id"] == "container-a")
        container["geometry"] = {"type": "Point", "coordinates": [74.603, 42.8935]}
        self._save_draft(geojson)

        passage.refresh_from_db()
        self.assertEqual(passage.district, "Район В")
        self.assertEqual(Passage.objects.filter(bazar=self.bazar).count(), 2)


class PassageDistrictCatalogTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            phone_number="996700000040",
            password="test-password",
            first_name="Admin",
            is_staff=True,
        )
        self.client.force_login(self.staff)
        self.bazar = Bazar.objects.create(name="Дордой")

    def test_panel_allows_the_same_number_in_another_district(self):
        first = self.client.post(
            reverse("admin_panel:passage_create"),
            {"bazar": self.bazar.pk, "district": "Район А", "number": "1"},
        )
        self.assertEqual(first.status_code, 302)

        second = self.client.post(
            reverse("admin_panel:passage_create"),
            {"bazar": self.bazar.pk, "district": "Район Б", "number": "1"},
        )
        self.assertEqual(second.status_code, 302)
        self.assertEqual(Passage.objects.filter(bazar=self.bazar, number="1").count(), 2)

    def test_panel_still_blocks_a_duplicate_inside_one_district(self):
        payload = {"bazar": self.bazar.pk, "district": "Район А", "number": "1"}
        self.assertEqual(self.client.post(reverse("admin_panel:passage_create"), payload).status_code, 302)

        response = self.client.post(reverse("admin_panel:passage_create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Passage.objects.filter(bazar=self.bazar, number="1").count(), 1)

    def test_container_label_names_the_district(self):
        passage = Passage.objects.create(bazar=self.bazar, district="Район А", number="1")
        container = Container.objects.create(
            passage=passage,
            number="10",
            lat="42.882500",
            lon="74.603000",
        )

        self.assertEqual(container.ui_label, "Контейнер 10, 1 проход · Район А")
        self.assertIn("Район А", container.display_title)

    def test_container_label_without_district_is_unchanged(self):
        passage = Passage.objects.create(bazar=self.bazar, number="1")
        container = Container.objects.create(
            passage=passage,
            number="10",
            lat="42.882500",
            lon="74.603000",
        )

        self.assertEqual(container.ui_label, "Контейнер 10, 1 проход")


class PassageDistrictBackfillTests(TestCase):
    """Миграция 0031 проставляет район уже существующим проходам."""

    def test_backfill_fills_districts_from_the_published_map(self):
        bazar = Bazar.objects.create(name="Дордой")
        passage_a = Passage.objects.create(bazar=bazar, number="1")
        passage_b = Passage.objects.create(bazar=bazar, number="2")

        geojson = _map_with_two_districts()
        for feature in geojson["features"]:
            if feature["id"] == "passage-a":
                feature["properties"]["passage_id"] = passage_a.pk
            elif feature["id"] == "passage-b":
                feature["properties"]["number"] = "2"
                feature["properties"]["name"] = "2"
                feature["properties"]["passage_id"] = passage_b.pk
        MarketMapRevision.objects.create(
            bazar=bazar,
            version=1,
            status=MarketMapRevision.Status.PUBLISHED,
            geojson=geojson,
        )

        migration = import_module("apps.delivery.migrations.0031_passage_district")
        migration.backfill_passage_districts(django_apps, None)

        passage_a.refresh_from_db()
        passage_b.refresh_from_db()
        self.assertEqual(passage_a.district, "Район А")
        self.assertEqual(passage_b.district, "Район Б")
