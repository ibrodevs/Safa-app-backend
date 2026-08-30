from decimal import Decimal

from rest_framework.test import APITestCase

from apps.delivery.models import Shipment, ShipmentReview
from apps.users.models import User


class ShipmentReviewTests(APITestCase):
    def setUp(self):
        self.client_user = User.objects.create_user(
            phone_number="996710001101",
            password="password",
            role=User.Roles.CLIENT,
            first_name="Client",
        )
        self.other_client = User.objects.create_user(
            phone_number="996710001102",
            password="password",
            role=User.Roles.CLIENT,
            first_name="Other",
        )
        self.carrier = User.objects.create_user(
            phone_number="996710001103",
            password="password",
            role=User.Roles.CARRIER,
            first_name="Carrier",
        )
        self.shipment = self._completed_shipment("First")

    def _completed_shipment(self, title):
        return Shipment.objects.create(
            client=self.client_user,
            carrier=self.carrier,
            title=title,
            status=Shipment.Status.COMPLETED,
            is_paid=True,
        )

    def _review_url(self, shipment=None):
        shipment = shipment or self.shipment
        return f"/api/delivery/shipments/{shipment.id}/review/"

    def test_client_can_review_completed_order_and_detail_exposes_it(self):
        self.client.force_authenticate(self.client_user)

        response = self.client.post(
            self._review_url(),
            {"rating": 5, "comment": "  Отличная работа  "},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        review = ShipmentReview.objects.get(shipment=self.shipment)
        self.assertEqual(review.rating, 5)
        self.assertEqual(review.comment, "Отличная работа")
        self.carrier.profile.refresh_from_db()
        self.assertEqual(self.carrier.profile.rate, Decimal("5.00"))
        self.assertEqual(self.carrier.profile.client_rate_count, 1)

        detail = self.client.get(f"/api/delivery/shipments/{self.shipment.id}/")
        self.assertEqual(detail.data["review"]["rating"], 5)
        self.assertEqual(detail.data["review"]["comment"], "Отличная работа")
        self.assertFalse(detail.data["can_review"])

    def test_profile_rating_is_average_of_five_star_reviews(self):
        self.client.force_authenticate(self.client_user)
        self.client.post(self._review_url(), {"rating": 5}, format="json")
        second = self._completed_shipment("Second")
        response = self.client.post(
            self._review_url(second),
            {"rating": 3, "comment": "Нормально"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.carrier.profile.refresh_from_db()
        self.assertEqual(self.carrier.profile.rate, Decimal("4.00"))
        self.assertEqual(self.carrier.profile.client_rate_count, 2)

    def test_order_accepts_only_one_review(self):
        self.client.force_authenticate(self.client_user)
        first = self.client.post(self._review_url(), {"rating": 4}, format="json")
        second = self.client.post(self._review_url(), {"rating": 1}, format="json")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.data["detail"], "review_already_exists")

    def test_other_client_cannot_review_order(self):
        self.client.force_authenticate(self.other_client)
        response = self.client.post(self._review_url(), {"rating": 5}, format="json")

        self.assertEqual(response.status_code, 404)

    def test_incomplete_order_cannot_be_reviewed(self):
        active = Shipment.objects.create(
            client=self.client_user,
            carrier=self.carrier,
            title="Active",
            status=Shipment.Status.IN_TRANSIT,
        )
        self.client.force_authenticate(self.client_user)
        response = self.client.post(self._review_url(active), {"rating": 5}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["detail"], "shipment_not_completed")

    def test_rating_must_be_between_one_and_five(self):
        self.client.force_authenticate(self.client_user)
        response = self.client.post(self._review_url(), {"rating": 6}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("rating", response.data)
