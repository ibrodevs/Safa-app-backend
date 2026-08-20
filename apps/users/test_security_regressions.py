import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from apps.users.enrollment import make_kyc_enrollment_token
from apps.users.models import CourierKYC, User


@pytest.mark.django_db
def test_password_login_rejects_unverified_phone():
    User.objects.create_user(
        phone_number="996700930001",
        password="secret123",
        first_name="Unverified",
        is_verify=False,
    )

    response = APIClient().post(
        "/api/users/token/",
        {"phone_number": "996700930001", "password": "secret123"},
        format="json",
    )

    assert response.status_code == 401
    assert response.data["detail"] == "phone_not_verified"


@pytest.mark.django_db
def test_carrier_wait_requires_signed_enrollment_token():
    carrier = User.objects.create_user(
        phone_number="996700930002",
        password="secret123",
        first_name="Carrier",
        role=User.Roles.CARRIER,
        is_verify=True,
        is_active=True,
    )
    kyc, _ = CourierKYC.objects.get_or_create(user=carrier)
    kyc.status = CourierKYC.Status.APPROVED
    kyc.save(update_fields=["status"])

    missing = APIClient().post(
        "/api/users/carrier-wait/",
        {"phone": carrier.phone_number},
        format="json",
    )
    valid = APIClient().post(
        "/api/users/carrier-wait/",
        {
            "phone": carrier.phone_number,
            "kyc_token": make_kyc_enrollment_token(carrier),
        },
        format="json",
    )

    assert missing.status_code == 400
    assert valid.status_code == 200
    assert valid.data["access"]
    assert valid.data["refresh"]


@pytest.mark.django_db
def test_selfie_upload_requires_token_for_same_carrier(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    carrier = User.objects.create_user(
        phone_number="996700930003",
        password="secret123",
        first_name="Carrier",
        role=User.Roles.CARRIER,
    )

    def image_file(name):
        data = io.BytesIO()
        Image.new("RGB", (2, 2), "white").save(data, format="PNG")
        return SimpleUploadedFile(name, data.getvalue(), content_type="image/png")

    missing = APIClient().post(
        "/api/users/selfie/",
        {"phone": carrier.phone_number, "selfie_id_card": image_file("missing.png")},
        format="multipart",
    )
    valid = APIClient().post(
        "/api/users/selfie/",
        {
            "phone": carrier.phone_number,
            "kyc_token": make_kyc_enrollment_token(carrier),
            "selfie_id_card": image_file("valid.png"),
        },
        format="multipart",
    )

    assert missing.status_code == 400
    assert valid.status_code == 201
    carrier.kyc.refresh_from_db()
    assert carrier.kyc.selfie_id_card.name.endswith("valid.png")
