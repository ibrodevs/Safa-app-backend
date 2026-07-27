import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient


@pytest.mark.django_db
@override_settings(DEMO_OTP_CODE="1111")
def test_demo_otp_allows_verification_without_whatsapp():
    phone = "996700123456"
    get_user_model().objects.create_user(
        phone_number=phone,
        password="secret123",
        first_name="Demo",
    )

    client = APIClient()
    request_response = client.post(
        "/api/users/whatsapp-code/",
        {"phone": phone},
        format="json",
    )

    assert request_response.status_code == 200
    assert request_response.data["detail"] == "sent_demo"

    verify_response = client.post(
        "/api/users/verify/",
        {"phone": phone, "code": "1111"},
        format="json",
    )

    assert verify_response.status_code == 200
    assert verify_response.data["is_verify"] is True
    assert verify_response.data["access"]
    assert verify_response.data["refresh"]
