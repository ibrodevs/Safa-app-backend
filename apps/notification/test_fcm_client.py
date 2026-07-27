import pytest
from django.test import override_settings

from apps.notification.fcm_client import send_data_message


@pytest.mark.django_db
@override_settings(FCM_PROJECT_ID="dogoapp-7b7a2", FCM_SERVICE_ACCOUNT_FILE="")
def test_send_data_message_skips_when_service_account_is_not_configured():
    send_data_message(
        token="demo-token",
        data={"type": "shipment_status", "shipment_id": "1"},
    )
