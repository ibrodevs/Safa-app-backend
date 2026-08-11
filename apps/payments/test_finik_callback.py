import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.delivery.models import Shipment
from apps.payments.models import PaymentAttempt
from apps.users.models import User


ACCOUNT_ID = "finik-account-123"


@pytest.fixture(autouse=True)
def mock_finik_server_verification(monkeypatch):
    monkeypatch.setattr(
        "apps.payments.views.verify_finik_transaction",
        lambda transaction_id, attempt: True,
    )


def _shipment():
    client = User.objects.create_user(
        phone_number="996700123456",
        password="secret123",
        first_name="Client",
    )
    return Shipment.objects.create(
        client=client,
        title="Delivery",
        estimated_fare=450,
        final_fare=450,
    )


def _attempt(shipment):
    return PaymentAttempt.objects.create(
        shipment=shipment,
        amount=450,
        currency="KGS",
        finik_request_id="request-id-123",
    )


def _callback(attempt, **overrides):
    payload = {
        "status": "SUCCEEDED",
        "accountId": ACCOUNT_ID,
        "amount": "450.00",
        "transactionId": "transaction-123",
        "item": {"id": "item-123"},
        "fields": {
            "paymentId": str(attempt.id),
            "finikRequestId": attempt.finik_request_id,
            "shipmentId": str(attempt.shipment_id),
        },
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
@override_settings(FINIK_ACCOUNT_ID=ACCOUNT_ID)
def test_verified_success_callback_marks_shipment_paid_and_records_ids():
    shipment = _shipment()
    attempt = _attempt(shipment)

    response = APIClient().post(
        "/api/payments/finik/callback/",
        _callback(attempt),
        format="json",
    )

    assert response.status_code == 200
    shipment.refresh_from_db()
    attempt.refresh_from_db()
    assert shipment.is_paid is True
    assert shipment.paid_at is not None
    assert attempt.status == PaymentAttempt.Status.SUCCEEDED
    assert attempt.finik_transaction_id == "transaction-123"
    assert attempt.finik_item_id == "item-123"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "override",
    [
        {"accountId": "wrong-account"},
        {"amount": "449.00"},
        {"fields": {
            "paymentId": "placeholder",
            "finikRequestId": "wrong-request",
            "shipmentId": "1",
        }},
    ],
)
@override_settings(FINIK_ACCOUNT_ID=ACCOUNT_ID)
def test_callback_must_match_server_created_payment(override):
    shipment = _shipment()
    attempt = _attempt(shipment)
    if override.get("fields", {}).get("paymentId") == "placeholder":
        override["fields"]["paymentId"] = str(attempt.id)
        override["fields"]["shipmentId"] = str(attempt.shipment_id)

    response = APIClient().post(
        "/api/payments/finik/callback/",
        _callback(attempt, **override),
        format="json",
    )

    assert response.status_code == 400
    shipment.refresh_from_db()
    attempt.refresh_from_db()
    assert shipment.is_paid is False
    assert attempt.status == PaymentAttempt.Status.PENDING


@pytest.mark.django_db
@override_settings(FINIK_ACCOUNT_ID=ACCOUNT_ID)
def test_callback_is_rejected_when_finik_does_not_confirm_transaction(monkeypatch):
    monkeypatch.setattr(
        "apps.payments.views.verify_finik_transaction",
        lambda transaction_id, attempt: False,
    )
    shipment = _shipment()
    attempt = _attempt(shipment)

    response = APIClient().post(
        "/api/payments/finik/callback/",
        _callback(attempt),
        format="json",
    )

    assert response.status_code == 400
    shipment.refresh_from_db()
    assert shipment.is_paid is False


@pytest.mark.django_db
@override_settings(
    FINIK_ACCOUNT_ID=ACCOUNT_ID,
    FINIK_API_KEY="api-key",
    FINIK_CALLBACK_URL="",
)
def test_payment_init_derives_callback_url_and_returns_account_id():
    shipment = _shipment()
    client = APIClient()
    client.force_authenticate(shipment.client)

    response = client.post(f"/api/delivery/shipments/{shipment.id}/pay/finik/")

    assert response.status_code == 201
    assert response.data["callbackUrl"].endswith("/api/payments/finik/callback/")
    assert response.data["accountId"] == ACCOUNT_ID
    assert response.data["requiredFields"]["finikRequestId"] == response.data["finikRequestId"]
