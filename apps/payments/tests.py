from django.db import models
from django.test import SimpleTestCase

from apps.payments.models import PaymentAttempt


class PaymentAttemptDeletionPolicyTests(SimpleTestCase):
    def test_payment_attempts_are_deleted_with_shipment(self):
        shipment_field = PaymentAttempt._meta.get_field("shipment")

        self.assertIs(shipment_field.remote_field.on_delete, models.CASCADE)
