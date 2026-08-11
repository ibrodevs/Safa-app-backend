import hashlib

import pytest
from django.test import override_settings
from django.utils import timezone
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
    carrier = User.objects.create_user(
        phone_number="996700123457",
        password="secret123",
        first_name="Carrier",
        role=User.Roles.CARRIER,
    )
    return Shipment.objects.create(
        client=client,
        carrier=carrier,
        title="Delivery",
        estimated_fare=450,
        final_fare=450,
        status=Shipment.Status.AWAITING_PAYMENT,
        work_completed_at=timezone.now(),
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
    assert shipment.status == Shipment.Status.COMPLETED
    assert shipment.finished_at is not None
    assert attempt.status == PaymentAttempt.Status.SUCCEEDED
    assert attempt.finik_transaction_id == "transaction-123"
    assert attempt.finik_item_id == "item-123"
    settlement = shipment.carrier_settlement
    assert settlement.gross_amount == 450
    assert settlement.commission_amount == 45
    assert settlement.net_amount == 405


@pytest.mark.django_db
@override_settings(FINIK_ACCOUNT_ID=ACCOUNT_ID)
def test_callback_accepts_lowercase_status_and_nested_account_id():
    shipment = _shipment()
    attempt = _attempt(shipment)
    payload = _callback(attempt, status="succeeded")
    payload.pop("accountId")
    payload["data"] = {"accountId": ACCOUNT_ID}

    response = APIClient().post(
        "/api/payments/finik/callback/",
        payload,
        format="json",
    )

    assert response.status_code == 200
    shipment.refresh_from_db()
    assert shipment.is_paid is True
    assert shipment.status == Shipment.Status.COMPLETED


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
@override_settings(FINIK_ACCOUNT_ID=ACCOUNT_ID)
def test_repeated_callback_does_not_credit_carrier_twice():
    shipment = _shipment()
    attempt = _attempt(shipment)
    client = APIClient()
    payload = _callback(attempt)

    first = client.post("/api/payments/finik/callback/", payload, format="json")
    second = client.post("/api/payments/finik/callback/", payload, format="json")

    assert first.status_code == 200
    assert second.status_code == 200
    assert shipment.carrier_settlement.pk
    assert shipment.__class__.objects.get(pk=shipment.pk).status == Shipment.Status.COMPLETED
    assert shipment.carrier.carrier_settlements.count() == 1

    client.force_authenticate(shipment.carrier)
    wallet = client.get("/api/payments/carrier/wallet/")
    assert wallet.status_code == 200
    assert wallet.data["balance"] == 405
    assert wallet.data["settlements"][0]["shipment"] == shipment.id


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


@pytest.mark.django_db
@override_settings(
    FINIK_ACCOUNT_ID=ACCOUNT_ID,
    FINIK_API_KEY="api-key",
    FINIK_TEST_AMOUNT=1,
)
def test_test_amount_is_used_for_payment_and_settlement():
    shipment = _shipment()
    client = APIClient()
    client.force_authenticate(shipment.client)

    init_response = client.post(
        f"/api/delivery/shipments/{shipment.id}/pay/finik/"
    )

    assert init_response.status_code == 201
    assert init_response.data["amount"] == 1
    attempt = PaymentAttempt.objects.get(id=init_response.data["paymentId"])
    assert attempt.amount == 1

    callback_response = APIClient().post(
        "/api/payments/finik/callback/",
        _callback(attempt, amount="1.00"),
        format="json",
    )

    assert callback_response.status_code == 200
    shipment.refresh_from_db()
    assert shipment.status == Shipment.Status.COMPLETED
    assert shipment.carrier_settlement.gross_amount == 1
    assert shipment.carrier_settlement.commission_amount == 0
    assert shipment.carrier_settlement.net_amount == 1


@pytest.mark.django_db
@override_settings(
    FINIK_ACCOUNT_ID=ACCOUNT_ID,
    FINIK_API_KEY="api-key",
    FINIK_BETA=False,
    FINIK_TEST_AMOUNT=1,
    FINIK_CALLBACK_URL="https://example.com/api/payments/finik/callback/",
)
def test_public_config_reports_payment_flow_without_exposing_secrets():
    response = APIClient().get("/api/payments/finik/config/")

    assert response.status_code == 200
    assert response.data == {
        "paymentFlowVersion": 2,
        "configured": True,
        "keyFingerprint": hashlib.sha256(b"api-key").hexdigest()[:16],
        "beta": False,
        "testAmount": 1,
        "callbackUrl": "https://example.com/api/payments/finik/callback/",
    }
    assert "api-key" not in str(response.data)
