from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from django.conf import settings

from apps.payments.models import AmanatPaymentAttempt, PaymentAttempt


class FinikVerificationUnavailable(Exception):
    """Finik could not be reached or returned an unusable response."""

    def __init__(self, code: str, provider_message: str = ""):
        super().__init__(code)
        self.code = code
        self.provider_message = provider_message[:240]


_GET_ITEM_QUERY = """
query VerifyFinikTransaction($input: ServiceInput!) {
  getItem(input: $input) {
    id
    requestId
    fixedAmount
    paymentCount
    transactionId
    account { id }
    requiredFields { fieldId value }
  }
}
"""

_LIST_ITEMS_QUERY = """
query FindFinikItem($input: ListServicesInput!) {
  listItems(input: $input) {
    services {
      __typename
      ... on Item {
        id
        requestId
        fixedAmount
        paymentCount
        transactionId
        account { id }
        requiredFields { fieldId value }
      }
    }
  }
}
"""

_CREATE_ITEM_QUERY = """
mutation RecoverFinikItem($input: CreateItemInput!) {
  createItem(input: $input) {
    id
    requestId
    fixedAmount
    paymentCount
    transactionId
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


def finik_item_matches_attempt(
    item: dict[str, Any],
    attempt: PaymentAttempt | AmanatPaymentAttempt,
    *,
    require_payment: bool = True,
) -> bool:
    """Validate that a Finik item belongs to one exact server attempt."""

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
        (not require_payment or payment_count >= 1)
        and amount_matches
        and str(item.get("requestId") or "") == attempt.finik_request_id
        and str(account.get("id") or "")
        == str(getattr(settings, "FINIK_ACCOUNT_ID", "") or "").strip()
        and fields.get("paymentId") == str(attempt.id)
        and fields.get("finikRequestId") == attempt.finik_request_id
        and target_matches
    )


def _finik_graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    api_key = str(getattr(settings, "FINIK_API_KEY", "") or "").strip()
    if not api_key:
        raise FinikVerificationUnavailable("finik_api_key_not_configured")

    try:
        response = requests.post(
            _graphql_url(),
            json={"query": query, "variables": variables},
            headers={
                "x-api-key": api_key,
                "content-type": "application/json",
                "accept": "application/json",
            },
            timeout=float(getattr(settings, "FINIK_TIMEOUT_SECONDS", 15)),
        )
        response.raise_for_status()
        payload = response.json()
    except requests.HTTPError as exc:
        status_code = getattr(exc.response, "status_code", None) or "unknown"
        raise FinikVerificationUnavailable(f"finik_http_{status_code}") from exc
    except requests.Timeout as exc:
        raise FinikVerificationUnavailable("finik_timeout") from exc
    except (requests.RequestException, ValueError) as exc:
        raise FinikVerificationUnavailable("finik_network_error") from exc

    if not isinstance(payload, dict):
        raise FinikVerificationUnavailable("finik_invalid_response")
    if payload.get("errors"):
        error = (payload.get("errors") or [{}])[0] or {}
        error_type = str((error.get("extensions") or {}).get("errorType") or "")
        message = str(error.get("message") or "").lower()
        if "unauthor" in error_type.lower() or "unauthor" in message:
            code = "finik_graphql_unauthorized"
        elif "validation" in error_type.lower() or "cannot query field" in message:
            code = "finik_graphql_schema_mismatch"
        else:
            code = "finik_graphql_error"
        provider_message = " ".join(str(error.get("message") or "").split())
        raise FinikVerificationUnavailable(code, provider_message)
    return payload


def _required_fields_for_attempt(
    attempt: PaymentAttempt | AmanatPaymentAttempt,
) -> list[dict[str, Any]]:
    values = {
        "paymentId": str(attempt.id),
        "finikRequestId": attempt.finik_request_id,
    }
    if isinstance(attempt, AmanatPaymentAttempt):
        values.update(
            {
                "paymentKind": "amanat",
                "donationId": str(attempt.donation_id),
                "campaignId": str(attempt.donation.campaign_id),
            }
        )
    else:
        values["shipmentId"] = str(attempt.shipment_id)
    return [
        {
            "fieldId": key,
            "isHidden": True,
            "value": value,
            "label_ru": key,
            "label_en": key,
            "label_ky": key,
        }
        for key, value in values.items()
    ]


def recover_finik_item_idempotently(
    attempt: PaymentAttempt | AmanatPaymentAttempt,
) -> dict[str, Any] | None:
    """Repeat the idempotent create request to recover its existing item ID."""

    account_id = str(getattr(settings, "FINIK_ACCOUNT_ID", "") or "").strip()
    callback_url = str(
        getattr(settings, "FINIK_CALLBACK_URL", "") or ""
    ).strip()
    item_name = str(
        getattr(settings, "FINIK_ITEM_NAME_EN", "Safa delivery payment")
        or "Safa delivery payment"
    ).strip()
    if isinstance(attempt, AmanatPaymentAttempt):
        description = f"Пожертвование Safa Amanat ({attempt.currency})"
    else:
        description = f"Заказ #{attempt.shipment_id} ({attempt.currency})"
    payload = _finik_graphql(
        _CREATE_ITEM_QUERY,
        {
            "input": {
                "account": {"id": account_id},
                "name_en": item_name,
                "requestId": attempt.finik_request_id,
                "fixedAmount": int(attempt.amount),
                "description": description,
                "callbackUrl": callback_url,
                "maxAvailableQuantity": 1,
                "visibilityType": "PRIVATE",
                "status": "ENABLED",
                "requiredFields": _required_fields_for_attempt(attempt),
            }
        },
    )
    item = (payload.get("data") or {}).get("createItem")
    if not isinstance(item, dict):
        return None
    return (
        item
        if finik_item_matches_attempt(item, attempt, require_payment=False)
        else None
    )


def find_finik_item_by_request_id(
    attempt: PaymentAttempt | AmanatPaymentAttempt,
) -> dict[str, Any] | None:
    """Recover an item when a callback and mobile item ID were lost."""

    first_error = None
    try:
        recovered = recover_finik_item_idempotently(attempt)
        if recovered:
            return recovered
    except FinikVerificationUnavailable as exc:
        first_error = exc

    account_id = str(getattr(settings, "FINIK_ACCOUNT_ID", "") or "").strip()
    search_inputs = [
        {
            "from": 0,
            "size": 100,
            "query": attempt.finik_request_id,
            "filter": {"accountId": account_id},
        },
        {
            "from": 0,
            "size": 200,
            "startDate": int(attempt.created_at.timestamp()) - 3600,
            "endDate": int(attempt.created_at.timestamp()) + 86400,
            "filter": {"accountId": account_id, "types": ["Item"]},
        },
        {
            "from": 0,
            "size": 200,
            "startDate": int(attempt.created_at.timestamp()) - 3600,
            "endDate": int(attempt.created_at.timestamp()) + 86400,
            "filter": {"accountId": account_id},
        },
    ]
    last_error = first_error
    had_successful_response = False
    for search_input in search_inputs:
        try:
            payload = _finik_graphql(
                _LIST_ITEMS_QUERY,
                {"input": search_input},
            )
        except FinikVerificationUnavailable as exc:
            last_error = exc
            continue
        had_successful_response = True
        services = ((payload.get("data") or {}).get("listItems") or {}).get(
            "services"
        ) or []
        for item in services:
            if not isinstance(item, dict):
                continue
            if str(item.get("requestId") or "") != attempt.finik_request_id:
                continue
            if finik_item_matches_attempt(item, attempt, require_payment=False):
                return item
    if last_error is not None and not had_successful_response:
        raise last_error
    return None


def verify_finik_payment(
    identifier: str,
    attempt: PaymentAttempt | AmanatPaymentAttempt,
    *,
    key_type: str = "TRANSACTION_ID",
) -> dict[str, Any] | None:
    """Return a verified paid Finik item bound to this server attempt."""

    payload = _finik_graphql(
        _GET_ITEM_QUERY,
        {
            "input": {
                "id": str(identifier),
                "keyType": key_type,
            }
        },
    )

    item = (payload.get("data") or {}).get("getItem")
    if not isinstance(item, dict):
        return None

    return item if finik_item_matches_attempt(item, attempt) else None


def verify_finik_transaction(
    transaction_id: str,
    attempt: PaymentAttempt | AmanatPaymentAttempt,
) -> bool:
    """Backward-compatible callback verification by transaction ID."""

    return (
        verify_finik_payment(
            transaction_id,
            attempt,
            key_type="TRANSACTION_ID",
        )
        is not None
    )
