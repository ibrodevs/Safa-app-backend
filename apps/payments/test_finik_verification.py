from unittest.mock import Mock, patch

import pytest
from django.test import override_settings

from apps.delivery.models import AmanatCampaign, AmanatCategory, AmanatDonation, Shipment
from apps.payments.finik import (
    find_finik_item_by_request_id,
    verify_finik_transaction,
)
from apps.payments.models import AmanatPaymentAttempt, PaymentAttempt
from apps.users.models import User


@pytest.mark.django_db
@override_settings(
    FINIK_API_KEY="api-key",
    FINIK_ACCOUNT_ID="account-123",
    FINIK_BETA=True,
    FINIK_TIMEOUT_SECONDS=9,
)
@patch("apps.payments.finik.requests.post")
def test_transaction_is_verified_against_finik_item(mock_post):
    user = User.objects.create_user(
        phone_number="996700555111",
        password="secret123",
        first_name="Client",
    )
    shipment = Shipment.objects.create(client=user, title="Delivery")
    attempt = PaymentAttempt.objects.create(
        shipment=shipment,
        amount=450,
        finik_request_id="request-123",
    )
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "data": {
            "getItem": {
                "id": "item-123",
                "requestId": "request-123",
                "fixedAmount": 450.0,
                "paymentCount": 1,
                "account": {"id": "account-123"},
                "requiredFields": [
                    {"fieldId": "paymentId", "value": str(attempt.id)},
                    {"fieldId": "finikRequestId", "value": "request-123"},
                    {"fieldId": "shipmentId", "value": str(shipment.id)},
                ],
            }
        }
    }
    mock_post.return_value = response

    assert verify_finik_transaction("transaction-123", attempt) is True
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["variables"]["input"] == {
        "id": "transaction-123",
        "keyType": "TRANSACTION_ID",
    }
    assert "beta.api.paymentsgateway.averspay.kg" in mock_post.call_args.args[0]


@pytest.mark.django_db
@override_settings(FINIK_API_KEY="api-key", FINIK_ACCOUNT_ID="account-123")
@patch("apps.payments.finik.requests.post")
def test_transaction_with_wrong_amount_is_rejected(mock_post):
    user = User.objects.create_user(
        phone_number="996700555222",
        password="secret123",
        first_name="Client",
    )
    shipment = Shipment.objects.create(client=user, title="Delivery")
    attempt = PaymentAttempt.objects.create(
        shipment=shipment,
        amount=450,
        finik_request_id="request-456",
    )
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "data": {
            "getItem": {
                "requestId": "request-456",
                "fixedAmount": 1,
                "paymentCount": 1,
                "account": {"id": "account-123"},
                "requiredFields": [],
            }
        }
    }
    mock_post.return_value = response

    assert verify_finik_transaction("transaction-456", attempt) is False


@pytest.mark.django_db
@override_settings(FINIK_API_KEY="api-key", FINIK_ACCOUNT_ID="account-123")
@patch("apps.payments.finik.requests.post")
def test_item_can_be_recovered_by_exact_request_id(mock_post):
    user = User.objects.create_user(
        phone_number="996700555229",
        password="secret123",
        first_name="Client",
    )
    shipment = Shipment.objects.create(client=user, title="Delivery")
    attempt = PaymentAttempt.objects.create(
        shipment=shipment,
        amount=450,
        finik_request_id="lost-request-123",
    )
    item = {
        "__typename": "Item",
        "id": "recovered-item-123",
        "requestId": attempt.finik_request_id,
        "fixedAmount": 450,
        "paymentCount": 1,
        "transactionId": "transaction-123",
        "account": {"id": "account-123"},
        "requiredFields": [
            {"fieldId": "paymentId", "value": str(attempt.id)},
            {"fieldId": "finikRequestId", "value": attempt.finik_request_id},
            {"fieldId": "shipmentId", "value": str(shipment.id)},
        ],
    }
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "data": {"listItems": {"services": [item]}}
    }
    mock_post.return_value = response

    assert find_finik_item_by_request_id(attempt) == item
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["variables"]["input"]["query"] == attempt.finik_request_id
    assert kwargs["json"]["variables"]["input"]["filter"] == {
        "accountId": "account-123",
        "types": ["Item"],
    }


@pytest.mark.django_db
@override_settings(FINIK_API_KEY="api-key", FINIK_ACCOUNT_ID="account-123")
@patch("apps.payments.finik.requests.post")
def test_amanat_transaction_is_bound_to_exact_donation(mock_post):
    user = User.objects.create_user(
        phone_number="996700555333",
        password="secret123",
        first_name="Donor",
    )
    category = AmanatCategory.objects.create(
        slug="verification-test",
        name="Verification test",
    )
    campaign = AmanatCampaign.objects.create(
        category=category,
        title="Medrese",
        needed_amount=10000,
    )
    donation = AmanatDonation.objects.create(
        campaign=campaign,
        donor=user,
        amount=500,
    )
    attempt = AmanatPaymentAttempt.objects.create(
        donation=donation,
        amount=500,
        finik_request_id="amanat-request-123",
    )
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "data": {
            "getItem": {
                "requestId": "amanat-request-123",
                "fixedAmount": 500,
                "paymentCount": 1,
                "account": {"id": "account-123"},
                "requiredFields": [
                    {"fieldId": "paymentId", "value": str(attempt.id)},
                    {
                        "fieldId": "finikRequestId",
                        "value": "amanat-request-123",
                    },
                    {"fieldId": "paymentKind", "value": "amanat"},
                    {"fieldId": "donationId", "value": str(donation.id)},
                    {"fieldId": "campaignId", "value": str(campaign.id)},
                ],
            }
        }
    }
    mock_post.return_value = response

    assert verify_finik_transaction("amanat-transaction-123", attempt) is True
