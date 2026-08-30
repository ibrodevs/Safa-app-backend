from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.delivery.map_cleanup import purge_bazar_map
from apps.delivery.map_models import MarketMapRevision
from apps.delivery.models import (
    Bazar,
    Container,
    DeliveryDistrict,
    Passage,
    Shipment,
    ShipmentStop,
)
from apps.users.models import User


class MapCleanupTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            phone_number="996700000030",
            password="test-password",
            first_name="Admin",
            is_staff=True,
        )
        self.client.force_login(self.staff)

        self.district = DeliveryDistrict.objects.create(name="Ленинский")
        self.bazar = Bazar.objects.create(
            name="Дордой",
            top_left_lat=Decimal("42.900000"),
            top_left_lon=Decimal("74.600000"),
            bottom_right_lat=Decimal("42.880000"),
            bottom_right_lon=Decimal("74.620000"),
        )
        self.other_bazar = Bazar.objects.create(name="Ошский")
        self.other_passage = Passage.objects.create(bazar=self.other_bazar, number="1")

        self.passage = Passage.objects.create(bazar=self.bazar, number="7")
        self.container = Container.objects.create(
            passage=self.passage,
            number="701",
            title="Ткани",
            lat=Decimal("42.890000"),
            lon=Decimal("74.610000"),
        )
        self.revision = MarketMapRevision.objects.create(
            bazar=self.bazar,
            version=1,
            status=MarketMapRevision.Status.PUBLISHED,
            geojson={
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "id": "district-1",
                        "properties": {
                            "kind": "district",
                            "name": "Ленинский",
                            "district_tariff_id": self.district.pk,
                        },
                        "geometry": {"type": "Polygon", "coordinates": [[]]},
                    }
                ],
            },
        )

        client = User.objects.create_user(
            phone_number="996700000031",
            password="test-password",
            first_name="Customer",
        )
        self.shipment = Shipment.objects.create(client=client, title="Документы")
        self.stop = ShipmentStop.objects.create(
            shipment=self.shipment,
            container=self.container,
            position=1,
        )

    def test_purge_removes_map_with_passages_and_containers(self):
        stats = purge_bazar_map(self.bazar)

        self.assertEqual(stats["districts"], 1)
        self.assertEqual(stats["passages"], 1)
        self.assertEqual(stats["containers"], 1)
        self.assertEqual(stats["detached_stops"], 1)

        self.assertFalse(MarketMapRevision.objects.filter(bazar=self.bazar).exists())
        self.assertFalse(Passage.objects.filter(bazar=self.bazar).exists())
        self.assertFalse(Container.objects.filter(pk=self.container.pk).exists())

        # Базар и общий справочник районов не трогаем.
        self.assertTrue(Bazar.objects.filter(pk=self.bazar.pk).exists())
        self.assertTrue(DeliveryDistrict.objects.filter(pk=self.district.pk).exists())

        # Чужой базар остаётся нетронутым.
        self.assertTrue(Passage.objects.filter(pk=self.other_passage.pk).exists())

    def test_purge_keeps_shipment_history(self):
        purge_bazar_map(self.bazar)

        self.stop.refresh_from_db()
        self.assertIsNone(self.stop.container_id)
        self.assertEqual(self.stop.lat, Decimal("42.890000"))
        self.assertEqual(self.stop.lon, Decimal("74.610000"))
        self.assertTrue(self.stop.title)

    def test_purge_clears_legacy_rectangle_so_map_does_not_return(self):
        purge_bazar_map(self.bazar)

        self.bazar.refresh_from_db()
        self.assertIsNone(self.bazar.top_left_lat)
        self.assertIsNone(self.bazar.bottom_right_lon)

        revision, _ = MarketMapRevision.get_or_create_draft(bazar=self.bazar)
        self.assertEqual(revision.geojson["features"], [])

    def test_panel_map_delete_endpoint(self):
        response = self.client.post(
            reverse("admin_panel:map_delete", args=(self.bazar.pk,))
        )

        self.assertRedirects(response, reverse("admin_panel:districts"))
        self.assertFalse(MarketMapRevision.objects.filter(bazar=self.bazar).exists())
        self.assertFalse(Container.objects.filter(pk=self.container.pk).exists())
        self.assertTrue(Bazar.objects.filter(pk=self.bazar.pk).exists())

    def test_panel_map_delete_rejects_get(self):
        response = self.client.get(
            reverse("admin_panel:map_delete", args=(self.bazar.pk,))
        )

        self.assertEqual(response.status_code, 405)
        self.assertTrue(MarketMapRevision.objects.filter(bazar=self.bazar).exists())

    def test_panel_bazar_delete_removes_bazar_with_everything(self):
        response = self.client.post(
            reverse("admin_panel:catalog_bazar_delete", args=(self.bazar.pk,))
        )

        self.assertRedirects(response, reverse("admin_panel:bazars"))
        self.assertFalse(Bazar.objects.filter(pk=self.bazar.pk).exists())
        self.assertFalse(Passage.objects.filter(pk=self.passage.pk).exists())
        self.assertFalse(Container.objects.filter(pk=self.container.pk).exists())
        self.assertTrue(Bazar.objects.filter(pk=self.other_bazar.pk).exists())

    def test_panel_passage_delete_takes_its_containers(self):
        response = self.client.post(
            reverse("admin_panel:passage_delete", args=(self.passage.pk,))
        )

        self.assertRedirects(response, reverse("admin_panel:passages"))
        self.assertFalse(Passage.objects.filter(pk=self.passage.pk).exists())
        self.assertFalse(Container.objects.filter(pk=self.container.pk).exists())

    def test_panel_container_delete_detaches_shipment_stop(self):
        response = self.client.post(
            reverse("admin_panel:container_delete", args=(self.container.pk,))
        )

        self.assertRedirects(response, reverse("admin_panel:containers"))
        self.assertFalse(Container.objects.filter(pk=self.container.pk).exists())
        self.stop.refresh_from_db()
        self.assertIsNone(self.stop.container_id)

    def test_django_admin_delete_view_does_not_block_on_protected_objects(self):
        self.staff.is_superuser = True
        self.staff.save(update_fields=["is_superuser"])

        response = self.client.post(
            reverse("admin:delivery_bazar_delete", args=(self.bazar.pk,)),
            {"post": "yes"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Bazar.objects.filter(pk=self.bazar.pk).exists())
        self.assertFalse(Passage.objects.filter(pk=self.passage.pk).exists())
        self.assertFalse(Container.objects.filter(pk=self.container.pk).exists())
