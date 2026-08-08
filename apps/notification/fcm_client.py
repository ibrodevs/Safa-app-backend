from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import google.auth.transport.requests
import requests
from django.conf import settings
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]

_session = requests.Session()
_credentials_by_file: dict[str, service_account.Credentials] = {}


@dataclass(frozen=True)
class FCMSendResult:
    """Result of one FCM HTTP v1 delivery attempt.

    ``success`` means Firebase accepted the message for this registration token;
    it cannot guarantee that the operating system displayed it to the user.
    """

    success: bool
    deactivate_token: bool = False
    error: str = ""


def _platform_config(platform: str) -> tuple[str, str]:
    """Return the Firebase project/service-account pair for a token platform.

    The current mobile clients intentionally use different Firebase projects:
    Android -> safa-app-87b24, iOS -> dogoapp-7b7a2. A registration token can
    only be sent through the project that issued it, so one global FCM project
    is not sufficient.
    """

    platform_code = (platform or "android").strip().lower()
    generic_project = str(getattr(settings, "FCM_PROJECT_ID", "") or "").strip()
    generic_file = str(
        getattr(settings, "FCM_SERVICE_ACCOUNT_FILE", "") or ""
    ).strip()

    if platform_code == "ios":
        project_id = str(
            getattr(settings, "FCM_IOS_PROJECT_ID", "")
            or os.getenv("FCM_IOS_PROJECT_ID", "")
            or generic_project
            or "dogoapp-7b7a2"
        ).strip()
        explicit_file = str(
            getattr(settings, "FCM_IOS_SERVICE_ACCOUNT_FILE", "")
            or os.getenv("FCM_IOS_SERVICE_ACCOUNT_FILE", "")
        ).strip()
    elif platform_code == "android":
        project_id = str(
            getattr(settings, "FCM_ANDROID_PROJECT_ID", "")
            or os.getenv("FCM_ANDROID_PROJECT_ID", "")
            or "safa-app-87b24"
        ).strip()
        explicit_file = str(
            getattr(settings, "FCM_ANDROID_SERVICE_ACCOUNT_FILE", "")
            or os.getenv("FCM_ANDROID_SERVICE_ACCOUNT_FILE", "")
        ).strip()
    else:
        project_id = generic_project
        explicit_file = ""

    # Reuse the old generic credential only when it targets the same project.
    # This preserves existing deployments without ever silently sending an
    # Android token through the iOS Firebase project (or vice versa).
    service_account_file = explicit_file
    if not service_account_file and generic_project == project_id:
        service_account_file = generic_file

    return project_id, service_account_file


def _fcm_config_error(platform: str) -> str | None:
    project_id, service_account_file = _platform_config(platform)

    if not project_id:
        return f"FCM project ID is empty for {platform}"
    if not service_account_file:
        return f"FCM service account is not configured for {platform} ({project_id})"
    if not Path(service_account_file).is_file():
        return (
            f"FCM service account does not exist for {platform}: "
            f"{service_account_file}"
        )
    return None


def fcm_config_status(platform: str = "android") -> dict[str, Any]:
    """Return safe platform diagnostics without exposing Firebase secrets."""

    project_id, service_account_file = _platform_config(platform)
    error = _fcm_config_error(platform)
    return {
        "platform": platform,
        "configured": error is None,
        "project_id": project_id,
        "service_account_configured": bool(service_account_file),
        "service_account_exists": bool(service_account_file)
        and Path(service_account_file).is_file(),
        "error": error or "",
    }


def _get_credentials(service_account_file: str) -> service_account.Credentials:
    credentials = _credentials_by_file.get(service_account_file)
    if credentials is None:
        credentials = service_account.Credentials.from_service_account_file(
            service_account_file,
            scopes=SCOPES,
        )
        _credentials_by_file[service_account_file] = credentials
    return credentials


def _get_access_token(service_account_file: str) -> str:
    creds = _get_credentials(service_account_file)
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
    platform: str = "android",
) -> FCMSendResult:
    """Send one FCM HTTP v1 message without breaking the business action."""

    if not token:
        return FCMSendResult(success=False, error="empty_token")

    config_error = _fcm_config_error(platform)
    if config_error:
        logger.warning("FCM send skipped: %s", config_error)
        return FCMSendResult(success=False, error=config_error)

    project_id, service_account_file = _platform_config(platform)
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    message = _build_message(
        token=token,
        data=data,
        ttl=ttl,
        collapse_key=collapse_key,
    )

    try:
        access_token = _get_access_token(service_account_file)
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
        logger.warning("FCM send transport/auth error platform=%s: %s", platform, exc)
        return FCMSendResult(success=False, error=str(exc))

    if 200 <= resp.status_code < 300:
        return FCMSendResult(success=True)

    deactivate = _is_unregistered_response(resp)
    logger.warning(
        "FCM send rejected platform=%s status=%s deactivate=%s resp=%s",
        platform,
        resp.status_code,
        deactivate,
        resp.text,
    )
    return FCMSendResult(
        success=False,
        deactivate_token=deactivate,
        error=f"HTTP {resp.status_code}",
    )
