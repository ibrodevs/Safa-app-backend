import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.delivery.models import Bazar, Container, Passage, Shipment
from apps.payments.amounts import payment_amount_for_shipment
from apps.payments.models import PaymentAttempt
from apps.users.models import User


@pytest.mark.django_db
def test_carrier_cannot_create_client_order():
    carrier = User.objects.create_user(
        phone_number="996700940001",
        password="secret123",
        first_name="Carrier",
        role=User.Roles.CARRIER,
    )
    bazar = Bazar.objects.create(name="Role test", fixed_price=300)
    passage = Passage.objects.create(bazar=bazar, number="1")
    Container.objects.create(passage=passage, number="1", lat=42.87, lon=74.60)
    Container.objects.create(passage=passage, number="2", lat=42.88, lon=74.61)
    api = APIClient()
    api.force_authenticate(carrier)

    response = api.post(
        "/api/delivery/shipments/",
        {
            "title": "Forbidden",
            "service_type": "delivery",
            "stops": [
                {"bazar": bazar.name, "passage": passage.number, "container": "1"},
                {"bazar": bazar.name, "passage": passage.number, "container": "2"},
            ],
        },
        format="json",
    )

    assert response.status_code == 403
    assert Shipment.objects.count() == 0


@pytest.mark.django_db
@override_settings(FINIK_ACCOUNT_ID="account", FINIK_API_KEY="key")
def test_repeated_payment_init_reuses_pending_attempt():
    client = User.objects.create_user(
        phone_number="996700940002", password="secret123", first_name="Client"
    )
    carrier = User.objects.create_user(
        phone_number="996700940003",
        password="secret123",
        first_name="Carrier",
        role=User.Roles.CARRIER,
    )
    shipment = Shipment.objects.create(
        client=client,
        carrier=carrier,
        title="Idempotent payment",
        status=Shipment.Status.AWAITING_PAYMENT,
        estimated_fare=500,
        final_fare=500,
        work_completed_at=timezone.now(),
    )
    api = APIClient()
    api.force_authenticate(client)

    first = api.post(f"/api/delivery/shipments/{shipment.id}/pay/finik/")
    second = api.post(f"/api/delivery/shipments/{shipment.id}/pay/finik/")

    assert first.status_code == second.status_code == 201
    assert first.data["paymentId"] == second.data["paymentId"]
    assert PaymentAttempt.objects.filter(shipment=shipment).count() == 1


@pytest.mark.django_db
@override_settings(DEBUG=False, FINIK_BETA=False, FINIK_TEST_AMOUNT=1)
def test_production_ignores_accidental_finik_test_amount():
    shipment = Shipment(estimated_fare=450, final_fare=450)
    assert payment_amount_for_shipment(shipment) == 450
