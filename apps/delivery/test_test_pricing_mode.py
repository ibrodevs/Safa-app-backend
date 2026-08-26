import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.delivery.models import Shipment
from apps.delivery.lifecycle import mark_shipment_awaiting_payment
from apps.delivery.serializer import ShipmentDetailSerializer
from apps.payments.models import PaymentAttempt
from apps.users.models import User


def _user(phone: str, role: str) -> User:
    return User.objects.create_user(
        phone_number=phone,
        password="pass12345",
        first_name="Test",
        role=role,
        is_verify=True,
    )


@pytest.mark.django_db
@override_settings(
    SAFA_TEST_PRICING=True,
    SAFA_TEST_PRICE=1,
    FINIK_ACCOUNT_ID="finik-account",
    FINIK_API_KEY="finik-key",
    FINIK_CALLBACK_URL="https://api.example.com/api/payments/finik/callback/",
)
def test_test_pricing_is_visible_and_charged_but_preserves_real_fare():
    client_user = _user("996700559001", User.Roles.CLIENT)
    carrier = _user("996700559002", User.Roles.CARRIER)
    api = APIClient()
    api.force_authenticate(client_user)
    stops = [
        {"title": "Точка A", "lat": 42.84, "lon": 74.60},
        {"title": "Точка B", "lat": 42.88, "lon": 74.64},
    ]

    quote = api.post(
        "/api/delivery/shipments/quote/",
        {"stops": stops},
        format="json",
    )
    assert quote.status_code == 200
    assert quote.data["estimated_fare"] == 1

    created = api.post(
        "/api/delivery/shipments/",
        {
            "title": "Тест Finik за 1 сом",
            "service_type": Shipment.ServiceType.DELIVERY,
            "stops": stops,
        },
        format="json",
    )
    assert created.status_code == 201
    assert created.data["estimated_fare"] == 1

    shipment = Shipment.objects.get(pk=created.data["id"])
    real_fare = shipment.estimated_fare
    assert real_fare > 1

    shipment.carrier = carrier
    shipment.status = Shipment.Status.ASSIGNED
    shipment.final_fare = real_fare
    shipment.save(update_fields=["carrier", "status", "final_fare"])
    mark_shipment_awaiting_payment(shipment)

    detail = api.get(f"/api/delivery/shipments/{shipment.id}/")
    assert detail.status_code == 200
    assert detail.data["estimated_fare"] == 1
    assert detail.data["final_fare"] == 1
    assert detail.data["payment_due_amount"] == 1

    payment = api.post(f"/api/delivery/shipments/{shipment.id}/pay/finik/")
    assert payment.status_code == 201
    assert payment.data["amount"] == 1
    assert PaymentAttempt.objects.get(id=payment.data["paymentId"]).amount == 1

    # Выключение флага мгновенно возвращает сохранённую реальную цену.
    with override_settings(SAFA_TEST_PRICING=False, FINIK_TEST_AMOUNT=None):
        real_data = ShipmentDetailSerializer(shipment).data
        assert real_data["estimated_fare"] == real_fare
        assert real_data["final_fare"] == real_fare
        assert real_data["payment_due_amount"] == real_fare
