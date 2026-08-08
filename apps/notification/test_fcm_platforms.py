from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.notification.events import _send_to_user
from apps.notification.fcm_client import FCMSendResult, _platform_config
from apps.notification.models import FCMToken
from apps.users.models import User


@override_settings(
    FCM_PROJECT_ID="dogoapp-7b7a2",
    FCM_SERVICE_ACCOUNT_FILE="/tmp/dogo-service-account.json",
)
@patch.dict(
    "os.environ",
    {
        "FCM_ANDROID_PROJECT_ID": "",
        "FCM_ANDROID_SERVICE_ACCOUNT_FILE": "",
        "FCM_IOS_PROJECT_ID": "",
        "FCM_IOS_SERVICE_ACCOUNT_FILE": "",
    },
    clear=False,
)
def test_android_never_reuses_credentials_from_the_wrong_ios_project():
    android_project, android_file = _platform_config("android")
    ios_project, ios_file = _platform_config("ios")

    assert android_project == "safa-app-87b24"
    assert android_file == ""
    assert ios_project == "dogoapp-7b7a2"
    assert ios_file == "/tmp/dogo-service-account.json"


@pytest.mark.django_db
def test_token_platform_is_forwarded_to_fcm_sender():
    user = User.objects.create_user(
        phone_number="996700882001",
        password="pass12345",
        first_name="Push",
        role=User.Roles.CLIENT,
        is_verify=True,
    )
    FCMToken.objects.create(
        user=user,
        token="ios-platform-token",
        platform=FCMToken.Platform.IOS,
    )

    with patch(
        "apps.notification.events.send_data_message",
        return_value=FCMSendResult(success=True),
    ) as mocked_send:
        delivered = _send_to_user(
            user.id,
            {
                "app": "client",
                "type": "system_test",
                "title": "Test",
                "body": "Test",
                "channel": "system",
                "deep_link": "app://client/home",
                "silent": "0",
            },
        )

    assert delivered is True
    assert mocked_send.call_args.kwargs["platform"] == "ios"
