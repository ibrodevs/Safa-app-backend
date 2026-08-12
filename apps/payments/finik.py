from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from django.conf import settings

from apps.payments.models import AmanatPaymentAttempt, PaymentAttempt


class FinikVerificationUnavailable(Exception):
    """Finik could not be reached or returned an unusable response."""


_GET_ITEM_QUERY = """
query VerifyFinikTransaction($input: ServiceInput!) {
  getItem(input: $input) {
    id
    requestId
    fixedAmount
    paymentCount
    account { id }
    requiredFields { fieldId value }
  }
}
"""


def _graphql_url() -> str:
    override = str(getattr(settings, "FINIK_GRAPHQL_URL", "") or "").strip()
    if override:
        return override

    beta = bool(getattr(settings, "FINIK_BETA", False))
    api_key = str(getattr(settings, "FINIK_API_KEY", "") or "").strip()
    if api_key.startswith("da2-"):
        domain = "beta.graphql.averspay.kg" if beta else "graphql.averspay.kg"
        return f"https://{domain}/graphql"

    domain = (
        "beta.api.paymentsgateway.averspay.kg/v1"
        if beta
        else "api.paymentsgateway.averspay.kg/v1"
    )
    return f"https://{domain}/graphql"


def _required_field_map(item: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for field in item.get("requiredFields") or []:
        if not isinstance(field, dict) or not field.get("fieldId"):
            continue
        result[str(field["fieldId"])] = str(field.get("value") or "")
    return result


def verify_finik_transaction(
    transaction_id: str,
    attempt: PaymentAttempt | AmanatPaymentAttempt,
) -> bool:
    """Confirm that Finik knows a paid transaction for this exact attempt."""

    api_key = str(getattr(settings, "FINIK_API_KEY", "") or "").strip()
    if not api_key:
        raise FinikVerificationUnavailable("finik_api_key_not_configured")

    try:
        response = requests.post(
            _graphql_url(),
            json={
                "query": _GET_ITEM_QUERY,
                "variables": {
                    "input": {
                        "id": str(transaction_id),
                        "keyType": "TRANSACTION_ID",
                    }
                },
            },
            headers={
                "x-api-key": api_key,
                "content-type": "application/json",
                "accept": "application/json",
            },
            timeout=float(getattr(settings, "FINIK_TIMEOUT_SECONDS", 15)),
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise FinikVerificationUnavailable("finik_verification_unavailable") from exc

    if not isinstance(payload, dict) or payload.get("errors"):
        raise FinikVerificationUnavailable("finik_verification_invalid_response")

    item = (payload.get("data") or {}).get("getItem")
    if not isinstance(item, dict):
        return False

    try:
        amount_matches = Decimal(str(item.get("fixedAmount"))) == Decimal(
            attempt.amount
        )
        payment_count = int(item.get("paymentCount") or 0)
    except (InvalidOperation, TypeError, ValueError):
        return False

    account = item.get("account") or {}
    fields = _required_field_map(item)
    if isinstance(attempt, AmanatPaymentAttempt):
        target_matches = (
            fields.get("paymentKind") == "amanat"
            and fields.get("donationId") == str(attempt.donation_id)
            and fields.get("campaignId") == str(attempt.donation.campaign_id)
        )
    else:
        target_matches = fields.get("shipmentId") == str(attempt.shipment_id)
    return (
        payment_count >= 1
        and amount_matches
        and str(item.get("requestId") or "") == attempt.finik_request_id
        and str(account.get("id") or "")
        == str(getattr(settings, "FINIK_ACCOUNT_ID", "") or "").strip()
        and fields.get("paymentId") == str(attempt.id)
        and fields.get("finikRequestId") == attempt.finik_request_id
        and target_matches
    )
