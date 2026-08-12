import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient


@pytest.mark.django_db
@override_settings(DEMO_OTP_CODE="1111", DEBUG=True)
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


@pytest.mark.django_db
@override_settings(DEMO_OTP_CODE="1111", DEBUG=False, CHATFLOW_TOKEN="")
def test_demo_otp_is_disabled_in_production():
    response = APIClient().post(
        "/api/users/whatsapp-code/",
        {"phone": "996700123457"},
        format="json",
    )

    assert response.status_code == 502
    assert response.data["detail"].endswith("chatflow_token_not_configured")


@pytest.mark.django_db
@override_settings(
    DEMO_OTP_CODE="1111",
    DEBUG=True,
    OTP_RESEND_COOLDOWN_SECONDS=60,
)
def test_whatsapp_otp_resend_is_rate_limited_per_phone():
    client = APIClient()
    payload = {"phone": "996700123458"}

    first = client.post("/api/users/whatsapp-code/", payload, format="json")
    second = client.post("/api/users/whatsapp-code/", payload, format="json")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.data["retry_after"] == 60


@pytest.mark.django_db
@override_settings(
    DEBUG=False,
    STATIC_OTP={"996700123459": "1111"},
    CHATFLOW_TOKEN="",
)
def test_static_otp_is_disabled_in_production():
    response = APIClient().post(
        "/api/users/whatsapp-code/",
        {"phone": "996700123459"},
        format="json",
    )

    assert response.status_code == 502
    assert response.data["detail"].endswith("chatflow_token_not_configured")
