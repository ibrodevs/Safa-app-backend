from unittest.mock import Mock, patch

import pytest
import requests
from django.test import override_settings

from apps.users.chatflow import ChatFlowError, chatflow_send_text


@override_settings(
    CHATFLOW_BASE_URL="https://app.chatflow.kz",
    CHATFLOW_TOKEN="secret-token",
    CHATFLOW_FLOW_ID="flow-123",
    CHATFLOW_INSTANCE_ID="",
    CHATFLOW_TIMEOUT_SECONDS=8,
)
@patch("apps.users.chatflow.requests.get")
def test_current_chatflow_api_uses_bearer_token_and_flow_id(mock_get):
    response = Mock(ok=True, status_code=200)
    response.json.return_value = {"success": True}
    mock_get.return_value = response

    chatflow_send_text("+996 700 123 456", "OTP: 1234")

    mock_get.assert_called_once_with(
        "https://app.chatflow.kz/api/v1/n8n/action/text",
        params={
            "flow_id": "flow-123",
            "recipient": "996700123456",
            "msg": "OTP: 1234",
        },
        headers={
            "Authorization": "Bearer secret-token",
            "Accept": "application/json",
        },
        timeout=8.0,
    )


@override_settings(
    CHATFLOW_BASE_URL="https://lk.chatflow.kz",
    CHATFLOW_TOKEN="legacy-token",
    CHATFLOW_FLOW_ID="",
    CHATFLOW_INSTANCE_ID="instance-123",
)
@patch("apps.users.chatflow.requests.get")
def test_legacy_chatflow_api_remains_supported(mock_get):
    response = Mock(ok=True, status_code=200)
    response.json.return_value = True
    mock_get.return_value = response

    chatflow_send_text("996700123456", "OTP: 1234")

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["instance_id"] == "instance-123"
    assert kwargs["params"]["jid"] == "996700123456@c.us"
    assert kwargs["params"]["token"] == "legacy-token"


@override_settings(
    CHATFLOW_TOKEN="",
    CHATFLOW_FLOW_ID="",
    CHATFLOW_INSTANCE_ID="",
)
def test_chatflow_fails_before_network_when_credentials_are_missing():
    with pytest.raises(ChatFlowError, match="chatflow_token_not_configured"):
        chatflow_send_text("996700123456", "OTP")


@override_settings(
    CHATFLOW_TOKEN="secret-token",
    CHATFLOW_FLOW_ID="flow-123",
    CHATFLOW_INSTANCE_ID="",
)
@patch("apps.users.chatflow.requests.get", side_effect=requests.Timeout)
def test_chatflow_network_errors_do_not_leak_credentials(_mock_get):
    with pytest.raises(ChatFlowError, match="^chatflow_unavailable$"):
        chatflow_send_text("996700123456", "OTP")
