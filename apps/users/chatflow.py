import re
from typing import Any
from urllib.parse import urljoin

import requests
from django.conf import settings


class ChatFlowError(Exception):
    """Safe, user-displayable Chatflow integration error."""


def _normalized_phone(phone: str) -> str:
    digits = re.sub(r"\D+", "", str(phone))
    if not re.fullmatch(r"996\d{9}", digits):
        raise ChatFlowError("phone_must_be_996XXXXXXXXX")
    return digits


def _setting(name: str) -> str:
    return str(getattr(settings, name, "") or "").strip()


def _error_message(response: requests.Response, data: Any) -> str:
    if isinstance(data, dict):
        for key in ("message", "error", "detail", "response"):
            value = data.get(key)
            if value:
                return str(value)[:300]
    return f"http_{response.status_code}"


def chatflow_send_text(phone: str, msg: str) -> None:
    """Send an OTP through the current Chatflow API or its legacy API.

    New Chatflow accounts use a Bearer token and Flow ID on app.chatflow.kz.
    CHATFLOW_INSTANCE_ID remains supported for installations that still use the
    legacy lk.chatflow.kz endpoint.
    """

    token = _setting("CHATFLOW_TOKEN")
    flow_id = _setting("CHATFLOW_FLOW_ID")
    instance_id = _setting("CHATFLOW_INSTANCE_ID")
    if not token:
        raise ChatFlowError("chatflow_token_not_configured")
    if not flow_id and not instance_id:
        raise ChatFlowError("chatflow_flow_id_not_configured")

    recipient = _normalized_phone(phone)
    base_url = _setting("CHATFLOW_BASE_URL") or "https://app.chatflow.kz"
    timeout = float(getattr(settings, "CHATFLOW_TIMEOUT_SECONDS", 15))

    if flow_id:
        url = urljoin(f"{base_url.rstrip('/')}/", "api/v1/n8n/action/text")
        params = {"flow_id": flow_id, "recipient": recipient, "msg": str(msg)}
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
    else:
        url = urljoin(f"{base_url.rstrip('/')}/", "api/v1/send-text")
        params = {
            "token": token,
            "instance_id": instance_id,
            "jid": f"{recipient}@c.us",
            "msg": str(msg),
        }
        headers = {"Accept": "application/json"}

    try:
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise ChatFlowError("chatflow_unavailable") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise ChatFlowError(f"chatflow_invalid_response_{response.status_code}") from exc

    if not response.ok:
        raise ChatFlowError(_error_message(response, data))

    if data is True:
        return
    if isinstance(data, dict) and data.get("success") is not False:
        return

    raise ChatFlowError(_error_message(response, data))
