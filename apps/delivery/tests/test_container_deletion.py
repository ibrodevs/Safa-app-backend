from django.contrib.auth import get_user_model
from decimal import Decimal

from django.test import TestCase

from apps.delivery.models import Bazar, Container, Passage, Shipment, ShipmentStop


class ContainerDeletionTests(TestCase):
    def test_container_can_be_deleted_without_deleting_order_history(self):
        user = get_user_model().objects.create_user(
            phone_number="996700000001",
            password="test-password",
            first_name="Test",
        )
        bazar = Bazar.objects.create(name="Test bazar")
        passage = Passage.objects.create(bazar=bazar, number="1")
        container = Container.objects.create(
            passage=passage,
            number="10",
            title="Test container",
            lat="42.870000",
            lon="74.590000",
        )
        shipment = Shipment.objects.create(client=user, title="Test shipment")
        stop = ShipmentStop.objects.create(
            shipment=shipment,
            container=container,
            position=0,
        )
        original_title = stop.title
        original_lat = stop.lat
        original_lon = stop.lon

        container.delete()

        stop.refresh_from_db()
        self.assertIsNone(stop.container_id)
        self.assertEqual(stop.title, original_title)
        self.assertEqual(stop.lat, Decimal(original_lat))
        self.assertEqual(stop.lon, Decimal(original_lon))
        self.assertTrue(Shipment.objects.filter(pk=shipment.pk).exists())
