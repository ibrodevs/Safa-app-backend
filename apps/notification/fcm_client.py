# apps/notifications/fcm_client.py
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Mapping, Any, Optional

import requests
import google.auth.transport.requests
from google.oauth2 import service_account
from django.conf import settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]

_session = requests.Session()
_credentials: Optional[service_account.Credentials] = None


def _fcm_config_error() -> str | None:
    project_id = str(getattr(settings, "FCM_PROJECT_ID", "") or "").strip()
    service_account_file = str(
        getattr(settings, "FCM_SERVICE_ACCOUNT_FILE", "") or ""
    ).strip()

    if not project_id:
        return "FCM_PROJECT_ID is empty"
    if not service_account_file:
        return "FCM_SERVICE_ACCOUNT_FILE is empty"
    if not Path(service_account_file).is_file():
        return f"FCM_SERVICE_ACCOUNT_FILE does not exist: {service_account_file}"
    return None


def _get_credentials() -> service_account.Credentials:
    global _credentials
    if _credentials is None:
        _credentials = service_account.Credentials.from_service_account_file(
            settings.FCM_SERVICE_ACCOUNT_FILE,
            scopes=SCOPES,
        )
    return _credentials


def _get_access_token() -> str:
    creds = _get_credentials()
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)
    return creds.token


def send_data_message(
    *,
    token: str,
    data: Mapping[str, Any],
    ttl: str = "15s",
    collapse_key: str | None = None,
) -> None:
    """
    Отправка data-only сообщения в FCM HTTP v1.
    `data`-ключи обязательно строковые.
    """
    if not token:
        return

    config_error = _fcm_config_error()
    if config_error:
        logger.warning("FCM send skipped: %s", config_error)
        return

    project_id = settings.FCM_PROJECT_ID
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

    android: dict[str, Any] = {
        "priority": "HIGH",
        "ttl": ttl,
    }
    if collapse_key:
        android["collapse_key"] = collapse_key

    message: dict[str, Any] = {
        "message": {
            "token": token,
            "android": android,
            "apns": {
                "headers": {"apns-priority": "10"},
                "payload": {"aps": {"content-available": 1}},
            },
            "data": {k: "" if v is None else str(v) for k, v in data.items()},
        }
    }

    headers = {
        "Authorization": f"Bearer {_get_access_token()}",
        "Content-Type": "application/json; charset=utf-8",
    }

    try:
        resp = _session.post(url, headers=headers, data=json.dumps(message), timeout=5)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("FCM send error: %s, resp=%s", e, getattr(resp, "text", None))
