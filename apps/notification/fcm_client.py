from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import google.auth.transport.requests
import requests
from django.conf import settings
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]

_session = requests.Session()
_credentials: Optional[service_account.Credentials] = None


@dataclass(frozen=True)
class FCMSendResult:
    """Result of one FCM HTTP v1 delivery attempt.

    ``success`` means Firebase accepted the message for this registration token;
    it cannot guarantee that the operating system displayed it to the user.
    """

    success: bool
    deactivate_token: bool = False
    error: str = ""


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


def fcm_config_status() -> dict[str, Any]:
    """Return safe diagnostics without exposing Firebase credentials."""

    project_id = str(getattr(settings, "FCM_PROJECT_ID", "") or "").strip()
    service_account_file = str(
        getattr(settings, "FCM_SERVICE_ACCOUNT_FILE", "") or ""
    ).strip()
    error = _fcm_config_error()
    return {
        "configured": error is None,
        "project_id": project_id,
        "service_account_configured": bool(service_account_file),
        "service_account_exists": bool(service_account_file)
        and Path(service_account_file).is_file(),
        "error": error or "",
    }


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
    if not creds.valid or creds.expired or not creds.token:
        creds.refresh(auth_req)
    return str(creds.token or "")


def _is_unregistered_response(resp: requests.Response) -> bool:
    try:
        payload = resp.json()
    except (ValueError, TypeError):
        return False

    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return False

    details = error.get("details") or []
    for detail in details:
        if not isinstance(detail, dict):
            continue
        if str(detail.get("errorCode") or "").upper() == "UNREGISTERED":
            return True
    return False


def _build_message(
    *,
    token: str,
    data: Mapping[str, Any],
    ttl: str,
    collapse_key: str | None,
) -> dict[str, Any]:
    string_data = {k: "" if v is None else str(v) for k, v in data.items()}
    silent = string_data.get("silent") == "1"

    android: dict[str, Any] = {
        "priority": "HIGH",
        "ttl": ttl,
    }
    if collapse_key:
        android["collapse_key"] = collapse_key

    apns: dict[str, Any]
    if silent:
        apns = {
            "headers": {
                "apns-priority": "5",
                "apns-push-type": "background",
            },
            "payload": {"aps": {"content-available": 1}},
        }
    else:
        android["notification"] = {
            "channel_id": "dogo_main",
            "icon": "ic_stat_taxi",
            "sound": "default",
        }
        apns = {
            "headers": {
                "apns-priority": "10",
                "apns-push-type": "alert",
            },
            "payload": {
                "aps": {
                    "sound": "default",
                    "content-available": 1,
                }
            },
        }

    message: dict[str, Any] = {
        "token": token,
        "android": android,
        "apns": apns,
        "data": string_data,
    }
    if not silent:
        message["notification"] = {
            "title": string_data.get("title") or "Уведомление Safa",
            "body": string_data.get("body") or "",
        }

    return {"message": message}


def send_data_message(
    *,
    token: str,
    data: Mapping[str, Any],
    ttl: str = "15s",
    collapse_key: str | None = None,
) -> FCMSendResult:
    """Send one FCM HTTP v1 message without breaking the business action.

    Normal notifications include both visible notification fields and data, so
    Android/iOS can display them while the app is backgrounded or terminated.
    Silent messages remain data-only background pushes.
    """

    if not token:
        return FCMSendResult(success=False, error="empty_token")

    config_error = _fcm_config_error()
    if config_error:
        logger.warning("FCM send skipped: %s", config_error)
        return FCMSendResult(success=False, error=config_error)

    project_id = str(settings.FCM_PROJECT_ID).strip()
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    message = _build_message(
        token=token,
        data=data,
        ttl=ttl,
        collapse_key=collapse_key,
    )

    try:
        access_token = _get_access_token()
        if not access_token:
            raise RuntimeError("Firebase access token is empty")
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        resp = _session.post(
            url,
            headers=headers,
            data=json.dumps(message),
            timeout=5,
        )
    except Exception as exc:
        logger.warning("FCM send transport/auth error: %s", exc)
        return FCMSendResult(success=False, error=str(exc))

    if 200 <= resp.status_code < 300:
        return FCMSendResult(success=True)

    deactivate = _is_unregistered_response(resp)
    logger.warning(
        "FCM send rejected status=%s deactivate=%s resp=%s",
        resp.status_code,
        deactivate,
        resp.text,
    )
    return FCMSendResult(
        success=False,
        deactivate_token=deactivate,
        error=f"HTTP {resp.status_code}",
    )
