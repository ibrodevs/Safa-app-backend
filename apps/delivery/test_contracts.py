from rest_framework.test import APITestCase

from apps.delivery.models import Shipment, ShipmentStop
from apps.users.models import User


class ShipmentContractTests(APITestCase):
    def setUp(self):
        self.client_user = User.objects.create_user(phone_number="996710000001", password="password", role=User.Roles.CLIENT, first_name="Client")
        self.carrier = User.objects.create_user(phone_number="996710000002", password="password", role=User.Roles.CARRIER, first_name="Carrier")
        self.shipment = Shipment.objects.create(client=self.client_user, carrier=self.carrier, title="Test", status=Shipment.Status.ASSIGNED)
        ShipmentStop.objects.create(shipment=self.shipment, position=0, title="A", lat=42.87, lon=74.61)
        ShipmentStop.objects.create(shipment=self.shipment, position=1, title="B", lat=42.88, lon=74.62)

    def test_return_to_pending_releases_carrier(self):
        self.client.force_authenticate(self.carrier)
        response = self.client.post(f"/api/delivery/shipments/{self.shipment.id}/set_status/", {"status": Shipment.Status.PENDING}, format="json")
        self.assertEqual(response.status_code, 200)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, Shipment.Status.PENDING)
        self.assertIsNone(self.shipment.carrier_id)

    def test_detail_contains_persisted_route_progress(self):
        self.client.force_authenticate(self.carrier)
        response = self.client.get(f"/api/delivery/shipments/{self.shipment.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("current_stop_index", response.data)
        self.assertEqual(response.data["carrier_id"], self.carrier.id)

    def test_nearby_feed_rejects_client_role(self):
        self.client.force_authenticate(self.client_user)
        response = self.client.get("/api/delivery/shipments/nearby/?lat=42.87&lon=74.61")
        self.assertEqual(response.status_code, 403)

    def test_delete_cancels_without_erasing_record(self):
        self.client.force_authenticate(self.client_user)
        response = self.client.delete(f"/api/delivery/shipments/{self.shipment.id}/")
        self.assertEqual(response.status_code, 204)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, Shipment.Status.CANCELED)


    def test_two_stop_route_requires_start_then_complete(self):
        self.client.force_authenticate(self.carrier)
        self.shipment.current_stop_index = 0
        self.shipment.save(update_fields=["current_stop_index"])

        started = self.client.post(f"/api/delivery/shipments/{self.shipment.id}/advance/")
        self.assertEqual(started.status_code, 200)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, Shipment.Status.IN_TRANSIT)
        self.assertEqual(self.shipment.current_stop_index, 1)

        completed = self.client.post(f"/api/delivery/shipments/{self.shipment.id}/advance/")
        self.assertEqual(completed.status_code, 200)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, Shipment.Status.COMPLETED)
        self.assertTrue(self.shipment.rating_applied)
